from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
from typing import Any, Callable, Mapping

from .registry import AGENTS


MAX_MANIFEST_BYTES = 1_000_000
MAX_ARTIFACT_BYTES = 1_000_000
MANIFEST_SCHEMA_VERSION = 1
ARTIFACT_SCHEMA_VERSION = 1
APPROVED_RELEASE_REVIEWERS = frozenset({"quench"})
REQUIRED_EVIDENCE_IDS = (
    "independent_review",
    "credential_restore",
    "deployment_verification",
)
VCS_METADATA_COMPONENTS = frozenset({".git", ".hg", ".svn", ".bzr"})


@dataclass(frozen=True)
class RepositoryObservation:
    revision: str | None
    dirty_entry_count: int
    error: str | None = None


@dataclass(frozen=True)
class ReadinessCheck:
    id: str
    status: str
    required: bool
    detail: str


Runner = Callable[..., subprocess.CompletedProcess[str]]
GIT_READ_ONLY_PREFIX = (
    "git", "--no-optional-locks",
    "-c", "core.fsmonitor=false",
    "-c", "core.hooksPath=/dev/null",
)


def _git_environment() -> dict[str, str]:
    """Return an environment that cannot redirect Git away from the requested tree."""
    environment = {
        key: value for key, value in os.environ.items()
        if not key.upper().startswith("GIT_")
    }
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    environment["GIT_NO_LAZY_FETCH"] = "1"
    environment["GIT_TERMINAL_PROMPT"] = "0"
    return environment


def _git_common(repository: Path) -> dict[str, Any]:
    return {
        "cwd": repository.resolve(),
        "env": _git_environment(),
        "text": True,
        "capture_output": True,
        "timeout": 15,
        "check": False,
        "stdin": subprocess.DEVNULL,
    }


def _git_command(*arguments: str) -> list[str]:
    return [*GIT_READ_ONLY_PREFIX, *arguments]


def _valid_git_object_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) in {40, 64}
        and all(character in "0123456789abcdefABCDEF" for character in value)
    )


def inspect_repository(repository: Path, *, runner: Runner = subprocess.run) -> RepositoryObservation:
    """Inspect stable local Git state without optional locks, writes, or network access."""
    root = repository.resolve()
    common = _git_common(root)
    try:
        revision_before = runner(
            _git_command("rev-parse", "--verify", "HEAD^{commit}"),
            **common,
        )
        status = runner(
            _git_command("status", "--porcelain=v1", "--untracked-files=all"),
            **common,
        )
        revision_after = runner(
            _git_command("rev-parse", "--verify", "HEAD^{commit}"),
            **common,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return RepositoryObservation(None, 0, f"repository inspection failed: {type(exc).__name__}")
    if any(result.returncode != 0 for result in (revision_before, status, revision_after)):
        return RepositoryObservation(None, 0, "repository inspection failed")
    head_before = revision_before.stdout.strip()
    head_after = revision_after.stdout.strip()
    if not head_before or head_before != head_after:
        return RepositoryObservation(None, 0, "repository revision changed during inspection")
    if not _valid_git_object_id(head_after):
        return RepositoryObservation(None, 0, "repository revision is unavailable")
    dirty_count = len([line for line in status.stdout.splitlines() if line.strip()])
    return RepositoryObservation(head_after, dirty_count)


def _read_bounded_relative_file(
        anchor: Path, components: tuple[str, ...], *, maximum: int,
        label: str) -> tuple[bytes | None, str | None]:
    """Read a regular file through no-follow directory descriptors."""
    if (not components or any(part in {"", ".", ".."} for part in components)
            or not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY")):
        return None, f"{label} path cannot be opened safely"
    directory_descriptor = -1
    file_descriptor = -1
    directory_flags = (
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    )
    file_flags = (
        os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        directory_descriptor = os.open(anchor, directory_flags)
        for component in components[:-1]:
            next_descriptor = os.open(
                component, directory_flags, dir_fd=directory_descriptor,
            )
            previous_descriptor = directory_descriptor
            directory_descriptor = next_descriptor
            os.close(previous_descriptor)
        file_descriptor = os.open(
            components[-1], file_flags, dir_fd=directory_descriptor,
        )
        before = os.fstat(file_descriptor)
        if not stat.S_ISREG(before.st_mode):
            return None, f"{label} is not a regular file"
        if before.st_size <= 0:
            return None, f"{label} is empty"
        if before.st_size > maximum:
            return None, f"{label} exceeds the size limit"

        chunks: list[bytes] = []
        remaining = maximum + 1
        while remaining:
            chunk = os.read(file_descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        after = os.fstat(file_descriptor)
        stable_fields = (
            "st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns",
        )
        if (any(getattr(before, field) != getattr(after, field) for field in stable_fields)
                or len(content) != before.st_size):
            return None, f"{label} changed while reading"
    except OSError:
        return None, f"{label} is missing or cannot be opened safely"
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        if directory_descriptor >= 0:
            os.close(directory_descriptor)
    if len(content) > maximum:
        return None, f"{label} exceeds the size limit"
    if not content.strip():
        return None, f"{label} is empty"
    return content, None


def _read_bounded_path(
        path: Path, *, maximum: int, label: str) -> tuple[bytes | None, str | None]:
    absolute = Path(os.path.abspath(os.fspath(path)))
    if not absolute.anchor:
        return None, f"{label} path cannot be opened safely"
    return _read_bounded_relative_file(
        Path(absolute.anchor), tuple(absolute.parts[1:]), maximum=maximum, label=label,
    )


def _strict_json_loads(content: bytes) -> Any:
    def object_from_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON object key")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON constant: {value}")

    return json.loads(
        content.decode("utf-8"),
        object_pairs_hook=object_from_pairs,
        parse_constant=reject_constant,
    )


def _manifest_schema_error(value: Mapping[str, Any]) -> str | None:
    if set(value) != {"schema_version", "evidence"}:
        return "release evidence manifest must contain only schema_version and evidence"
    if (type(value.get("schema_version")) is not int
            or value["schema_version"] != MANIFEST_SCHEMA_VERSION):
        return f"release evidence manifest schema_version must be {MANIFEST_SCHEMA_VERSION}"
    evidence = value.get("evidence")
    if not isinstance(evidence, Mapping):
        return "release evidence manifest evidence must be a JSON object"
    if set(evidence) - set(REQUIRED_EVIDENCE_IDS):
        return "release evidence manifest contains an unknown evidence type"
    for record in evidence.values():
        if not isinstance(record, Mapping) or set(record) != {"revision", "artifact"}:
            return "each evidence record must contain only revision and artifact"
        if (not isinstance(record.get("revision"), str) or not record["revision"].strip()
                or not isinstance(record.get("artifact"), str) or not record["artifact"].strip()):
            return "evidence revision and artifact must be nonempty strings"
    return None


def load_evidence_manifest(path: Path | None) -> tuple[dict[str, Any], str | None]:
    """Read a bounded, fixed-schema manifest without following path symlinks."""
    if path is None:
        return {}, "release evidence manifest was not provided"
    content, read_error = _read_bounded_path(
        path, maximum=MAX_MANIFEST_BYTES, label="release evidence manifest",
    )
    if read_error is not None:
        return {}, read_error
    try:
        value = _strict_json_loads(content or b"")
    except (UnicodeError, json.JSONDecodeError, ValueError):
        return {}, "release evidence manifest could not be read as JSON"
    if not isinstance(value, dict):
        return {}, "release evidence manifest must be a JSON object"
    schema_error = _manifest_schema_error(value)
    if schema_error is not None:
        return {}, schema_error
    return value, None


def _normalize_artifact_path(artifact: object) -> tuple[str | None, str | None]:
    if not isinstance(artifact, str) or not artifact.strip():
        return None, "evidence artifact path is missing"
    raw = Path(artifact)
    if (raw.is_absolute() or not raw.parts
            or any(part in {"", ".", ".."} for part in raw.parts)):
        return None, "evidence artifact must be a normalized repository-relative path"
    if any(part.casefold() in VCS_METADATA_COMPONENTS for part in raw.parts):
        return None, "evidence artifact must not use repository metadata"
    normalized = Path(*raw.parts).as_posix()
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        return None, "evidence artifact path contains control characters"
    return normalized, None


def _read_local_artifact(
        repository: Path, artifact: object,
) -> tuple[bytes | None, str | None, str | None]:
    normalized, path_error = _normalize_artifact_path(artifact)
    if path_error is not None:
        return None, None, path_error
    root = repository.resolve()
    content, read_error = _read_bounded_relative_file(
        Path(root.anchor), tuple(root.parts[1:]) + tuple(Path(normalized or "").parts),
        maximum=MAX_ARTIFACT_BYTES, label="evidence artifact",
    )
    return content, normalized, read_error


def _tracked_artifact_error(
        repository: Path, revision: str, artifact_path: str, content: bytes,
        *, runner: Runner,
) -> str | None:
    """Require the exact bytes to be a tracked blob in the inspected commit."""
    if not _valid_git_object_id(revision):
        return "inspected repository revision is invalid"
    common = _git_common(repository)
    try:
        tracked = runner(
            _git_command("--literal-pathspecs", "ls-files", "--error-unmatch", "--",
                         artifact_path),
            **common,
        )
        blob = runner(
            _git_command("rev-parse", "--verify", f"{revision}:{artifact_path}"),
            **common,
        )
    except (OSError, subprocess.SubprocessError):
        return "evidence artifact tracking could not be verified"
    if tracked.returncode != 0 or blob.returncode != 0:
        return "evidence artifact must be tracked at the inspected revision"
    expected_oid = blob.stdout.strip().lower()
    if (len(expected_oid) not in {40, 64}
            or any(character not in "0123456789abcdef" for character in expected_oid)):
        return "evidence artifact blob identity is invalid"
    algorithm = "sha1" if len(expected_oid) == 40 else "sha256"
    digest = hashlib.new(
        algorithm, b"blob " + str(len(content)).encode("ascii") + b"\0" + content,
    ).hexdigest()
    if digest != expected_oid:
        return "evidence artifact bytes differ from the inspected revision"
    return None


def _artifact_claim_error(evidence_id: str, content: bytes) -> str | None:
    try:
        claim = _strict_json_loads(content)
    except (UnicodeError, json.JSONDecodeError, ValueError):
        return "evidence artifact must be valid JSON"
    if not isinstance(claim, Mapping):
        return "evidence artifact must be a JSON object"

    shared = {"schema_version", "evidence_type"}
    if evidence_id == "independent_review":
        expected_fields = shared | {"reviewer", "author", "disposition"}
    else:
        expected_fields = shared | {"target", "verifier", "observed_at", "result"}
    if set(claim) != expected_fields:
        return f"{evidence_id} artifact does not match its fixed schema"
    if (type(claim.get("schema_version")) is not int
            or claim["schema_version"] != ARTIFACT_SCHEMA_VERSION):
        return f"evidence artifact schema_version must be {ARTIFACT_SCHEMA_VERSION}"
    if claim.get("evidence_type") != f"orca.{evidence_id}":
        return "evidence artifact has the wrong evidence type"

    if evidence_id == "independent_review":
        reviewer_id = claim.get("reviewer")
        author_id = claim.get("author")
        reviewer = AGENTS.get(reviewer_id) if isinstance(reviewer_id, str) else None
        author = AGENTS.get(author_id) if isinstance(author_id, str) else None
        if claim.get("disposition") != "approved":
            return "independent review artifact must claim an approved disposition"
        if (reviewer_id not in APPROVED_RELEASE_REVIEWERS or reviewer is None
                or not reviewer.may_review):
            return "independent review artifact must name an allowlisted release reviewer"
        if reviewer_id == author_id:
            return "implementation author and release reviewer must be different identities"
        if author is None or not author.may_author:
            return "independent review artifact must name the registered implementation author"
        return None

    for field in ("target", "verifier", "observed_at"):
        if not isinstance(claim.get(field), str) or not claim[field].strip():
            return f"{evidence_id} artifact {field} must be nonempty text"
    if claim.get("result") != "verified":
        return f"{evidence_id} artifact must claim a verified result"
    return None


def _evidence_check(
        *, repository: Path, revision: str | None, evidence: Mapping[str, Any],
        evidence_id: str, runner: Runner,
) -> ReadinessCheck:
    record = evidence.get(evidence_id)
    if not isinstance(record, Mapping):
        return ReadinessCheck(evidence_id, "blocked", True, "required evidence is missing")
    if (not _valid_git_object_id(revision)
            or record.get("revision") != revision):
        return ReadinessCheck(
            evidence_id, "blocked", True,
            "evidence is not bound to the inspected repository revision",
        )
    artifact, artifact_path, artifact_error = _read_local_artifact(
        repository, record.get("artifact"),
    )
    if artifact_error is not None:
        return ReadinessCheck(evidence_id, "blocked", True, artifact_error)
    tracking_error = _tracked_artifact_error(
        repository, revision, artifact_path or "", artifact or b"", runner=runner,
    )
    if tracking_error is not None:
        return ReadinessCheck(evidence_id, "blocked", True, tracking_error)
    claim_error = _artifact_claim_error(evidence_id, artifact or b"")
    if claim_error is not None:
        return ReadinessCheck(evidence_id, "blocked", True, claim_error)
    return ReadinessCheck(
        evidence_id, "present_unverified", True,
        "tracked structural evidence is present, but no external or pinned verifier is available",
    )


def evaluate_release_readiness(
        repository: Path, observation: RepositoryObservation,
        manifest: Mapping[str, Any] | None = None, *, manifest_error: str | None = None,
        runner: Runner = subprocess.run,
) -> dict[str, Any]:
    """Return a deterministic structural diagnostic that never grants readiness."""
    root = repository.resolve()
    if not isinstance(manifest, Mapping):
        manifest = {}
        manifest_error = manifest_error or "release evidence manifest must be a JSON object"
    if manifest_error is None:
        manifest_error = _manifest_schema_error(manifest)
    evidence = manifest.get("evidence", {}) if manifest_error is None else {}
    if not isinstance(evidence, Mapping):
        evidence = {}

    checks: list[ReadinessCheck] = []
    if observation.error:
        checks.append(ReadinessCheck("repository_revision", "blocked", True, observation.error))
    else:
        checks.append(ReadinessCheck(
            "repository_revision", "satisfied", True,
            "local repository revision was resolved and stable during inspection",
        ))
    checks.append(ReadinessCheck(
        "clean_worktree",
        "satisfied" if observation.error is None and observation.dirty_entry_count == 0 else "blocked",
        True,
        ("working tree is clean" if observation.error is None and observation.dirty_entry_count == 0
         else f"working tree has {observation.dirty_entry_count} uncommitted or untracked entries"),
    ))
    if manifest_error:
        checks.append(ReadinessCheck("evidence_manifest", "blocked", True, manifest_error))
    else:
        checks.append(ReadinessCheck(
            "evidence_manifest", "satisfied", True,
            "bounded fixed-schema local manifest loaded; its claims are not trusted",
        ))

    for evidence_id in REQUIRED_EVIDENCE_IDS:
        checks.append(_evidence_check(
            repository=root,
            revision=observation.revision,
            evidence=evidence,
            evidence_id=evidence_id,
            runner=runner,
        ))

    rendered_checks = [asdict(check) for check in checks]
    structural_inputs_present = not any(
        check["status"] == "blocked" for check in rendered_checks
    )
    blockers = [
        check["id"] for check in rendered_checks
        if check["status"] in {"blocked", "present_unverified"}
    ]
    return {
        "schema_version": 3,
        "status": "blocked",
        "production_ready": False,
        "structural_inputs_present": structural_inputs_present,
        "repository": str(root),
        "revision": observation.revision,
        "checks": rendered_checks,
        "blockers": blockers,
        "unverified_evidence": [
            check["id"] for check in rendered_checks
            if check["status"] == "present_unverified"
        ],
        "safety": {
            "network_access": "none",
            "repository_writes": "none",
            "external_verification": "unavailable",
            "result_is_approval": False,
        },
        "limitations": [
            "This report is a local structural preflight, not release approval or production readiness.",
            "Local manifests and artifacts cannot authenticate reviewer, credential, or deployment claims.",
            "A separately trusted verifier with pinned external trust roots is required to clear blockers.",
            "Fry's explicit release decision and applicable independent review remain authoritative.",
        ],
    }


def check_release_readiness(
        repository: Path, manifest_path: Path | None, *, runner: Runner = subprocess.run,
) -> dict[str, Any]:
    observation = inspect_repository(repository, runner=runner)
    manifest, manifest_error = load_evidence_manifest(manifest_path)
    return evaluate_release_readiness(
        repository, observation, manifest, manifest_error=manifest_error, runner=runner,
    )
