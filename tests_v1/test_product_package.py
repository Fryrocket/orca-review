from hashlib import sha256
import json
from pathlib import Path
from threading import Thread
from urllib.request import Request, urlopen
import zipfile

from orca.control_plane import ControlPlane
from orca.product_package import (
    attach_quench_review,
    create_pi5_cooling_hat_package,
    list_product_projects,
    prepare_fabrication_readiness,
    quench_review_prompt,
)
from orca.web import OrcaHTTPServer


PROMPT = "Create a complete end-to-end Raspberry Pi 5 HAT with a fan for cooling."


def test_pi5_package_creates_real_checksum_verified_artifacts(tmp_path):
    result = create_pi5_cooling_hat_package(PROMPT, tmp_path)
    package = tmp_path / result["package_id"]
    archive = package / "ORCA-Pi5-Cooling-HAT.zip"
    assert archive.is_file()
    assert sha256(archive.read_bytes()).hexdigest() == result["zip_sha256"]
    assert result["review"]["checks"]["physical_validation_claimed"] is False
    assert result["status"] == "prototype_package_complete_manufacturing_release_blocked"
    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
        assert {"pi5-cooling-hat.kicad_sch", "pi5-cooling-hat.kicad_pcb",
                "BOM.csv", "fan_control.py", "MANIFEST.json", "PROJECT.json",
                "REVIEW.json"} <= names
        assert bundle.testzip() is None
        manifest = json.loads(bundle.read("MANIFEST.json"))
        assert manifest["package_id"] == result["package_id"]
    assert result["project"]["project_id"].startswith("orca_pi5_cooling_hat_")
    assert list_product_projects(tmp_path) == [result["project"]]


def test_quench_review_is_embedded_and_rehashes_the_package(tmp_path):
    initial = create_pi5_cooling_hat_package(PROMPT, tmp_path)
    prompt = quench_review_prompt(tmp_path, initial["package_id"])
    assert len(prompt) < 8_000
    assert "checksum-bound evidence" in prompt
    assert '"thermal_calculations"' in prompt
    assert '"test_fixture_plan"' in prompt
    assert "distinguish an existing test plan" in prompt
    reviewed = attach_quench_review(tmp_path, initial["package_id"], {
        "summary": "Prototype package is internally consistent but correctly blocked.",
        "evidence": ["Physical test evidence is absent."],
        "uncertainty": "Mechanical and thermal performance remain unproven.",
        "next_gate": "blocked",
    })
    assert reviewed["review"]["independent_authoring"] is True
    assert reviewed["review"]["independent_reviewer"] == "QUENCH"
    assert "independent QUENCH review" not in reviewed["review"]["blocking_evidence"]
    assert reviewed["project"]["independently_reviewed"] is True
    assert reviewed["zip_sha256"] != initial["zip_sha256"]
    with zipfile.ZipFile(tmp_path / initial["package_id"] / "ORCA-Pi5-Cooling-HAT.zip") as bundle:
        assert "QUENCH-REVIEW.json" in bundle.namelist()
        assert json.loads(bundle.read("REVIEW.json"))["independent_authoring"] is True


def test_fabrication_readiness_extends_existing_project_without_fake_results(tmp_path):
    initial = create_pi5_cooling_hat_package(PROMPT, tmp_path)
    result = prepare_fabrication_readiness(
        tmp_path, initial["project"]["project_id"])
    package = tmp_path / initial["package_id"]
    assert result["status"] == "fabrication_readiness_prepared_physical_validation_blocked"
    assert result["review"]["fabrication_readiness"]["physical_measurements_claimed"] is False
    with zipfile.ZipFile(package / "ORCA-Pi5-Cooling-HAT.zip") as bundle:
        names = set(bundle.namelist())
        assert {"fabrication-readiness.md", "mechanical-fit-inspection.md",
                "bench-electrical-test.md", "thermal-soak-procedure.md",
                "instrumentation-list.csv", "acceptance-matrix.csv",
                "evidence-rules.md", "owner-execution-checklist.md"} <= names
        assert bundle.testzip() is None
        matrix = bundle.read("acceptance-matrix.csv").decode()
        assert "PENDING" in matrix
        assert "PASSED" not in matrix
    manifest = json.loads((package / "MANIFEST.json").read_text())
    assert all((package / item["name"]).is_file() for item in manifest["artifacts"])
    assert all(sha256((package / item["name"]).read_bytes()).hexdigest() == item["sha256"]
               for item in manifest["artifacts"])


def test_product_package_http_create_and_authenticated_download(tmp_path):
    token = "p" * 32
    control = ControlPlane()
    server = OrcaHTTPServer(("127.0.0.1", 0), control, operator_token=token)
    control.evidence.path = str(tmp_path / "orca-events.db")
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        body = json.dumps({"prompt": PROMPT}).encode()
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/product-development/package",
            data=body, method="POST", headers={"Content-Type": "application/json",
            "X-ORCA-Operator-Token": token})
        with urlopen(request) as response:
            created = json.load(response)
        request = Request(
            f"http://127.0.0.1:{server.server_port}{created['download_url']}",
            headers={"X-ORCA-Operator-Token": token})
        with urlopen(request) as response:
            payload = response.read()
            assert response.headers["Content-Type"] == "application/zip"
        assert sha256(payload).hexdigest() == created["zip_sha256"]
    finally:
        server.shutdown()
        server.server_close()


def test_http_single_prompt_chains_fabrication_readiness(tmp_path):
    token = "r" * 32
    control = ControlPlane()
    server = OrcaHTTPServer(("127.0.0.1", 0), control, operator_token=token)
    control.evidence.path = str(tmp_path / "orca-events.db")
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        prompt = PROMPT + " Complete the fabrication-readiness phase in the same request."
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/product-development/package",
            data=json.dumps({"prompt": prompt}).encode(), method="POST",
            headers={"Content-Type": "application/json", "X-ORCA-Operator-Token": token})
        with urlopen(request) as response:
            created = json.load(response)
        assert created["status"] == "fabrication_readiness_prepared_physical_validation_blocked"
        # The unit server has no QUENCH runtime, so the independent review file
        # is the one live artifact intentionally absent here.
        assert created["artifact_count"] == 27
        request = Request(
            f"http://127.0.0.1:{server.server_port}{created['download_url']}",
            headers={"X-ORCA-Operator-Token": token})
        with urlopen(request) as response:
            payload = response.read()
        archive = tmp_path / "single-request.zip"
        archive.write_bytes(payload)
        with zipfile.ZipFile(archive) as bundle:
            assert "fabrication-readiness.md" in bundle.namelist()
            assert "owner-execution-checklist.md" in bundle.namelist()
            assert bundle.testzip() is None
    finally:
        server.shutdown()
        server.server_close()


def test_chat_routes_complete_pi5_hat_requests_to_real_package():
    source = Path("orca/static/app.js").read_text()
    assert "function wantsEndToEndProductPackage" in source
    assert "'/api/product-development/package'" in source
    assert "Download complete design package" in source
    assert "manufacturing release remains blocked" in source
    assert "tracked project" in source
    assert "function fabricationReadinessProject" in source
    assert "'/api/product-development/fabrication-readiness'" in source
    assert "Download updated readiness package" in source
    assert "use_tool_broker=False" in Path("orca/web.py").read_text()
    runtime = Path("orca/runtime.py").read_text()
    assert 'else 2_048' in runtime
