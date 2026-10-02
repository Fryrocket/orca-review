from hashlib import sha256
import json
from pathlib import Path
from threading import Thread
from urllib.request import Request, urlopen
import zipfile

from orca.control_plane import ControlPlane
from orca.environment_package import (
    attach_environment_quench_review,
    create_pi5_environment_hat_package,
    environment_quench_prompt,
)
from orca.web import OrcaHTTPServer


PROMPT = (
    "Create a complete A-to-Z Raspberry Pi 5 environmental status HAT with "
    "temperature and humidity sensing, RGB status and an open-drain alarm."
)


def test_environment_hat_is_real_routed_and_checksum_verified(tmp_path):
    result = create_pi5_environment_hat_package(PROMPT, tmp_path)
    package = tmp_path / result["package_id"]
    archive = package / result["archive_filename"]
    assert archive.is_file()
    assert sha256(archive.read_bytes()).hexdigest() == result["zip_sha256"]
    assert result["project"]["project_id"].startswith("orca_pi5_environment_hat_")
    gate = result["review"]["checks"]["functional_electronics_gate"]
    assert all(gate.values())
    assert result["review"]["checks"]["physical_validation_claimed"] is False
    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
        assert {
            "pi5-environment-hat.kicad_sch", "pi5-environment-hat.kicad_pcb",
            "pcb-drc.rpt", "schematic-erc.rpt", "BOM.csv", "PROJECT.json",
            "REVIEW.json", "MANIFEST.json", "USER-MANUAL.md",
            "fabrication-pi5-environment-hat-F_Cu.gtl",
            "fabrication-pi5-environment-hat-In1_Cu.g1",
            "fabrication-pi5-environment-hat-In2_Cu.g2",
            "fabrication-pi5-environment-hat-B_Cu.gbl",
            "fabrication-pi5-environment-hat-PTH.drl",
            "fabrication-pi5-environment-hat-NPTH.drl",
        } <= names
        assert bundle.testzip() is None


def test_environment_hat_quench_review_is_embedded(tmp_path):
    initial = create_pi5_environment_hat_package(PROMPT, tmp_path)
    prompt = environment_quench_prompt(tmp_path, initial["package_id"])
    assert len(prompt) < 8_000
    reviewed = attach_environment_quench_review(tmp_path, initial["package_id"], {
        "summary": "The software design is reviewable; physical evidence remains absent.",
        "evidence": ["KiCad DRC is clean.", "The HAT EEPROM is present.", "Physical results are not claimed."],
        "uncertainty": "Fit, calibration and bench behavior remain unproven.",
        "next_gate": "blocked",
    })
    assert reviewed["project"]["independently_reviewed"] is True
    assert reviewed["review"]["independent_reviewer"] == "QUENCH"
    with zipfile.ZipFile(tmp_path / initial["package_id"] / initial["archive_filename"]) as bundle:
        assert "QUENCH-REVIEW.json" in bundle.namelist()


def test_environment_request_uses_product_endpoint_and_real_download(tmp_path):
    token = "e" * 32
    control = ControlPlane()
    server = OrcaHTTPServer(("127.0.0.1", 0), control, operator_token=token)
    control.evidence.path = str(tmp_path / "orca-events.db")
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/product-development/package",
            data=json.dumps({"prompt": PROMPT}).encode(), method="POST",
            headers={"Content-Type": "application/json", "X-ORCA-Operator-Token": token})
        with urlopen(request) as response:
            created = json.load(response)
        assert created["project"]["project_id"].startswith("orca_pi5_environment_hat_")
        request = Request(
            f"http://127.0.0.1:{server.server_port}{created['download_url']}",
            headers={"X-ORCA-Operator-Token": token})
        with urlopen(request) as response:
            payload = response.read()
        assert sha256(payload).hexdigest() == created["zip_sha256"]
    finally:
        server.shutdown()
        server.server_close()


def test_studio_routes_supported_environment_hat_to_product_builder():
    source = Path("orca/static/app.js").read_text()
    assert "environment|environmental|humidity|temperature|sht31" in source
    assert "result.archive_filename" in source
    assert "result.manual_content" in source
