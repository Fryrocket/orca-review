from __future__ import annotations

from csv import writer
from datetime import datetime, timezone
from hashlib import sha256
import io
import json
from pathlib import Path
import re
import zipfile

from .review_panel import build_review_packet, review_panel_plan
from .security import redact_text


MAX_PROMPT = 12_000
_TEMPLATE = Path(__file__).resolve().parent / "templates" / "pi5_environment_hat"
_REQUIRED_NETS = {
    "GND", "3V3", "I2C_SDA", "I2C_SCL", "GPIO18_RED", "LED_RED",
    "GPIO23_GREEN", "LED_GREEN", "GPIO24_BLUE", "LED_BLUE",
    "GPIO22_ALARM", "ALARM_GATE", "ALARM_OD", "ID_SD", "ID_SC",
    "EEPROM_WP",
}
_ARCHIVE = "ORCA-Pi5-Environmental-Status-HAT.zip"


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _csv(rows: list[list[object]]) -> str:
    stream = io.StringIO(newline="")
    output = writer(stream)
    output.writerows(rows)
    return stream.getvalue()


def _assets() -> tuple[dict[str, str], dict[str, bool]]:
    paths = {
        "pi5-environment-hat.kicad_sch": _TEMPLATE / "pi5-environment-hat.kicad_sch",
        "pi5-environment-hat.kicad_pcb": _TEMPLATE / "pi5-environment-hat.kicad_pcb",
        "schematic-erc.rpt": _TEMPLATE / "schematic-erc.rpt",
        "pcb-drc.rpt": _TEMPLATE / "pcb-drc.rpt",
        "design-source-generate-schematic.py": _TEMPLATE / "generate_schematic.py",
        "design-source-generate-board.py": _TEMPLATE / "generate_board.py",
    }
    fabrication = {
        "fabrication-" + path.name: path
        for path in (_TEMPLATE / "fabrication").iterdir()
        if path.is_file()
    }
    paths.update(fabrication)
    if any(not path.is_file() for path in paths.values()):
        raise RuntimeError("environment HAT design assets are incomplete")
    assets = {name: path.read_text(encoding="utf-8") for name, path in paths.items()}
    board = assets["pi5-environment-hat.kicad_pcb"]
    schematic = assets["pi5-environment-hat.kicad_sch"]
    nets = set(re.findall(r'\(net\s+\d+\s+"([^"]+)"\)', board))
    checks = {
        "required_nets_present": _REQUIRED_NETS <= nets,
        "schematic_has_symbols": schematic.count("(symbol ") >= 18,
        "schematic_has_connectivity_labels": schematic.count("(global_label ") >= 14,
        "pcb_has_required_footprints": board.count("(footprint ") >= 20,
        "hat_id_eeprom_present": all(marker in board for marker in ('"U2"', '"CAT24C32"', '"ID_SD"', '"ID_SC"', '"EEPROM_WP"')),
        "sensor_present": all(marker in board for marker in ('"U1"', '"SHT31-DIS-B2.5kS"', '"I2C_SDA"', '"I2C_SCL"')),
        "pcb_is_routed": board.count("(segment") >= 55,
        "pcb_unconnected_items": "Found 0 unconnected pads" in assets["pcb-drc.rpt"],
        "pcb_drc_errors": "Found 0 DRC violations" in assets["pcb-drc.rpt"] and "; error" not in assets["pcb-drc.rpt"],
        "schematic_erc_errors": "Errors 0" in assets["schematic-erc.rpt"],
        "gerbers_present": all(
            any(name.endswith(suffix) for name in fabrication)
            for suffix in ("F_Cu.gtl", "In1_Cu.g1", "In2_Cu.g2", "B_Cu.gbl",
                           "F_Mask.gts", "B_Mask.gbs", "Edge_Cuts.gm1",
                           "PTH.drl", "NPTH.drl", ".gbrjob", "placement.csv")
        ),
    }
    if not all(checks.values()):
        failed = ", ".join(name for name, passed in checks.items() if not passed)
        raise RuntimeError(f"environment HAT functional gate failed: {failed}")
    return assets, checks


def _manual() -> str:
    return """# ORCA Pi 5 Environmental Status HAT User Manual

## Purpose

This engineering prototype measures temperature and relative humidity with an SHT31-DIS sensor, displays status through a common-cathode RGB LED, and exposes a low-current open-drain alarm output. It is designed for Raspberry Pi 5 and includes the required HAT+ identity EEPROM circuit.

## Safety and limits

Use only 3.3 V logic. The alarm output is a low-current open drain and must not directly drive a relay, motor, mains circuit, or load beyond the verified 2N7000 limits. Power down before installing or removing the HAT. This package is not a certification and has not been physically measured.

## Installation

Inspect the PCB for shorts and correct orientation. Fit four suitable standoffs. With Raspberry Pi power removed, align the 40-pin connector and press evenly. Confirm the board does not interfere with cooling hardware, camera/display cables, or the Pi fan connector. Perform current-limited first power before normal use.

## Interfaces

The SHT31 uses I2C address 0x44 on GPIO2/SDA and GPIO3/SCL. GPIO18 drives red, GPIO23 drives green, and GPIO24 drives blue through 330-ohm resistors. GPIO22 drives a 2N7000 open-drain alarm through a 100-ohm gate resistor with a 100-kilohm pulldown. The two-pin alarm header exposes ALARM_OD and GND.

## Software

Install `python3-smbus2` and a GPIO library appropriate for Raspberry Pi OS. Run `environment_status.py` as an unprivileged service with access only to I2C and the declared GPIO lines. The example defaults to green for normal conditions, blue for high humidity, red for high temperature or sensor failure, and asserts the alarm only for declared alert states.

## Verification

Before relying on the HAT, verify the received sensor and EEPROM markings, connector orientation, board fit, 3.3 V rail, I2C discovery at 0x44, LED colors, alarm drain voltage/current, sensor accuracy against a traceable reference, recovery after a controlled power cycle, and operation across the intended environment. Record raw readings and hashes. A missing physical result remains pending, never passed.

## Maintenance

Keep the sensor opening clean and exposed to representative air. Avoid condensation, solvents, flux residue, and direct heat sources. Recheck calibration on a defined interval. Preserve the project ID, PCB revision, firmware revision, and evidence manifest with every unit.
"""


def _firmware() -> str:
    return '''#!/usr/bin/env python3
"""Reference controller for the ORCA Pi 5 Environmental Status HAT."""
import time
from smbus2 import SMBus

ADDRESS = 0x44

def read_environment(bus):
    bus.write_i2c_block_data(ADDRESS, 0x24, [0x00])
    time.sleep(0.02)
    raw = bus.read_i2c_block_data(ADDRESS, 0x00, 6)
    temperature_c = -45 + 175 * ((raw[0] << 8) | raw[1]) / 65535
    humidity_percent = 100 * ((raw[3] << 8) | raw[4]) / 65535
    return temperature_c, humidity_percent

with SMBus(1) as bus:
    while True:
        temperature, humidity = read_environment(bus)
        print(f"temperature_c={temperature:.2f} humidity_percent={humidity:.2f}")
        time.sleep(2)
'''


def create_pi5_environment_hat_package(prompt: str, root: str | Path) -> dict:
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT:
        raise ValueError("product package request must contain 1-12,000 characters")
    if redact_text(prompt) != prompt:
        raise ValueError("product package request contains secret-shaped data")
    normalized = " ".join(prompt.casefold().split())
    if not ("pi" in normalized and ("hat" in normalized or "board" in normalized)
            and ("environment" in normalized or "humidity" in normalized or "sht31" in normalized)):
        raise ValueError("this workflow requires the Pi 5 environmental status HAT request")
    package_id = sha256(normalized.encode()).hexdigest()
    package_root = Path(root).resolve() / package_id
    package_root.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    project_id = f"orca_pi5_environment_hat_{package_id[:16]}"
    assets, checks = _assets()
    files: dict[str, str] = {
        "README.md": "# ORCA Pi 5 Environmental Status HAT\n\nA connected, routed, fabrication-ready software design. Physical fit, electrical bench tests, calibration and environmental testing remain blocked pending real hardware.\n",
        "pi5-environment-hat.kicad_pro": json.dumps({"board": {}, "erc": {}, "meta": {"filename": "pi5-environment-hat.kicad_pro", "version": 1}, "net_settings": {}, "pcbnew": {}, "schematic": {}, "text_variables": {}}, indent=2),
        "requirements.csv": _csv([
            ["ID", "Requirement", "Verification", "State"],
            ["REQ-001", "Measure temperature and humidity through SHT31 at I2C address 0x44", "I2C bench and reference comparison", "design complete; physical pending"],
            ["REQ-002", "Drive common-cathode RGB status LED from GPIO18/23/24", "color and current measurement", "design complete; physical pending"],
            ["REQ-003", "Expose low-current open-drain alarm controlled by GPIO22", "voltage/current/fault bench test", "design complete; physical pending"],
            ["REQ-004", "Meet HAT+ identity EEPROM requirements", "EEPROM program/read/WP test", "design complete; physical pending"],
            ["REQ-005", "Fit Raspberry Pi 5 HAT outline and mounting pattern", "mechanical overlay and physical fit", "software geometry complete; physical pending"],
        ]),
        "BOM.csv": _csv([
            ["Ref", "Qty", "Description", "Manufacturer part", "Alternate rule"],
            ["U1", 1, "Digital temperature/humidity sensor", "Sensirion SHT31-DIS-B2.5kS", "same package, voltage, accuracy and I2C behavior"],
            ["U2", 1, "32-kbit HAT+ ID EEPROM", "onsemi CAT24C32", "3.3 V, 16-bit address, full WP, no clock stretching"],
            ["Q1", 1, "N-channel MOSFET", "onsemi 2N7000", "pin-compatible verified substitute"],
            ["D1", 1, "5 mm common-cathode RGB LED", "Kingbright L-154A4SURKQBDZGW", "common-cathode, matched pin order"],
            ["J1", 1, "2x20 Pi stacking header", "Samtec ESQ-120-23-G-D", "verified Pi HAT stacking header"],
            ["J2", 1, "2-pin alarm header", "Molex 0022284020", "2.54 mm compatible"],
            ["R1,R2", 2, "10k optional I2C pull-up", "Yageo MFR-25FBF52-10K", "DNP unless bus needs local pull-ups"],
            ["R3,R4,R5", 3, "330 ohm LED resistor", "Yageo MFR-25FBF52-330R", "1 percent equivalent"],
            ["R6", 1, "100 ohm gate resistor", "Yageo MFR-25FBF52-100R", "1 percent equivalent"],
            ["R7", 1, "100k gate pulldown", "Yageo MFR-25FBF52-100K", "1 percent equivalent"],
            ["R8,R9", 2, "3.9k ID bus pull-up", "Yageo MFR-25FBF52-3K9", "HAT+ compatible"],
            ["R10", 1, "1k EEPROM WP pull-up", "Yageo MFR-25FBF52-1K", "HAT+ compatible"],
            ["C1,C2", 2, "100nF decoupling", "KEMET C315C104M5U5TA", "rated 6.3 V or higher"],
            ["C3", 1, "10uF bulk capacitor", "Nichicon UFW1A100MDD", "rated 6.3 V or higher"],
        ]),
        "cost-estimate.csv": _csv([
            ["Item", "Planning USD", "Basis"], ["Prototype PCB", "12.00", "quote required"],
            ["Sensor and EEPROM", "10.00", "planning allowance"], ["Headers, LED, passives and MOSFET", "9.00", "planning allowance"],
            ["TOTAL", "31.00", "before shipping, tax and assembly"],
        ]),
        "power-and-interface-calculations.md": "# Calculations\n\nAt 3.3 V with a nominal 2.0 V LED drop and 330 ohms, one channel is approximately 3.9 mA. Three simultaneous channels are approximately 11.8 mA. The SHT31 typical measurement current is small compared with that load; confirm against the selected measurement cadence. The optional 10-kilohm I2C pull-ups each draw at most 0.33 mA low. The 100-kilohm gate pulldown draws 33 microamps when GPIO22 is high through the 100-ohm gate resistor. The open-drain alarm has no onboard pull-up; its external voltage and sink current must stay inside verified 2N7000 and 3.3-V-system limits.\n",
        "pin-map.csv": _csv([
            ["Function", "Pi physical pin", "GPIO/net"], ["3V3", "1 and 17", "3V3"],
            ["SDA", "3", "GPIO2/I2C_SDA"], ["SCL", "5", "GPIO3/I2C_SCL"],
            ["Ground", "6", "GND"], ["Red", "12", "GPIO18"], ["Alarm", "15", "GPIO22"],
            ["Green", "16", "GPIO23"], ["Blue", "18", "GPIO24"],
            ["HAT ID data", "27", "ID_SD"], ["HAT ID clock", "28", "ID_SC"],
        ]),
        "environment_status.py": _firmware(),
        "verification-plan.md": "# Verification plan\n\nRun KiCad ERC/DRC; inspect Gerbers; verify exact received parts and pin order; test current-limited first power; discover 0x44; compare temperature/humidity against a traceable reference at multiple points; verify each LED channel; measure alarm leakage and sink behavior; program/read/protect the EEPROM; verify mechanical fit; run controlled restart and outage recovery; perform intended-range environmental testing. Preserve raw evidence and hashes.\n",
        "manufacturing-readiness.md": "# Manufacturing readiness\n\nSoftware design gate: PASSED. KiCad reports zero DRC violations, zero unconnected pads and zero footprint errors; schematic ERC reports zero errors; four copper Gerbers, masks, silkscreens, board outline, separated PTH/NPTH drills and placement data exist. Manufacturing release remains BLOCKED pending received-part verification, physical fit, bench electrical testing, sensor calibration, environmental testing and owner evidence.\n",
        "risk-and-compliance.md": "# Risk and compliance\n\nPrincipal risks are connector reversal, incompatible LED polarity, alarm overvoltage/overcurrent, condensation, sensor contamination, bad calibration and unsupported product claims. No regulatory, calibration, accuracy, safety or market-access claim is made. Final obligations depend on enclosure, power source, market and intended use.\n",
        "assembly-guide.md": "# Assembly guide\n\nVerify the fabrication outputs and exact received parts. Assemble the lowest-profile parts first, then the DFN sensor using controlled reflow, followed by EEPROM, passives, MOSFET, LED and headers. Inspect polarity and solder joints under magnification. Clean without contaminating the SHT31 opening. Perform continuity and resistance checks before current-limited first power.\n",
        "USER-MANUAL.md": _manual(),
    }
    files.update(assets)
    packet = build_review_packet(
        project_id=project_id,
        candidate_files={name: files[name] for name in (
            "pi5-environment-hat.kicad_sch", "pi5-environment-hat.kicad_pcb",
            "schematic-erc.rpt", "pcb-drc.rpt", "BOM.csv", "requirements.csv",
            "power-and-interface-calculations.md", "verification-plan.md",
            "design-source-generate-schematic.py", "design-source-generate-board.py")},
        claims=(
            "The schematic, PCB, BOM and generator sources describe the same circuit.",
            "Every used pad is connected and the board has zero DRC violations.",
            "The HAT+ EEPROM and sensor interfaces match cited primary specifications.",
            "No physical test, calibration or certification is claimed.",
        ),
        public_sources=(
            "https://datasheets.raspberrypi.com/hat/hat-plus-specification.pdf",
            "https://sensirion.com/media/documents/213E6A3B/63A5A569/Datasheet_SHT3x_DIS.pdf",
        ),
    )
    files["INDEPENDENT-REVIEW-PACKET.json"] = json.dumps(packet, indent=2, sort_keys=True)
    files["INDEPENDENT-REVIEW-PLAN.json"] = json.dumps(review_panel_plan(), indent=2, sort_keys=True)
    project = {
        "schema": 1, "project_id": project_id, "name": "ORCA Raspberry Pi 5 Environmental Status HAT",
        "kind": "hardware_product_development", "source": "ORCA Studio",
        "lifecycle_state": "engineering_prototype", "status": "functional_design_complete_physical_validation_blocked",
        "created_at": now, "updated_at": now, "package_id": package_id,
        "independently_reviewed": False, "manufacturing_release": "blocked_pending_physical_evidence",
    }
    review = {
        "reviewer": "ORCA deterministic evidence gate", "independent_authoring": False,
        "result": project["status"],
        "checks": {"functional_electronics_gate": checks, "all_files_nonempty": True,
                   "physical_validation_claimed": False, "purchases_or_external_actions": 0},
        "blocking_evidence": ["independent QUENCH review", "received-part verification", "mechanical fit", "bench electrical testing", "sensor calibration", "environmental test"],
    }
    files["PROJECT.json"] = json.dumps(project, indent=2)
    files["REVIEW.json"] = json.dumps(review, indent=2)
    for name, content in files.items():
        (package_root / name).write_text(content, encoding="utf-8")
    records = [{"name": name, "bytes": (package_root / name).stat().st_size,
                "sha256": _digest(package_root / name)} for name in sorted(files)]
    manifest = {"schema": 1, "package_id": package_id, "created_at": now,
                "status": project["status"], "artifacts": records}
    (package_root / "MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    zip_path = package_root / _ARCHIVE
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(package_root.iterdir()):
            if path.is_file() and path != zip_path:
                archive.write(path, path.name)
    return _result(package_root, package_id, project, review)


def environment_quench_prompt(root: str | Path, package_id: str) -> str:
    package = Path(root).resolve() / package_id
    manifest = json.loads((package / "MANIFEST.json").read_text(encoding="utf-8"))
    evidence = {
        "project": json.loads((package / "PROJECT.json").read_text(encoding="utf-8")),
        "artifacts": [{"name": x["name"], "bytes": x["bytes"], "sha256_prefix": x["sha256"][:16]} for x in manifest["artifacts"][:45]],
        "requirements": (package / "requirements.csv").read_text(encoding="utf-8")[:1800],
        "calculations": (package / "power-and-interface-calculations.md").read_text(encoding="utf-8")[:1500],
        "drc": (package / "pcb-drc.rpt").read_text(encoding="utf-8")[:900],
        "erc": (package / "schematic-erc.rpt").read_text(encoding="utf-8")[:900],
        "manufacturing_gate": (package / "manufacturing-readiness.md").read_text(encoding="utf-8")[:1200],
    }
    return ("Independently review this checksum-bound Raspberry Pi 5 environmental HAT package. Check schematic/PCB/BOM consistency, SHT31 and HAT+ requirements, GPIO safety, alarm limits, evidence truthfulness and missing physical proof. Never claim fabrication, calibration, certification or physical testing. Be concise: summary <=400 characters; exactly three evidence strings <=240 characters; uncertainty <=240 characters; next_gate must be blocked. Return only the required QUENCH JSON contract.\n\n" + json.dumps(evidence, sort_keys=True, separators=(",", ":")))[:7900]


def attach_environment_quench_review(root: str | Path, package_id: str, output: dict) -> dict:
    if not isinstance(output, dict) or not isinstance(output.get("summary"), str):
        raise ValueError("QUENCH review output is invalid")
    package = Path(root).resolve() / package_id
    (package / "QUENCH-REVIEW.json").write_text(json.dumps(output, indent=2, sort_keys=True), encoding="utf-8")
    review = json.loads((package / "REVIEW.json").read_text(encoding="utf-8"))
    review.update({"independent_authoring": True, "independent_reviewer": "QUENCH", "quench_next_gate": output.get("next_gate")})
    review["result"] = "functional_design_independently_reviewed_physical_validation_blocked"
    review["blocking_evidence"] = [x for x in review["blocking_evidence"] if x != "independent QUENCH review"]
    (package / "REVIEW.json").write_text(json.dumps(review, indent=2), encoding="utf-8")
    project = json.loads((package / "PROJECT.json").read_text(encoding="utf-8"))
    project.update({"updated_at": datetime.now(timezone.utc).isoformat(), "status": review["result"], "independently_reviewed": True})
    (package / "PROJECT.json").write_text(json.dumps(project, indent=2), encoding="utf-8")
    excluded = {"MANIFEST.json", _ARCHIVE}
    records = [{"name": p.name, "bytes": p.stat().st_size, "sha256": _digest(p)}
               for p in sorted(package.iterdir()) if p.is_file() and p.name not in excluded]
    manifest = {"schema": 1, "package_id": package_id, "created_at": datetime.now(timezone.utc).isoformat(), "status": review["result"], "artifacts": records}
    (package / "MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    zip_path = package / _ARCHIVE
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(package.iterdir()):
            if path.is_file() and path != zip_path:
                archive.write(path, path.name)
    return _result(package, package_id, project, review)


def _result(package: Path, package_id: str, project: dict, review: dict) -> dict:
    zip_path = package / _ARCHIVE
    manifest = json.loads((package / "MANIFEST.json").read_text(encoding="utf-8"))
    return {
        "package_id": package_id, "status": review["result"],
        "artifact_count": len(manifest["artifacts"]) + 1,
        "zip_sha256": _digest(zip_path), "zip_bytes": zip_path.stat().st_size,
        "download_url": f"/api/product-development/packages/{package_id}/{_ARCHIVE}",
        "archive_filename": _ARCHIVE,
        "manifest_url": f"/api/product-development/packages/{package_id}/MANIFEST.json",
        "project": project, "review": review, "manual_title": "ORCA Pi 5 Environmental Status HAT User Manual",
        "manual_content": _manual(),
    }
