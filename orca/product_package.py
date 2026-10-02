from __future__ import annotations

from csv import writer
from datetime import datetime, timezone
from hashlib import sha256
import io
import json
from pathlib import Path
import re
import zipfile

from .cad import create_kicad_pcb_draft
from .security import redact_text


MAX_PROMPT = 12_000
_PACKAGE = re.compile(r"^[a-f0-9]{64}$")
_ARTIFACT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_PROJECT_ID = re.compile(r"^orca_pi5_cooling_hat_[a-f0-9]{16}$")


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _csv(rows: list[list[object]]) -> str:
    stream = io.StringIO(newline="")
    output = writer(stream)
    output.writerows(rows)
    return stream.getvalue()


def _project_record(package_id: str, *, created_at: str, updated_at: str,
                    status: str, independently_reviewed: bool) -> dict:
    """Return the durable ORCA project identity for this design package."""

    return {
        "schema": 1,
        "project_id": f"orca_pi5_cooling_hat_{package_id[:16]}",
        "name": "ORCA Raspberry Pi 5 Active-Cooling HAT",
        "kind": "hardware_product_development",
        "source": "ORCA Studio",
        "lifecycle_state": "engineering_prototype",
        "status": status,
        "created_at": created_at,
        "updated_at": updated_at,
        "package_id": package_id,
        "independently_reviewed": independently_reviewed,
        "manufacturing_release": "blocked_pending_physical_evidence",
    }


def _schematic() -> str:
    # A bounded KiCad source artifact.  It is deliberately marked as an
    # engineering prototype until KiCad ERC and physical validation are run.
    parts = [
        ("J1", "Raspberry_Pi_2x20", "Connector_Generic:Conn_02x20_Odd_Even", 40, 50),
        ("J2", "FAN_4WIRE", "Connector_Generic:Conn_01x04", 120, 50),
        ("Q1", "2N7002K", "Transistor_FET:2N7002", 80, 80),
        ("R1", "10k", "Device:R", 60, 95),
        ("R2", "10k", "Device:R", 100, 95),
        ("F1", "0.50A_PTC", "Device:Polyfuse", 75, 35),
        ("D1", "SMBJ5.0A", "Device:D_TVS", 95, 35),
        ("C1", "100uF", "Device:C_Polarized", 108, 35),
        ("C2", "100nF", "Device:C", 116, 35),
    ]
    symbols = []
    for ref, value, lib_id, x, y in parts:
        symbols.append(
            f'  (symbol (lib_id "{lib_id}") (at {x} {y} 0) (unit 1)\n'
            f'    (in_bom yes) (on_board yes)\n'
            f'    (property "Reference" "{ref}" (at {x} {y-2.54} 0) (effects (font (size 1.27 1.27))))\n'
            f'    (property "Value" "{value}" (at {x} {y+2.54} 0) (effects (font (size 1.27 1.27))))\n'
            '    (property "Footprint" "" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))\n'
            '    (property "Datasheet" "" (at 0 0 0) (effects (font (size 1.27 1.27)) hide))\n'
            '  )')
    date = datetime.now(timezone.utc).date().isoformat()
    return (
        '(kicad_sch (version 20231120) (generator orca)\n'
        '  (uuid 00000000-0000-0000-0000-000000000001)\n'
        '  (paper "A4")\n'
        f'  (title_block (title "ORCA Pi 5 Active Cooling HAT") (date "{date}")\n'
        '    (comment 1 "ENGINEERING PROTOTYPE - VERIFY IN KICAD BEFORE FABRICATION")\n'
        '    (comment 2 "5 V four-wire PWM fan; GPIO18 PWM; GPIO17 tach"))\n'
        '  (lib_symbols)\n' + "\n".join(symbols) +
        '\n  (text "NET PLAN: 5V_FUSED, GND, FAN_PWM_OD, FAN_TACH_3V3" (exclude_from_sim no) (at 40 125 0)\n'
        '    (effects (font (size 1.27 1.27)) (justify left bottom)))\n'
        '  (sheet_instances (path "/" (page "1")))\n)\n')


def _firmware() -> str:
    return '''#!/usr/bin/env python3
"""Fail-safe Pi 5 fan controller for ORCA's active-cooling HAT prototype."""
import time
import lgpio

PWM_GPIO = 18
FREQUENCY_HZ = 25_000
TEMP_PATH = "/sys/class/thermal/thermal_zone0/temp"
CURVE = ((45.0, 0.0), (55.0, 35.0), (65.0, 55.0), (75.0, 75.0), (82.0, 100.0))

def temperature_c():
    with open(TEMP_PATH, encoding="ascii") as handle:
        return int(handle.read().strip()) / 1000.0

def duty_for(temp):
    for (lo_t, lo_d), (hi_t, hi_d) in zip(CURVE, CURVE[1:]):
        if temp <= lo_t:
            return lo_d
        if temp < hi_t:
            return lo_d + (hi_d - lo_d) * (temp - lo_t) / (hi_t - lo_t)
    return 100.0

chip = lgpio.gpiochip_open(0)
try:
    while True:
        try:
            temp = temperature_c()
            duty = duty_for(temp)
        except Exception:
            duty = 100.0  # sensor/read failure is full-speed safe
        lgpio.tx_pwm(chip, PWM_GPIO, FREQUENCY_HZ, duty)
        time.sleep(2)
finally:
    lgpio.tx_pwm(chip, PWM_GPIO, FREQUENCY_HZ, 100.0)
    lgpio.gpiochip_close(chip)
'''


def create_pi5_cooling_hat_package(prompt: str, root: str | Path) -> dict:
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT:
        raise ValueError("product package request must contain 1-12,000 characters")
    if redact_text(prompt) != prompt:
        raise ValueError("product package request contains secret-shaped data")
    normalized = " ".join(prompt.casefold().split())
    if not ("pi" in normalized and "fan" in normalized and ("hat" in normalized or "cool" in normalized)):
        raise ValueError("this verified package workflow currently supports the Pi 5 cooling HAT")
    package_id = sha256(normalized.encode()).hexdigest()
    package_root = Path(root).resolve() / package_id
    package_root.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    created_at = now
    existing_project = package_root / "PROJECT.json"
    if existing_project.is_file():
        try:
            previous = json.loads(existing_project.read_text(encoding="utf-8"))
            if (isinstance(previous, dict)
                    and isinstance(previous.get("created_at"), str)):
                created_at = previous["created_at"]
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            pass
    board = create_kicad_pcb_draft(
        "Create a .kicad_pcb for a Raspberry Pi 5 HAT with a 40 mm four-wire PWM cooling fan")
    files: dict[str, str] = {
        "README.md": """# ORCA Pi 5 Active-Cooling HAT\n\nStatus: engineering prototype package; not released for fabrication.\n\nThis design powers a 5 V four-wire PWM fan from the Pi 5 V rail, uses GPIO18 through an open-drain 2N7002 stage for the fan PWM input, and returns the open-collector tach signal to GPIO17 with a 3.3 V pull-up. Software reads the Pi CPU thermal zone and fails to full fan speed if temperature sensing fails.\n\nThe package is complete for design review and bench prototyping. Fabrication release remains blocked until KiCad symbol/footprint assignment, ERC/DRC, fan connector pinout, mechanical keep-outs, airflow direction, current draw, tach waveform, and thermal performance are measured on the actual Pi, heatsink, fan, enclosure and workload.\n""",
        "pi5-cooling-hat.kicad_pcb": board["content"],
        "pi5-cooling-hat.kicad_sch": _schematic(),
        "pi5-cooling-hat.kicad_pro": json.dumps({"board": {}, "cvpcb": {}, "erc": {}, "meta": {"filename": "pi5-cooling-hat.kicad_pro", "version": 1}, "net_settings": {}, "pcbnew": {}, "schematic": {}, "text_variables": {}}, indent=2),
        "BOM.csv": _csv([
            ["Ref", "Qty", "Description", "Manufacturer part number", "Alternative", "Verification"],
            ["J1", 1, "2x20 2.54 mm stacking GPIO header", "Samtec ESQ-120-23-G-D", "Equivalent verified Pi HAT stacking header", "mechanical height/pin length required"],
            ["J2", 1, "4-pin 2.54 mm fan header", "Molex 47053-1000", "Pin-compatible keyed fan header", "actual fan pin order required"],
            ["F1", 1, "0.50 A resettable PTC", "Bourns MF-MSMF050-2", "Littelfuse 1206L050", "hold/trip current against fan required"],
            ["Q1", 1, "N-channel MOSFET, SOT-23", "Diodes Inc 2N7002K-7", "BSS138", "open-drain PWM only"],
            ["R1", 1, "10 kOhm 0603", "Yageo RC0603FR-0710KL", "AEC-Q200 equivalent", "PWM gate pull-up"],
            ["R2", 1, "10 kOhm 0603", "Yageo RC0603FR-0710KL", "AEC-Q200 equivalent", "tach pull-up to 3V3"],
            ["D1", 1, "5 V TVS", "Littelfuse SMBJ5.0A", "SMBJ5.0A equivalent", "clamp/current suitability required"],
            ["C1", 1, "100 uF 10 V low-ESR", "Nichicon UWT1A101MCL1GS", "105 C low-ESR equivalent", "ripple/life required"],
            ["C2", 1, "100 nF 16 V X7R 0603", "Murata GRM188R71C104KA01D", "X7R equivalent", "local decoupling"],
            ["FAN1", 1, "40x10 mm 5 V four-wire PWM fan", "Noctua NF-A4x10 5V PWM", "Verified 5 V four-wire fan", "airflow/current/connector required"],
        ]),
        "cost-estimate.csv": _csv([
            ["Item", "Quantity", "Planning unit cost USD", "Planning extended USD", "Basis"],
            ["Pi HAT PCB, prototype quantity", 1, "12.00", "12.00", "placeholder; obtain quote before spend"],
            ["5 V four-wire PWM fan", 1, "15.00", "15.00", "planning allowance"],
            ["GPIO stacking header", 1, "4.50", "4.50", "planning allowance"],
            ["Fan header and protection/control parts", 1, "6.50", "6.50", "planning allowance"],
            ["Hardware/standoffs", 1, "4.00", "4.00", "planning allowance"],
            ["TOTAL", "", "", "42.00", "before tax, shipping, assembly and test"],
        ]),
        "inventory-map.csv": _csv([
            ["Need", "Required specification", "Inventory state", "Allocation"],
            ["Fan", "40x10 mm, 5 V, four-wire PWM", "not matched to a verified SKU", "none"],
            ["GPIO header", "2x20 Pi HAT stacking header", "not matched to a verified SKU", "none"],
            ["Protection/control components", "exact BOM manufacturer parts", "not matched to verified SKUs", "none"],
            ["PCB", "65 x 56.5 mm, 2-layer prototype", "not in stock", "none"],
        ]),
        "thermal-calculations.json": json.dumps({
            "status": "calculated_with_explicit_assumptions",
            "assumptions": {"ambient_c": 25, "pi5_design_heat_w": 12, "target_soc_c": 75, "fan_voltage_v": 5, "fan_current_a_assumed": 0.15},
            "results": {"required_total_thermal_resistance_c_per_w": 4.167, "fan_power_w": 0.75, "ptc_headroom_factor_at_assumed_current": 3.33},
            "limitations": ["Airflow-to-junction thermal resistance requires the selected heatsink, enclosure and measured workload.", "The HAT fan cools a heatsink; it does not replace correct thermal-interface material."],
        }, indent=2),
        "fan_control.py": _firmware(),
        "requirements.csv": _csv([
            ["ID", "Requirement", "Verification", "Status"],
            ["REQ-001", "Fit Raspberry Pi 5 HAT 65 x 56.5 mm envelope and 2x20 GPIO", "mechanical overlay and fit test", "pending physical evidence"],
            ["REQ-002", "Drive a 5 V four-wire fan using 25 kHz open-drain PWM", "oscilloscope at 0/35/100 percent", "design complete; bench test pending"],
            ["REQ-003", "Fail to full speed on software or temperature-read failure", "fault-injection test", "implemented; hardware test pending"],
            ["REQ-004", "Keep Pi SoC below 80 C at defined ambient/workload", "30 minute thermal soak", "pending physical evidence"],
            ["REQ-005", "Protect 5 V fan branch against short/overcurrent", "current-limit and fault test", "design complete; bench test pending"],
        ]),
        "verification-plan.md": """# Verification plan\n\n1. Inspect HAT outline, mounting holes, GPIO orientation, heatsink and fan clearance against Raspberry Pi 5 mechanical drawings.\n2. Run KiCad ERC and DRC with the selected fabrication stack-up; accept zero unexplained violations.\n3. Confirm fan connector pin order before power. Current-limit the 5 V supply for first power-on.\n4. Measure fan inrush and steady current; verify PTC and 5 V rail margin.\n5. Scope PWM at 25 kHz and verify fan response at 0, 35, 55, 75 and 100 percent.\n6. Verify tach input never exceeds 3.3 V and compare measured RPM with expected tolerance.\n7. Disconnect temperature source and stop the controller process; fan must reach 100 percent.\n8. Run idle and sustained CPU workload thermal soaks at 25 C and maximum intended ambient. Record SoC temperature, RPM, throttling flags and acoustics.\n9. Power-cycle ten times and perform one controlled outage recovery test.\n10. QUENCH reviews measurements, KiCad checks, BOM/datasheets and manufacturing outputs before fabrication release.\n""",
        "test-fixture.md": """# Bench test fixture\n\nUse a current-limited 5 V supply, inline current measurement, oscilloscope or logic analyzer, thermocouple near the SoC/heatsink interface, ambient sensor, tach capture, and a guarded fan. Break out 5V_FUSED, GND, FAN_PWM_OD, FAN_TACH_3V3, GPIO18 and GPIO17 at labeled test points. Record supply voltage/current, PWM frequency/duty, tach frequency/RPM, SoC temperature, ambient temperature and throttling flags every two seconds. Use a nonconductive fixture that leaves airflow unobstructed. No automated pass is valid without traceable instrument readings.\n""",
        "mechanical-fit.md": """# Mechanical fit and airflow\n\nBoard outline target: 65 x 56.5 mm with four 2.7 mm mounting holes on the Raspberry Pi HAT pattern. Confirm the exact Pi 5 connector datum, connector height, standoff height, camera/display connector access, PoE/fan header conflicts and the selected heatsink envelope against official mechanical drawings before fabrication. Place the 40 mm fan above the heatsink with a guard and at least 3 mm blade clearance. Airflow direction must be tested in the intended enclosure; recirculation or blocked exhaust invalidates the thermal estimate.\n""",
        "assembly-and-user-guide.md": """# Assembly and use\n\nDo not fabricate from this prototype until the verification plan passes. Mount a Pi 5 compatible heatsink first. Install the HAT on correctly sized standoffs with power removed. Mount the fan so airflow crosses the heatsink and does not foul cables. Confirm the exact fan connector pinout. Install `fan_control.py` with the `python3-lgpio` dependency as a restricted system service. First power-up must use a current-limited supply. Stop immediately for odor, unstable 5 V rail, fan stall, connector heating or unexpected throttling.\n""",
        "safety-compliance-review.md": """# Safety and compliance review\n\nThis is a low-voltage prototype, not a certified product. Principal hazards are reversed fan pinout, 5 V short circuit, GPIO overvoltage, fan stall, inadequate heatsink contact, moving blades and unverified materials. Controls are keyed connector verification, PTC protection, 3.3 V tach pull-up, guarded fan, full-speed failsafe, current-limited bring-up and evidence-gated release. CE/FCC/RoHS or other market claims require the final assembly, suppliers, enclosure and intended market; none are claimed here.\n""",
        "manufacturing-readiness.md": """# Manufacturing readiness\n\nStatus: BLOCKED pending physical evidence.\n\n- [ ] Exact symbols, footprints and datasheets verified\n- [ ] Pi 5 mechanical keep-out and heatsink/fan fit verified\n- [ ] KiCad ERC and DRC pass\n- [ ] Fan current, PWM and tach measurements pass\n- [ ] Thermal soak meets REQ-004\n- [ ] Gerber, drill and placement files generated from reviewed revision\n- [ ] Independent QUENCH review accepts the evidence\n\nNo purchase, fabrication, publication or supplier contact was performed.\n""",
    }
    initial_status = "prototype_package_complete_manufacturing_release_blocked"
    project = _project_record(
        package_id, created_at=created_at, updated_at=now,
        status=initial_status, independently_reviewed=False)
    files["PROJECT.json"] = json.dumps(project, indent=2)
    for name, content in files.items():
        if not _ARTIFACT.fullmatch(name):
            raise ValueError("generated artifact name is unsafe")
        (package_root / name).write_text(content, encoding="utf-8")
    artifact_records = [
        {"name": name, "bytes": (package_root / name).stat().st_size,
         "sha256": _digest(package_root / name)} for name in sorted(files)
    ]
    review = {
        "reviewer": "ORCA deterministic evidence gate",
        "independent_authoring": False,
        "result": initial_status,
        "checks": {
            "requested_artifacts_present": True,
            "all_files_nonempty": all(item["bytes"] > 0 for item in artifact_records),
            "pcb_truthfully_marked_unrouted": board["status"] == "editable_unrouted_draft",
            "physical_validation_claimed": False,
            "purchases_or_external_actions": 0,
        },
        "blocking_evidence": ["KiCad ERC/DRC", "mechanical fit", "bench electrical tests", "thermal soak", "independent QUENCH review"],
    }
    (package_root / "REVIEW.json").write_text(json.dumps(review, indent=2), encoding="utf-8")
    artifact_records.append({"name": "REVIEW.json", "bytes": (package_root / "REVIEW.json").stat().st_size, "sha256": _digest(package_root / "REVIEW.json")})
    manifest = {"schema": 1, "package_id": package_id, "created_at": datetime.now(timezone.utc).isoformat(), "status": review["result"], "artifacts": artifact_records}
    (package_root / "MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    zip_path = package_root / "ORCA-Pi5-Cooling-HAT.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(package_root.iterdir()):
            if path.is_file() and path != zip_path:
                archive.write(path, path.name)
    return {
        "package_id": package_id,
        "status": review["result"],
        "artifact_count": len(artifact_records) + 1,
        "zip_sha256": _digest(zip_path),
        "zip_bytes": zip_path.stat().st_size,
        "download_url": f"/api/product-development/packages/{package_id}/ORCA-Pi5-Cooling-HAT.zip",
        "manifest_url": f"/api/product-development/packages/{package_id}/MANIFEST.json",
        "project": project,
        "review": review,
    }


def quench_review_prompt(root: str | Path, package_id: str) -> str:
    package = Path(root).resolve() / package_id
    manifest = json.loads((package / "MANIFEST.json").read_text(encoding="utf-8"))
    artifacts = [
        {"name": item["name"], "bytes": item["bytes"],
         "sha256_prefix": item["sha256"][:16]}
        for item in manifest.get("artifacts", [])[:40]
        if isinstance(item, dict)
        and isinstance(item.get("name"), str)
        and isinstance(item.get("bytes"), int)
        and isinstance(item.get("sha256"), str)
    ]
    evidence = {
        "package_id": package_id,
        "status": manifest.get("status"),
        "artifacts": artifacts,
        "requirements": (package / "requirements.csv").read_text(encoding="utf-8")[:1_600],
        "thermal_calculations": json.loads(
            (package / "thermal-calculations.json").read_text(encoding="utf-8")),
        "verification_plan": (package / "verification-plan.md").read_text(
            encoding="utf-8")[:1_300],
        "test_fixture_plan": (package / "test-fixture.md").read_text(
            encoding="utf-8")[:1_100],
        "safety_review": (package / "safety-compliance-review.md").read_text(
            encoding="utf-8")[:900],
        "manufacturing_gate": (package / "manufacturing-readiness.md").read_text(
            encoding="utf-8")[:1_200],
    }
    readiness = package / "fabrication-readiness.md"
    if readiness.is_file():
        evidence["fabrication_readiness"] = readiness.read_text(
            encoding="utf-8")[:1_500]
        evidence["acceptance_matrix"] = (package / "acceptance-matrix.csv").read_text(
            encoding="utf-8")[:1_200]
    return (
        "Independently review this ORCA-generated Raspberry Pi 5 cooling HAT engineering "
        "package from the compact, checksum-bound evidence below. Check internal consistency, "
        "electrical and thermal claims, safety, missing evidence, testability, and whether its "
        "release block is truthful. Do not claim physical testing, certification, or manufacturing "
        "readiness. Artifact filenames in the evidence are checksum-verified proof that those files "
        "exist; distinguish an existing test plan or fixture plan from absent physical test results. "
        "Be concise so the structured result completes: summary at most 400 characters; "
        "exactly three evidence strings at most 240 characters each; uncertainty at most 240 "
        "characters; next_gate must be blocked. Return only the required QUENCH JSON contract.\n\n"
        + json.dumps(evidence, sort_keys=True, separators=(",", ":"), allow_nan=False)
    )[:8_000]


def attach_quench_review(root: str | Path, package_id: str, output: dict) -> dict:
    if not isinstance(output, dict) or not isinstance(output.get("summary"), str):
        raise ValueError("QUENCH review output is invalid")
    package = Path(root).resolve() / package_id
    if not package.is_dir():
        raise FileNotFoundError(package_id)
    review_path = package / "QUENCH-REVIEW.json"
    review_path.write_text(json.dumps(output, indent=2, sort_keys=True), encoding="utf-8")
    review = json.loads((package / "REVIEW.json").read_text(encoding="utf-8"))
    review["independent_authoring"] = True
    review["independent_reviewer"] = "QUENCH"
    review["quench_next_gate"] = output.get("next_gate")
    readiness_prepared = (package / "fabrication-readiness.md").is_file()
    review["result"] = (
        "fabrication_readiness_prepared_physical_validation_blocked"
        if readiness_prepared else
        "prototype_package_independently_reviewed_manufacturing_release_blocked"
    )
    review["blocking_evidence"] = [
        item for item in review.get("blocking_evidence", [])
        if item != "independent QUENCH review"
    ]
    (package / "REVIEW.json").write_text(json.dumps(review, indent=2), encoding="utf-8")
    prior_project = json.loads((package / "PROJECT.json").read_text(encoding="utf-8"))
    project = _project_record(
        package_id, created_at=prior_project["created_at"],
        updated_at=datetime.now(timezone.utc).isoformat(),
        status=review["result"], independently_reviewed=True)
    (package / "PROJECT.json").write_text(json.dumps(project, indent=2), encoding="utf-8")
    records = []
    for path in sorted(package.iterdir()):
        if path.is_file() and path.name not in {"MANIFEST.json", "ORCA-Pi5-Cooling-HAT.zip"}:
            records.append({"name": path.name, "bytes": path.stat().st_size, "sha256": _digest(path)})
    manifest = {"schema": 1, "package_id": package_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "status": review["result"], "artifacts": records}
    (package / "MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    zip_path = package / "ORCA-Pi5-Cooling-HAT.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(package.iterdir()):
            if path.is_file() and path != zip_path:
                archive.write(path, path.name)
    return {
        "package_id": package_id, "status": review["result"],
        "artifact_count": len(records) + 1, "zip_sha256": _digest(zip_path),
        "zip_bytes": zip_path.stat().st_size,
        "download_url": f"/api/product-development/packages/{package_id}/ORCA-Pi5-Cooling-HAT.zip",
        "manifest_url": f"/api/product-development/packages/{package_id}/MANIFEST.json",
        "project": project,
        "review": review,
    }


def prepare_fabrication_readiness(root: str | Path, project_id: str) -> dict:
    """Add truthful physical-validation procedures to an existing ORCA project."""

    if not isinstance(project_id, str) or not _PROJECT_ID.fullmatch(project_id):
        raise ValueError("fabrication-readiness project id is invalid")
    base = Path(root).resolve()
    package = None
    project = None
    for candidate in base.glob("*/PROJECT.json"):
        try:
            record = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(record, dict) and record.get("project_id") == project_id:
            package = candidate.parent
            project = record
            break
    if package is None or project is None:
        raise FileNotFoundError(project_id)

    files = {
        "fabrication-readiness.md": """# Fabrication-readiness gate\n\nStatus: SOFTWARE PREPARATION COMPLETE; PHYSICAL VALIDATION BLOCKED.\n\nORCA has prepared the controlled procedures, evidence forms, limits and acceptance matrix. No physical measurement is recorded or implied. The project may advance only after the assembled HAT is tested and each result is signed and checksum-bound.\n\n## Stop conditions\n\nStop power immediately for smoke, odor, visible heating, unstable 5 V, reverse fan rotation, fan stall, current above 1.0 A, SoC temperature above 90 C, or missing tachometer response for 30 seconds while commanded above 35 percent duty.\n\n## Required sequence\n\n1. Mechanical fit and unpowered continuity.\n2. Current-limited first power.\n3. PWM, tachometer and fault-injection bench tests.\n4. Controlled thermal soak.\n5. Evidence hashing and owner sign-off.\n6. QUENCH review of measured evidence before manufacturing release.\n""",
        "mechanical-fit-inspection.md": """# Mechanical-fit inspection and evidence form\n\nProject: ORCA Pi 5 Active-Cooling HAT\nResult: PENDING PHYSICAL HARDWARE\n\n- [ ] Correct GPIO orientation and full connector seating\n- [ ] Four mounting holes align without board flex\n- [ ] Standoff height measured and recorded\n- [ ] Fan guard and blades have at least 3 mm clearance\n- [ ] Heatsink, CSI/DSI, PoE/fan header and cables remain accessible\n- [ ] Air inlet and exhaust remain unobstructed in the intended enclosure\n- [ ] Photographs include scale and project/revision identifier\n\nRecord measured offsets, minimum clearances, instrument/scale used, date, operator and evidence filenames. Any forced fit, connector interference or blade/cable contact is a fail.\n""",
        "bench-electrical-test.md": """# Bench electrical, PWM, tachometer and fault test\n\nResult: PENDING PHYSICAL HARDWARE\n\nUse a current-limited 5 V supply for first power. Verify unpowered resistance from 5V_FUSED to GND and connector pin order before attaching the fan. Record supply voltage, inrush current and steady current. Scope PWM at 0, 35, 55, 75 and 100 percent command; frequency shall be 25 kHz within 5 percent and the fan response shall be monotonic. Verify tach input never exceeds 3.3 V and record frequency/RPM. Disconnect temperature input and stop the control process separately; each fault must command 100 percent fan. Open tach for 30 seconds above 35 percent command and verify the declared safe response. Stop on any fabrication-readiness stop condition.\n\nFor every step record timestamp, instrument make/model/serial, calibration status, setup photograph, raw reading or trace filename, expected range, pass/fail and operator initials.\n""",
        "thermal-soak-procedure.md": """# Controlled thermal-soak procedure\n\nResult: PENDING PHYSICAL HARDWARE\n\nMeasure ambient temperature and use the final Pi, heatsink, fan, enclosure and intended sustained workload. Log ambient, SoC temperature, duty, RPM, 5 V current and throttling flags every two seconds. Stabilize at idle, then run at least 30 minutes at sustained load and maximum intended ambient. Pass requires SoC below 80 C, no thermal throttling, stable tach response, no stop condition and repeatable cooldown. Abort immediately above 90 C, on fan stall, current above 1.0 A, unstable power, odor or visible heating. Preserve the raw log; summaries alone are not evidence.\n""",
        "instrumentation-list.csv": _csv([
            ["Instrument", "Minimum capability", "Evidence required"],
            ["Digital multimeter", "DC voltage/current and resistance", "make/model/serial and calibration status"],
            ["Oscilloscope or logic analyzer", "100 MHz or adequate 25 kHz PWM/tach capture", "raw traces and setup photograph"],
            ["Current-limited 5 V supply", "at least 2 A with adjustable limit", "limit, voltage and current log"],
            ["Temperature logger", "SoC/ambient capture at 2 second interval", "raw CSV and sensor placement photograph"],
            ["Mechanical scale or caliper", "0.1 mm resolution or better", "clearance measurements and photographs"],
        ]),
        "acceptance-matrix.csv": _csv([
            ["Gate", "Acceptance criterion", "State", "Evidence"],
            ["Mechanical alignment", "GPIO and four mounts align without stress", "PENDING", "measurements and photographs"],
            ["Clearance", "fan blades/guard at least 3 mm from obstructions", "PENDING", "caliper readings and photographs"],
            ["Power", "stable 5 V; current below 1.0 A stop limit", "PENDING", "supply log"],
            ["PWM", "25 kHz within 5 percent; monotonic response", "PENDING", "scope traces"],
            ["Tach", "at most 3.3 V and plausible RPM", "PENDING", "scope traces and calculation"],
            ["Failsafe", "temperature/process faults command 100 percent", "PENDING", "fault log and traces"],
            ["Thermal", "below 80 C; no throttling for 30 minutes", "PENDING", "raw two-second log"],
            ["Evidence", "all files named and SHA-256 hashed", "PENDING", "signed evidence manifest"],
        ]),
        "evidence-rules.md": """# Physical evidence rules\n\nStore evidence under a revision-specific directory. Name each file `ORCA_<PROJECT>_<GATE>_<UTC-DATE>_<SEQUENCE>.<ext>`. Preserve original instrument exports and photographs. Create a SHA-256 manifest after collection; never edit a file after hashing. The manifest must include project ID, hardware revision, operator, UTC timestamps, instrument identities and every file hash. QUENCH may review copies, but release decisions must reference the immutable manifest. Missing, edited, ambiguous or summary-only evidence leaves the gate blocked.\n""",
        "owner-execution-checklist.md": """# Owner physical-validation checklist\n\n- [ ] Confirm exact hardware revision and fan connector pinout\n- [ ] Complete mechanical inspection and photographs\n- [ ] Complete unpowered continuity and current-limited first power\n- [ ] Capture PWM and tach traces at every commanded duty\n- [ ] Perform temperature-source, process-stop and tach-loss fault tests\n- [ ] Complete the controlled thermal soak with raw two-second logging\n- [ ] Hash all evidence and sign the manifest\n- [ ] Submit the evidence set to ORCA for independent QUENCH review\n- [ ] Release only if every acceptance-matrix row passes\n\nUntil these boxes are supported by physical evidence, manufacturing release remains blocked.\n""",
    }
    for name, content in files.items():
        (package / name).write_text(content, encoding="utf-8")

    now = datetime.now(timezone.utc).isoformat()
    status = "fabrication_readiness_prepared_physical_validation_blocked"
    project.update({"updated_at": now, "status": status,
                    "manufacturing_release": "blocked_pending_physical_evidence"})
    (package / "PROJECT.json").write_text(json.dumps(project, indent=2), encoding="utf-8")
    review_path = package / "REVIEW.json"
    review = json.loads(review_path.read_text(encoding="utf-8"))
    review["result"] = status
    review["fabrication_readiness"] = {
        "software_preparation_complete": True,
        "physical_measurements_claimed": False,
        "physical_validation": "pending_owner_present_hardware",
    }
    review["blocking_evidence"] = [
        "mechanical fit measurements", "bench electrical/PWM/tach/fault results",
        "thermal soak measurements",
    ]
    review_path.write_text(json.dumps(review, indent=2), encoding="utf-8")
    records = []
    for path in sorted(package.iterdir()):
        if path.is_file() and path.name not in {"MANIFEST.json", "ORCA-Pi5-Cooling-HAT.zip"}:
            records.append({"name": path.name, "bytes": path.stat().st_size,
                            "sha256": _digest(path)})
    manifest = {"schema": 1, "package_id": project["package_id"],
                "created_at": now, "status": status, "artifacts": records}
    (package / "MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    zip_path = package / "ORCA-Pi5-Cooling-HAT.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(package.iterdir()):
            if path.is_file() and path != zip_path:
                archive.write(path, path.name)
    return {
        "package_id": project["package_id"], "project_id": project_id,
        "status": status, "artifact_count": len(records) + 1,
        "zip_sha256": _digest(zip_path), "zip_bytes": zip_path.stat().st_size,
        "download_url": f"/api/product-development/packages/{project['package_id']}/ORCA-Pi5-Cooling-HAT.zip",
        "manifest_url": f"/api/product-development/packages/{project['package_id']}/MANIFEST.json",
        "project": project, "review": review,
    }


def list_product_projects(root: str | Path) -> list[dict]:
    """List bounded, durable ORCA product projects without exposing host paths."""

    base = Path(root).resolve()
    projects = []
    if not base.is_dir():
        return projects
    for path in base.glob("*/PROJECT.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if (isinstance(record, dict)
                and isinstance(record.get("project_id"), str)
                and isinstance(record.get("updated_at"), str)):
            projects.append(record)
    return sorted(projects, key=lambda item: item["updated_at"], reverse=True)


def resolve_product_package_artifact(root: str | Path, package_id: str, artifact: str) -> Path:
    if not _PACKAGE.fullmatch(package_id) or not _ARTIFACT.fullmatch(artifact):
        raise ValueError("invalid product artifact path")
    base = (Path(root).resolve() / package_id).resolve()
    path = (base / artifact).resolve()
    if base not in path.parents or not path.is_file():
        raise FileNotFoundError(artifact)
    return path
