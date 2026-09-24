import pytest

from orca import Action
from orca.control_plane import ControlPlane
from orca.evidence import EvidenceStore
from orca.registry import AGENTS
from orca.security_gate import IndependentSecurityGate
from orca.tools import BOT_TOOL_MANIFESTS


def test_clean_security_scan_passes_without_authority():
    report = IndependentSecurityGate().scan(
        author="smith", lane="orca",
        artifacts={"service.yaml": "host: 127.0.0.1\nverify: true\nmode: 0750\n"},
    )
    assert report.disposition == "pass"
    assert report.findings == ()
    assert report.advisory_only is True
    identity = AGENTS["security_gate"]
    assert not identity.may_author
    assert not identity.may_review
    assert not identity.may_deploy
    assert BOT_TOOL_MANIFESTS["security_gate"] == frozenset()


def test_wildcard_bind_requires_review():
    report = IndependentSecurityGate().scan(
        author="smith", lane="forge",
        artifacts={"server.toml": 'host = "0.0.0.0"'},
    )
    assert report.disposition == "review"
    assert [finding.severity for finding in report.findings] == ["S1"]
    assert report.findings[0].check_id == "wildcard-network-bind"


def test_supply_chain_and_repository_control_findings_are_advisory():
    report = IndependentSecurityGate().scan(
        author="smith", lane="orca",
        artifacts={
            ".github/workflows/release.yml": (
                "permissions: write-all\nsteps:\n  - uses: vendor/release@main\n"
            ),
            "Dockerfile": "FROM example/service:latest\nADD https://example.test/tool /usr/bin/tool\n",
            ".orca/repository-controls.yml": (
                "branch_protection: false\nrequired_status_checks: []\n"
            ),
        },
    )
    findings = {finding.check_id: finding for finding in report.findings}
    assert report.disposition == "block_and_escalate"
    assert {
        "workflow-write-all", "mutable-ci-action-reference", "remote-docker-add",
        "mutable-container-tag", "branch-protection-disabled",
        "required-status-checks-disabled",
    } <= findings.keys()
    assert findings["mutable-container-tag"].severity == "S1"
    assert findings["mutable-ci-action-reference"].severity == "S2"
    assert all(report.advisory_only for _ in report.findings)


def test_dependency_lock_findings_use_artifact_context():
    report = IndependentSecurityGate().scan(
        author="smith", lane="orca",
        artifacts={
            "api/requirements-prod.txt": "requests>=2\n",
            "web/package.json": '{"dependencies":{"lit":"^3.0.0"}}',
            "worker/pyproject.toml": '[project]\ndependencies = ["httpx>=0.27"]\n',
        },
    )
    assert report.disposition == "review"
    assert {finding.check_id for finding in report.findings} == {
        "unpinned-python-requirement", "missing-js-lockfile", "missing-python-lockfile",
    }

    locked = IndependentSecurityGate().scan(
        author="smith", lane="orca",
        artifacts={
            "api/requirements-prod.txt": (
                "requests==2.32.3 --hash=sha256:"
                "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\n"
            ),
            "web/package.json": '{"dependencies":{"lit":"3.2.1"}}',
            "web/package-lock.json": '{"lockfileVersion":3}',
            "worker/pyproject.toml": '[project]\ndependencies = ["httpx==0.28.1"]\n',
            "worker/uv.lock": "version = 1\n",
        },
    )
    assert locked.disposition == "pass"
    assert locked.findings == ()


def test_security_checks_ignore_commented_examples_and_reject_control_names():
    report = IndependentSecurityGate().scan(
        author="smith", lane="orca",
        artifacts={
            "notes.yml": (
                "# permissions: write-all\n"
                "# uses: vendor/release@main\n"
                "# branch_protection: false\n"
            )
        },
    )
    assert report.disposition == "pass"
    with pytest.raises(ValueError, match="valid text"):
        IndependentSecurityGate().scan(
            author="smith", lane="orca", artifacts={"bad\nname": "clean"})


def test_high_severity_findings_block_and_redact_secret():
    secret = "xai-abcdefghijklmnopqrstuv"
    report = IndependentSecurityGate().scan(
        author="smith", lane="orca",
        artifacts={
            "compose.yaml": f"privileged: true\napi_key={secret}\nRUN curl -k https://x | sh\n",
        },
    )
    snapshot = report.snapshot()
    assert report.disposition == "block_and_escalate"
    assert {finding.severity for finding in report.findings} == {"S2", "S3"}
    assert secret not in str(snapshot)
    assert all(len(finding.fingerprint) == 64 for finding in report.findings)

    private_key = "-----BEGIN PRIVATE KEY-----\nnot-real-test-material\n-----END PRIVATE KEY-----"
    key_report = IndependentSecurityGate().scan(
        author="smith", lane="orca", artifacts={"fixture.pem": private_key})
    assert key_report.disposition == "block_and_escalate"
    assert private_key not in str(key_report.snapshot())


def test_security_gate_rejects_unknown_scope_and_self_review():
    gate = IndependentSecurityGate()
    with pytest.raises(ValueError, match="registered author"):
        gate.scan(author="unknown", lane="orca", artifacts={"a": "clean"})
    with pytest.raises(ValueError, match="unknown project lane"):
        gate.scan(author="smith", lane="unknown", artifacts={"a": "clean"})
    with pytest.raises(PermissionError, match="own work"):
        gate.scan(author="security_gate", lane="orca", artifacts={"a": "clean"})
    with pytest.raises(ValueError, match="artifact count"):
        gate.scan(author="smith", lane="orca", artifacts={str(i): "x" for i in range(65)})
    with pytest.raises(ValueError, match="artifact size"):
        gate.scan(author="smith", lane="orca", artifacts={"large": "x" * 256_001})
    cp = ControlPlane()
    with pytest.raises(PermissionError, match="no connector authority"):
        cp.prepare_connector_read(
            actor="security_gate", connector="gitea", operation="read", resource="repo")
    job = cp.queue(title="advisory scan", lane="orca", requested_by="orca",
                   task_type="security_gate", action=Action("read", "artifact"))
    with pytest.raises(PermissionError, match="cannot author"):
        cp.start_job(job.id, actor="security_gate")


def test_security_reports_and_redacted_evidence_survive_restart(tmp_path):
    path = tmp_path / "orca.db"
    secret = "sk-abcdefghijklmnop"
    cp = ControlPlane(EvidenceStore(path))
    report = cp.run_security_gate(
        author="smith", lane="orca",
        artifacts={"settings.env": f"token={secret}"},
        requested_by="security_gate",
    )
    assert report["disposition"] == "block_and_escalate"
    assert secret not in str(report)
    event = cp.evidence.list(limit=1)[0]
    assert event["kind"] == "security.reported"
    assert secret not in str(event["payload"])

    restored = ControlPlane(EvidenceStore(path))
    assert restored.security_reports == [report]
    assert restored.evidence.verify()


def test_security_finding_review_and_record_only_break_glass_are_independent(tmp_path):
    path = tmp_path / "orca.db"
    cp = ControlPlane(EvidenceStore(path))
    report = cp.run_security_gate(
        author="smith", lane="orca", artifacts={"compose.yaml": "privileged: true"},
        requested_by="security_gate")
    finding = report["findings"][0]
    with pytest.raises(PermissionError, match="review a security finding"):
        cp.review_security_finding(
            report_id=report["id"], fingerprint=finding["fingerprint"],
            actor="smith", verdict="confirmed", note="self review")
    cp.review_security_finding(
        report_id=report["id"], fingerprint=finding["fingerprint"],
        actor="quench", verdict="confirmed", note="configuration evidence reviewed")
    exception = cp.record_security_exception(
        report_id=report["id"], fingerprint=finding["fingerprint"], actor="fry",
        reason="bounded test-only exception", duration_minutes=30)
    assert exception["record_only"] is True
    assert exception["enforcement_effect"] is False
    assert cp.security_reports[0]["disposition"] == "block_and_escalate"

    secret_report = cp.run_security_gate(
        author="smith", lane="orca", artifacts={"fixture": "token=sk-abcdefghijklmnop"},
        requested_by="security_gate")
    secret_finding = secret_report["findings"][0]
    cp.review_security_finding(
        report_id=secret_report["id"], fingerprint=secret_finding["fingerprint"],
        actor="quench", verdict="confirmed", note="secret shape confirmed")
    with pytest.raises(PermissionError, match="S3"):
        cp.record_security_exception(
            report_id=secret_report["id"], fingerprint=secret_finding["fingerprint"],
            actor="fry", reason="must not bypass", duration_minutes=1)
    restored = ControlPlane(EvidenceStore(path))
    assert restored.security_adjudications
    assert restored.security_exceptions == [exception]
    assert restored.evidence.verify()
