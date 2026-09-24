from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from orca.readiness import (
    RepositoryObservation,
    check_release_readiness,
    evaluate_release_readiness,
    inspect_repository,
    load_evidence_manifest,
)
from scripts import check_release_readiness as readiness_cli


REVISION = "a" * 40
TEMPORARY_ROOT = Path(tempfile.gettempdir()).resolve()


def temporary_directory():
    return tempfile.TemporaryDirectory(dir=TEMPORARY_ROOT)


def write_artifacts(
        root: Path, *, reviewer: str = "quench", author: str = "smith",
        credential_content: dict | None = None) -> None:
    evidence = root / "evidence"
    evidence.mkdir(exist_ok=True)
    (evidence / "review.json").write_text(json.dumps({
        "schema_version": 1,
        "evidence_type": "orca.independent_review",
        "reviewer": reviewer,
        "author": author,
        "disposition": "approved",
    }), encoding="utf-8")
    credential = credential_content if credential_content is not None else {
        "schema_version": 1,
        "evidence_type": "orca.credential_restore",
        "target": "forge",
        "verifier": "host-secret-system",
        "observed_at": "2026-09-23T12:00:00Z",
        "result": "verified",
    }
    (evidence / "credentials.json").write_text(json.dumps(credential), encoding="utf-8")
    (evidence / "deployment.json").write_text(json.dumps({
        "schema_version": 1,
        "evidence_type": "orca.deployment_verification",
        "target": "forge",
        "verifier": "deployment-observer",
        "observed_at": "2026-09-23T12:05:00Z",
        "result": "verified",
    }), encoding="utf-8")


def commit_all(root: Path, message: str = "evidence fixture") -> str:
    if not (root / ".git").exists():
        subprocess.run(
            ["git", "init", "-q"], cwd=root, check=True,
            text=True, capture_output=True,
        )
    subprocess.run(
        ["git", "add", "--", "."], cwd=root, check=True,
        text=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-c", "user.name=Readiness Test",
         "-c", "user.email=readiness@example.invalid", "commit", "-qm", message],
        cwd=root, check=True, text=True, capture_output=True,
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True,
        text=True, capture_output=True,
    ).stdout.strip()


def manifest_for(revision: str) -> dict:
    return {
        "schema_version": 1,
        "evidence": {
            "independent_review": {
                "revision": revision,
                "artifact": "evidence/review.json",
            },
            "credential_restore": {
                "revision": revision,
                "artifact": "evidence/credentials.json",
            },
            "deployment_verification": {
                "revision": revision,
                "artifact": "evidence/deployment.json",
            },
        },
    }


class ReleaseReadinessTests(unittest.TestCase):
    def test_dirty_tree_and_missing_evidence_are_truthful_blockers(self):
        with temporary_directory() as raw:
            report = evaluate_release_readiness(
                Path(raw), RepositoryObservation(REVISION, 4),
                {"schema_version": 1, "evidence": {}},
            )
        self.assertEqual(report["status"], "blocked")
        self.assertFalse(report["production_ready"])
        self.assertFalse(report["structural_inputs_present"])
        self.assertEqual(
            set(report["blockers"]),
            {"clean_worktree", "independent_review", "credential_restore",
             "deployment_verification"},
        )
        self.assertEqual(report["safety"]["network_access"], "none")

    def test_complete_local_structure_remains_unverified_and_blocking(self):
        with temporary_directory() as raw:
            root = Path(raw)
            write_artifacts(root)
            revision = commit_all(root)
            report = evaluate_release_readiness(
                root, RepositoryObservation(revision, 0), manifest_for(revision)
            )
        self.assertEqual(report["status"], "blocked")
        self.assertTrue(report["structural_inputs_present"])
        self.assertFalse(report["production_ready"])
        self.assertEqual(set(report["blockers"]), set(manifest_for(revision)["evidence"]))
        self.assertEqual(set(report["unverified_evidence"]), set(report["blockers"]))
        statuses = {check["id"]: check["status"] for check in report["checks"]}
        for evidence_id in manifest_for(revision)["evidence"]:
            self.assertEqual(statuses[evidence_id], "present_unverified")
        self.assertEqual(report["schema_version"], 3)
        self.assertEqual(report["safety"]["external_verification"], "unavailable")

    def test_manifest_cannot_define_requirements_or_status(self):
        with temporary_directory() as raw:
            root = Path(raw)
            write_artifacts(root)
            revision = commit_all(root)
            manifest = manifest_for(revision)
            manifest["requirements"] = {"credentials": False}
            report = evaluate_release_readiness(
                root, RepositoryObservation(revision, 0), manifest
            )
            self.assertIn("evidence_manifest", report["blockers"])
            manifest = manifest_for(revision)
            manifest["evidence"]["credential_restore"]["status"] = "verified"
            report = evaluate_release_readiness(
                root, RepositoryObservation(revision, 0), manifest
            )
        self.assertIn("evidence_manifest", report["blockers"])
        manifest_check = next(
            check for check in report["checks"] if check["id"] == "evidence_manifest"
        )
        self.assertIn("only revision and artifact", manifest_check["detail"])

    def test_artifacts_must_be_revision_bound_and_repository_local(self):
        with temporary_directory() as raw:
            root = Path(raw)
            write_artifacts(root)
            revision = commit_all(root)
            manifest = manifest_for(revision)
            manifest["evidence"]["independent_review"]["revision"] = "b" * 40
            report = evaluate_release_readiness(
                root, RepositoryObservation(revision, 0), manifest
            )
            self.assertIn("independent_review", report["blockers"])

            outside = root.parent / f"{root.name}-outside.json"
            outside.write_text("{}", encoding="utf-8")
            manifest["evidence"]["independent_review"] = {
                "revision": revision,
                "artifact": str(outside),
            }
            report = evaluate_release_readiness(
                root, RepositoryObservation(revision, 0), manifest
            )
            self.assertIn("independent_review", report["blockers"])
            outside.unlink()

            link = root / "linked-review.json"
            link.symlink_to(root / "evidence" / "review.json")
            manifest["evidence"]["independent_review"]["artifact"] = "linked-review.json"
            report = evaluate_release_readiness(
                root, RepositoryObservation(revision, 0), manifest
            )
        self.assertIn("independent_review", report["blockers"])

    def test_empty_and_schema_free_artifacts_are_rejected(self):
        with temporary_directory() as raw:
            root = Path(raw)
            write_artifacts(root, credential_content={})
            (root / "evidence" / "deployment.json").write_bytes(b"")
            revision = commit_all(root)
            report = evaluate_release_readiness(
                root, RepositoryObservation(revision, 0), manifest_for(revision)
            )
        checks = {check["id"]: check for check in report["checks"]}
        self.assertEqual(checks["credential_restore"]["status"], "blocked")
        self.assertIn("fixed schema", checks["credential_restore"]["detail"])
        self.assertEqual(checks["deployment_verification"]["status"], "blocked")
        self.assertIn("empty", checks["deployment_verification"]["detail"])

    def test_review_allowlist_and_separation_are_only_structural_claim_checks(self):
        with temporary_directory() as raw:
            root = Path(raw)
            write_artifacts(root, reviewer="fry")
            revision = commit_all(root, "unallowlisted reviewer")
            report = evaluate_release_readiness(
                root, RepositoryObservation(revision, 0), manifest_for(revision)
            )
            check = next(item for item in report["checks"]
                         if item["id"] == "independent_review")
            self.assertEqual(check["status"], "blocked")
            self.assertIn("allowlisted", check["detail"])

            write_artifacts(root, reviewer="quench", author="quench")
            revision = commit_all(root, "same author and reviewer")
            report = evaluate_release_readiness(
                root, RepositoryObservation(revision, 0), manifest_for(revision)
            )
            check = next(item for item in report["checks"]
                         if item["id"] == "independent_review")
            self.assertEqual(check["status"], "blocked")
            self.assertIn("different identities", check["detail"])

            write_artifacts(root)
            revision = commit_all(root, "structurally valid claim")
            report = evaluate_release_readiness(
                root, RepositoryObservation(revision, 0), manifest_for(revision)
            )
            check = next(item for item in report["checks"]
                         if item["id"] == "independent_review")
        self.assertEqual(check["status"], "present_unverified")
        self.assertIn("independent_review", report["blockers"])

    def test_ignored_untracked_changed_and_vcs_metadata_artifacts_are_rejected(self):
        with temporary_directory() as raw:
            root = Path(raw)
            write_artifacts(root)
            (root / ".gitignore").write_text("ignored/\n", encoding="utf-8")
            revision = commit_all(root)
            ignored = root / "ignored"
            ignored.mkdir()
            (ignored / "review.json").write_text(
                (root / "evidence" / "review.json").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            manifest = manifest_for(revision)
            manifest["evidence"]["independent_review"]["artifact"] = "ignored/review.json"
            report = evaluate_release_readiness(
                root, RepositoryObservation(revision, 0), manifest
            )
            check = next(item for item in report["checks"]
                         if item["id"] == "independent_review")
            self.assertIn("tracked", check["detail"])

            (root / "evidence" / "review.json").write_text(json.dumps({
                "schema_version": 1,
                "evidence_type": "orca.independent_review",
                "reviewer": "quench",
                "author": "smith",
                "disposition": "denied",
            }), encoding="utf-8")
            manifest = manifest_for(revision)
            report = evaluate_release_readiness(
                root, RepositoryObservation(revision, 0), manifest
            )
            check = next(item for item in report["checks"]
                         if item["id"] == "independent_review")
            self.assertIn("differ", check["detail"])

            manifest["evidence"]["independent_review"]["artifact"] = ".git/config"
            report = evaluate_release_readiness(
                root, RepositoryObservation(revision, 0), manifest
            )
            check = next(item for item in report["checks"]
                         if item["id"] == "independent_review")
        self.assertIn("metadata", check["detail"])

    def test_manifest_loader_enforces_fixed_schema_and_rejects_symlinks(self):
        with temporary_directory() as raw:
            root = Path(raw)
            missing, error = load_evidence_manifest(root / "missing.json")
            self.assertEqual(missing, {})
            self.assertIn("missing", error)

            invalid = root / "invalid.json"
            invalid.write_text("[]", encoding="utf-8")
            value, error = load_evidence_manifest(invalid)
            self.assertEqual(value, {})
            self.assertIn("JSON object", error)

            wrong_schema = root / "wrong-schema.json"
            wrong_schema.write_text(json.dumps({
                "schema_version": 1,
                "evidence": {},
                "requirements": {},
            }), encoding="utf-8")
            value, error = load_evidence_manifest(wrong_schema)
            self.assertEqual(value, {})
            self.assertIn("only schema_version and evidence", error)

            boolean_schema = root / "boolean-schema.json"
            boolean_schema.write_text(json.dumps({
                "schema_version": True,
                "evidence": {},
            }), encoding="utf-8")
            value, error = load_evidence_manifest(boolean_schema)
            self.assertEqual(value, {})
            self.assertIn("schema_version", error)

            duplicate = root / "duplicate.json"
            duplicate.write_text(
                '{"schema_version":1,"schema_version":1,"evidence":{}}',
                encoding="utf-8",
            )
            value, error = load_evidence_manifest(duplicate)
            self.assertEqual(value, {})
            self.assertIn("read as JSON", error)

            target = root / "target.json"
            target.write_text(json.dumps({
                "schema_version": 1, "evidence": {},
            }), encoding="utf-8")
            link = root / "link.json"
            link.symlink_to(target)
            value, error = load_evidence_manifest(link)
            self.assertEqual(value, {})
            self.assertIn("safely", error)

            real_parent = root / "real-parent"
            real_parent.mkdir()
            nested = real_parent / "manifest.json"
            nested.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
            parent_link = root / "parent-link"
            parent_link.symlink_to(real_parent, target_is_directory=True)
            value, error = load_evidence_manifest(parent_link / "manifest.json")
            self.assertEqual(value, {})
            self.assertIn("safely", error)

    def test_repository_probe_scrubs_git_environment_and_stabilizes_head(self):
        calls: list[tuple[list[str], dict]] = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            stdout = " M orca/readiness.py\n" if "status" in command else f"{REVISION}\n"
            return subprocess.CompletedProcess(command, 0, stdout, "")

        with patch.dict(os.environ, {"GIT_DIR": "/tmp/redirected"}):
            observation = inspect_repository(Path("."), runner=runner)
        self.assertEqual(observation, RepositoryObservation(REVISION, 1))
        self.assertEqual(len(calls), 3)
        for command, kwargs in calls:
            self.assertIn("--no-optional-locks", command)
            self.assertEqual(kwargs["env"]["GIT_OPTIONAL_LOCKS"], "0")
            self.assertEqual(kwargs["env"]["GIT_NO_LAZY_FETCH"], "1")
            self.assertEqual(kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")
            self.assertNotIn("GIT_DIR", kwargs["env"])
            self.assertNotIn("fetch", command)
            self.assertNotIn("pull", command)

        revisions = iter((f"{'a' * 40}\n", "", f"{'b' * 40}\n"))

        def changing_runner(command, **kwargs):
            return subprocess.CompletedProcess(command, 0, next(revisions), "")

        observation = inspect_repository(Path("."), runner=changing_runner)
        self.assertIn("changed", observation.error or "")

    def test_end_to_end_accepts_injected_repository_probe(self):
        with temporary_directory() as raw:
            root = Path(raw)
            manifest_path = root / "release.json"
            manifest_path.write_text(json.dumps({
                "schema_version": 1,
                "evidence": {},
            }), encoding="utf-8")

            def runner(command, **kwargs):
                stdout = "" if "status" in command else f"{REVISION}\n"
                return subprocess.CompletedProcess(command, 0, stdout, "")

            report = check_release_readiness(root, manifest_path, runner=runner)
        self.assertIn("independent_review", report["blockers"])
        self.assertFalse(report["production_ready"])
        self.assertFalse(report["structural_inputs_present"])

    def test_cli_never_returns_success_for_a_release_decision(self):
        structural_report = {
            "production_ready": False,
            "structural_inputs_present": True,
            "blockers": ["independent_review"],
        }
        with patch.object(readiness_cli, "check_release_readiness",
                          return_value=structural_report), redirect_stdout(io.StringIO()):
            self.assertEqual(readiness_cli.main([]), 2)
        incomplete_report = {
            "production_ready": False,
            "structural_inputs_present": False,
            "blockers": ["evidence_manifest"],
        }
        with patch.object(readiness_cli, "check_release_readiness",
                          return_value=incomplete_report), redirect_stdout(io.StringIO()):
            self.assertEqual(readiness_cli.main([]), 1)


if __name__ == "__main__":
    unittest.main()
