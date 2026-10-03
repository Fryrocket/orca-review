import json
from pathlib import Path

from orca.engineering_console import MAX_ITERATIONS, _verify_package, run_acceptance
from orca.product_package import create_pi5_cooling_hat_package, prepare_fabrication_readiness


PROMPT = "Build and verify a Raspberry Pi 5 active-cooling HAT through fabrication readiness."


def accepted_package(tmp_path):
    result = create_pi5_cooling_hat_package(PROMPT, tmp_path)
    return prepare_fabrication_readiness(tmp_path, result["project"]["project_id"])


def test_real_regression_reaches_honest_physical_gate(tmp_path):
    run = run_acceptance(PROMPT, tmp_path)
    assert run["state"] == "blocked"
    assert run["iteration"] == 1
    assert run["project_id"].startswith("orca_pi5_cooling_hat_")
    assert {item["kind"] for item in run["artifacts"]} == {"package", "manifest"}
    assert run["checks"]["functional_electronics_gate"]["firmware_tests_passed"] is True
    assert run["regression_baseline"]["file_count"] == 48
    assert run["regression_baseline"]["sha256"] == "9d88d0a43403677d3ca4c88dedaceb441cafd8c117e5d31c809caff522987db6"
    assert run["chat_authority"] is False
    assert "core_code" in run["capability_matrix"]["enabled"]
    assert "deployment" in run["capability_matrix"]["enabled"]
    assert "registered_connectors" in run["capability_matrix"]["enabled"]
    assert "credentials" in run["capability_matrix"]["approval_gated"]
    assert "permission_widening" in run["capability_matrix"]["prohibited"]
    assert run["ordinary_orca_agents_have_authority"] is False


def test_missing_paperwork_and_firmware_execution_prevent_success(tmp_path):
    result = accepted_package(tmp_path)
    package = tmp_path / result["package_id"]
    (package / "owner-execution-checklist.md").unlink()
    (package / "firmware-test-results.txt").write_text("not executed\n", encoding="utf-8")
    failures = _verify_package(result, tmp_path)
    assert any("required artifacts missing" in item for item in failures)
    assert any("firmware was not actually executed" in item for item in failures)


def test_fake_download_hash_and_empty_kicad_prevent_success(tmp_path):
    result = accepted_package(tmp_path)
    package = tmp_path / result["package_id"]
    result["zip_sha256"] = "0" * 64
    (package / "pi5-cooling-hat.kicad_pcb").write_text("(kicad_pcb)\n", encoding="utf-8")
    failures = _verify_package(result, tmp_path)
    assert any("checksum" in item for item in failures)
    assert any("KiCad PCB is empty" in item for item in failures)


def test_retry_is_bounded_and_never_reports_false_success(tmp_path, monkeypatch):
    from orca import engineering_console

    calls = []
    fake = {"project": {"project_id": "orca_pi5_cooling_hat_0123456789abcdef"}}
    monkeypatch.setattr(engineering_console, "prepare_fabrication_readiness", lambda root, project: fake)
    monkeypatch.setattr(engineering_console, "_verify_package", lambda result, root: ["confirmed failure"])
    run = run_acceptance(PROMPT, tmp_path, builder=lambda prompt, root: calls.append(prompt) or fake)
    assert len(calls) == MAX_ITERATIONS
    assert run["state"] == "failed"
    assert run["iteration"] == MAX_ITERATIONS
    assert run["blockers"] == ["confirmed failure"]
    stored = json.loads((tmp_path / "engineering-runs" / f"{run['run_id']}.json").read_text())
    assert stored["state"] == "failed"


def test_administrator_is_left_of_chatgpt_and_has_no_shell_controls():
    html = Path("orca/static/index.html").read_text(encoding="utf-8")
    script = Path("orca/static/app.js").read_text(encoding="utf-8")
    administrator = html.index('class="engineering-console"')
    orca = html.index('class="conversation-panel"')
    chatgpt = html.index('class="chatgpt-console"')
    assert administrator < orca < chatgpt
    assert 'aria-label="Administrator"' in html
    assert 'aria-label="ORCA"' in html
    assert 'aria-label="Master Developer"' in html
    assert "<h2>Administrator</h2>" in html
    assert "<h2>Master Developer</h2>" in html
    assert 'class="studio-grid" data-pane="orca"' in html
    assert 'data-studio-pane="administrator"' in html
    assert 'data-studio-pane="orca"' in html
    assert 'data-studio-pane="master"' in html
    assert "Enter to send · Shift+Enter for a new line" in html
    core_developer = html[administrator:orca]
    assert 'type="submit"' not in core_developer
    assert "CHATGPT · ORCA/FORGE TOOLS" in html
    assert "/api/administrator-screen/runs" in script
    assert "shell" not in html[administrator:chatgpt]
