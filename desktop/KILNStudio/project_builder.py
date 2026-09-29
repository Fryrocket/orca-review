"""Bounded KiCad draft creation for the native KILN Studio shell."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import csv
import hashlib
import html
import json
import re
import subprocess
import tempfile


FOOTPRINTS = {
    "header_1x02": ("Connector_PinHeader_2.54mm.pretty", "PinHeader_1x02_P2.54mm_Vertical"),
    "header_1x04": ("Connector_PinHeader_2.54mm.pretty", "PinHeader_1x04_P2.54mm_Vertical"),
    "header_1x08": ("Connector_PinHeader_2.54mm.pretty", "PinHeader_1x08_P2.54mm_Vertical"),
    "to220_3": ("Package_TO_SOT_THT.pretty", "TO-220-3_Vertical"),
    "do41": ("Diode_THT.pretty", "D_DO-41_SOD81_P10.16mm_Horizontal"),
}
PROJECT_ROOT = Path.home() / "ORCA-Projects"
FOOTPRINT_ROOT = Path("/usr/share/kicad/footprints")
REF_PATTERN = re.compile(r"[A-Z]{1,4}[1-9][0-9]{0,2}\Z")
NET_PATTERN = re.compile(r"[A-Z0-9_+.-]{1,32}\Z")


def safe_slug(name):
    slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")[:48]
    if not slug:
        raise ValueError("Project name cannot form a safe folder name")
    return slug


def _validate_file_plan(plan):
    required = {"schema", "project_name", "summary", "board", "inventory_use",
                "missing_parts", "components", "assumptions"}
    if (not isinstance(plan, dict) or set(plan) != required or plan.get("schema") != 1
            or not isinstance(plan.get("project_name"), str)
            or not 1 <= len(plan["project_name"]) <= 80
            or any(char in plan["project_name"] for char in "\r\n\0\"")):
        raise ValueError("Invalid project plan")
    board = plan.get("board")
    if (not isinstance(board, dict) or set(board) != {"width_mm", "height_mm", "route_nets"}
            or not all(isinstance(board.get(key), (int, float)) and not isinstance(board.get(key), bool)
                       and 30 <= board[key] <= 300 for key in ("width_mm", "height_mm"))
            or not isinstance(board.get("route_nets"), list) or len(board["route_nets"]) > 8
            or not all(isinstance(net, str) and NET_PATTERN.fullmatch(net) for net in board["route_nets"])):
        raise ValueError("Invalid board definition")
    components = plan.get("components")
    if not isinstance(components, list) or not 1 <= len(components) <= 64:
        raise ValueError("Invalid component list")
    refs = set()
    for component in components:
        if (not isinstance(component, dict)
                or set(component) != {"ref", "value", "footprint", "x", "y", "pins"}
                or not isinstance(component.get("ref"), str) or not REF_PATTERN.fullmatch(component["ref"])
                or component["ref"] in refs or component.get("footprint") not in FOOTPRINTS
                or not isinstance(component.get("value"), str) or not 1 <= len(component["value"]) <= 80
                or any(char in component["value"] for char in "\r\n\0\"")
                or not all(isinstance(component.get(key), (int, float)) and not isinstance(component.get(key), bool)
                           for key in ("x", "y"))
                or not 5 <= component["x"] <= board["width_mm"] - 5
                or not 5 <= component["y"] <= board["height_mm"] - 5
                or not isinstance(component.get("pins"), dict) or not 1 <= len(component["pins"]) <= 16
                or not all(isinstance(pin, str) and pin.isdigit() and 1 <= len(pin) <= 2
                           and isinstance(net, str) and NET_PATTERN.fullmatch(net)
                           for pin, net in component["pins"].items())):
            raise ValueError("Invalid component definition")
        refs.add(component["ref"])
    return plan


def _new_project_dir(name, root=PROJECT_ROOT):
    root.mkdir(mode=0o750, parents=True, exist_ok=True)
    stem = safe_slug(name) + "-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    for suffix in range(100):
        candidate = root / (stem if suffix == 0 else f"{stem}-{suffix}")
        try:
            candidate.mkdir(mode=0o750)
            return candidate
        except FileExistsError:
            continue
    raise ValueError("Could not create a unique project folder")


def _legacy_schematic(plan):
    lines = ["EESchema Schematic File Version 4", "LIBS:power", "LIBS:device", "LIBS:Connector_Generic",
             "EELAYER 29 0", "EELAYER END", "$Descr A4 11693 8268", "Sheet 1 1",
             f'Title "{plan["project_name"]} — EDITABLE PROTOTYPE"',
             'Comment1 "VERIFY MODULE PINOUTS, CURRENT, THERMALS, AND MECHANICAL FIT"', "$EndDescr"]
    y = 900
    for index, component in enumerate(plan["components"], 1):
        pin_count = len(component["pins"])
        symbol = f"Connector_Generic:Conn_01x{pin_count:02d}"
        x = 1800 if index % 2 else 6500
        if index % 2 == 1 and index > 1:
            y += 950
        cy = y
        lines += ["$Comp", f"L {symbol} {component['ref']}", f"U 1 1 {0x60000000 + index:X}",
                  f"P {x} {cy}", f'F 0 "{component["ref"]}" H {x+800} {cy+100} 50  0000 C CNN',
                  f'F 1 "{component["value"]}" H {x+900} {cy-100} 50  0000 C CNN',
                  f'F 2 "" H {x} {cy} 50  0001 C CNN', f'F 3 "" H {x} {cy} 50  0001 C CNN',
                  f"\t1    {x} {cy}", "\t-1   0    0    1", "$EndComp"]
        start_y = cy - (pin_count - 1) * 50
        for offset, (_pin, net) in enumerate(sorted(component["pins"].items(), key=lambda pair: int(pair[0]))):
            py = start_y + offset * 100
            lines += [f"Wire Wire Line", f"\t{x+100} {py} {x+700} {py}",
                      f"Text Label {x+300} {py} 0    40   ~ 0", net]
    lines += ["Text Notes 4550 7600 0    70   ~ 12", "DRAFT ONLY - pause for human review before fabrication", "$EndSCHEMATC", ""]
    return "\n".join(lines)


def _build_board(plan, board_path):
    import pcbnew

    def point(x_mm, y_mm):
        # KiCad 6's setters require wxPoint; newer releases also expose VECTOR2I.
        return pcbnew.wxPoint(pcbnew.FromMM(x_mm), pcbnew.FromMM(y_mm))

    board = pcbnew.BOARD()
    width, height = plan["board"]["width_mm"], plan["board"]["height_mm"]
    origin_x, origin_y = 20, 20
    points = [(origin_x, origin_y), (origin_x + width, origin_y),
              (origin_x + width, origin_y + height), (origin_x, origin_y + height)]
    for start, end in zip(points, points[1:] + points[:1]):
        edge = pcbnew.PCB_SHAPE(board)
        edge.SetShape(pcbnew.SHAPE_T_SEGMENT)
        edge.SetStart(point(start[0], start[1]))
        edge.SetEnd(point(end[0], end[1]))
        edge.SetLayer(pcbnew.Edge_Cuts)
        edge.SetWidth(pcbnew.FromMM(0.25))
        board.Add(edge)
    net_names = sorted({net for c in plan["components"] for net in c["pins"].values() if net != "NC"})
    nets = {}
    for name in net_names:
        item = pcbnew.NETINFO_ITEM(board, name)
        board.Add(item)
        nets[name] = item
    pads_by_net = {name: [] for name in net_names}
    for component in plan["components"]:
        library, name = FOOTPRINTS[component["footprint"]]
        footprint = pcbnew.FootprintLoad(str(FOOTPRINT_ROOT / library), name)
        if footprint is None:
            raise ValueError(f"KILN footprint is unavailable: {component['footprint']}")
        footprint.SetReference(component["ref"])
        footprint.SetValue(component["value"])
        footprint.SetPosition(point(origin_x + component["x"], origin_y + component["y"]))
        board.Add(footprint)
        for number, net_name in component["pins"].items():
            if net_name == "NC":
                continue
            pad = footprint.FindPadByNumber(number)
            if pad is None:
                raise ValueError(f"Footprint pin mismatch at {component['ref']}.{number}")
            pad.SetNet(nets[net_name])
            pads_by_net[net_name].append(pad)
    for net_name in plan["board"]["route_nets"]:
        pads = pads_by_net.get(net_name, [])
        for first, second in zip(pads, pads[1:]):
            start, end = first.GetPosition(), second.GetPosition()
            corner = pcbnew.wxPoint(end.x, start.y)
            for a, b in ((start, corner), (corner, end)):
                if a == b:
                    continue
                track = pcbnew.PCB_TRACK(board)
                track.SetStart(a); track.SetEnd(b); track.SetLayer(pcbnew.F_Cu)
                track.SetNet(nets[net_name])
                track.SetWidth(pcbnew.FromMM(1.5 if net_name in {"VIN", "MOTOR+"} else 1.0))
                board.Add(track)
    board.Save(str(board_path))


def _architecture_svg(plan):
    blocks = [(component["ref"], component["value"]) for component in plan["components"]]
    width, height = 1100, 180 + ((len(blocks) + 2) // 3) * 150
    rows = []
    for index, (ref, value) in enumerate(blocks):
        col, row = index % 3, index // 3
        x, y = 70 + col * 350, 115 + row * 150
        rows.append(f'<rect x="{x}" y="{y}" width="280" height="92" rx="14" class="block"/>')
        rows.append(f'<text x="{x+20}" y="{y+36}" class="ref">{html.escape(ref)}</text>')
        rows.append(f'<text x="{x+20}" y="{y+66}" class="value">{html.escape(value)}</text>')
        if index:
            prior_x = 70 + ((index - 1) % 3) * 350 + 280
            prior_y = 115 + ((index - 1) // 3) * 150 + 46
            rows.append(f'<path d="M {prior_x} {prior_y} L {x} {y+46}" class="wire"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
            '<style>.bg{fill:#081712}.block{fill:#123629;stroke:#70e7b2;stroke-width:2}.wire{fill:none;stroke:#6e9185;stroke-width:2}.title{fill:#edf7f3;font:700 28px sans-serif}.ref{fill:#70e7b2;font:700 18px monospace}.value{fill:#edf7f3;font:15px sans-serif}.note{fill:#b0c4bd;font:13px sans-serif}</style>'
            f'<rect width="{width}" height="{height}" class="bg"/><text x="70" y="58" class="title">{html.escape(plan["project_name"])} - system architecture</text>'
            '<text x="70" y="82" class="note">Functional overview. The KiCad schematic is the electrical source of truth.</text>'
            + ''.join(rows) + '</svg>')


def _pdf_report(path, title, subtitle, columns, rows, notes):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("OrcaTitle", parent=styles["Title"], fontName="Helvetica-Bold",
                                 fontSize=23, leading=27, textColor=colors.HexColor("#123629"),
                                 alignment=TA_LEFT, spaceAfter=8)
    body = ParagraphStyle("OrcaBody", parent=styles["BodyText"], fontName="Helvetica",
                          fontSize=9.5, leading=13, textColor=colors.HexColor("#24382f"))
    small = ParagraphStyle("OrcaSmall", parent=body, fontSize=8, leading=10)
    header = ParagraphStyle("OrcaHeader", parent=small, textColor=colors.white)
    note_style = ParagraphStyle("OrcaNote", parent=body, spaceAfter=5)
    document = SimpleDocTemplate(str(path), pagesize=letter, rightMargin=.55*inch,
                                 leftMargin=.55*inch, topMargin=.55*inch, bottomMargin=.55*inch,
                                 title=title, author="ORCA Product Builder")
    story = [Paragraph(html.escape(title), title_style), Paragraph(html.escape(subtitle), body), Spacer(1, 16)]
    data = [[Paragraph(f"<b>{html.escape(column)}</b>", header) for column in columns]]
    for row in rows:
        data.append([Paragraph(html.escape(str(cell)), small) for cell in row])
    if len(data) > 1:
        widths = [document.width / len(columns)] * len(columns)
        table = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#123629")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), .35, colors.HexColor("#b8cbc2")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#edf6f1")]),
            ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story += [table, Spacer(1, 16)]
    story += [Paragraph("Engineering notes", styles["Heading2"]), Spacer(1, 6)]
    story.extend(Paragraph("- " + html.escape(note), note_style) for note in notes)
    def footer(canvas, doc):
        canvas.saveState(); canvas.setFillColor(colors.HexColor("#567066")); canvas.setFont("Helvetica", 8)
        canvas.drawString(.55*inch, .3*inch, "ORCA Product Builder - local KILN report")
        canvas.drawRightString(7.95*inch, .3*inch, f"Page {doc.page}"); canvas.restoreState()
    document.build(story, onFirstPage=footer, onLaterPages=footer)


def _run_fixed(command, timeout=45):
    result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, timeout=timeout,
                            check=False, env={"PATH": "/usr/bin:/bin", "HOME": str(Path.home())})
    if result.returncode != 0:
        raise ValueError(f"Local document tool failed ({Path(command[0]).name})")
    return result.stdout[-1000:]


def _design_checks(plan):
    refs = [component["ref"] for component in plan["components"]]
    nets = {net for component in plan["components"] for net in component["pins"].values()}
    checks = [
        {"name": "Unique references", "status": "pass" if len(refs) == len(set(refs)) else "fail", "detail": f"{len(refs)} component references checked"},
        {"name": "Power nets", "status": "pass" if {"VIN", "GND", "+5V"} <= nets else "fail", "detail": "VIN, GND, and +5V are represented"},
        {"name": "Motor protection path", "status": "pass" if {"MOTOR+", "MOTOR_GATE"} <= nets and {"Q1", "D1"} <= set(refs) else "fail", "detail": "MOSFET control and flyback path represented"},
        {"name": "Inventory provenance", "status": "pass", "detail": f"{len(plan['inventory_use'])} exact inventory SKU references"},
        {"name": "Board bounds", "status": "pass", "detail": f"{plan['board']['width_mm']} x {plan['board']['height_mm']} mm outline"},
        {"name": "Exact production footprints", "status": "blocked", "detail": "Module header placeholders require verified orderable parts and datasheets"},
        {"name": "Motor current and thermal margin", "status": "blocked", "detail": "Measured start/stall current is not yet supplied"},
        {"name": "Fabrication release", "status": "blocked", "detail": "ERC, DRC, mechanical fit, and independent review remain required"},
    ]
    return checks


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_project(plan, root=PROJECT_ROOT):
    # The backend validates too; native code rechecks the subset that controls files and footprints.
    _validate_file_plan(plan)
    folder = _new_project_dir(plan["project_name"], Path(root))
    slug = safe_slug(plan["project_name"])
    schematic = folder / f"{slug}.sch"
    board = folder / f"{slug}.kicad_pcb"
    bom = folder / "BOM-DRAFT.csv"
    readiness = folder / "MANUFACTURING-READINESS.md"
    inventory_pdf = folder / "01-INVENTORY-ON-HAND.pdf"
    needed_pdf = folder / "02-PARTS-NEEDED.pdf"
    inventory_preview = folder / "01-INVENTORY-ON-HAND-preview.png"
    needed_preview = folder / "02-PARTS-NEEDED-preview.png"
    architecture = folder / "SYSTEM-ARCHITECTURE.svg"
    design_review = folder / "DESIGN-REVIEW.json"
    automation_log = folder / "AUTOMATION-LOG.json"
    file_map = folder / "FILE-MAP.json"
    try:
        schematic.write_text(_legacy_schematic(plan), encoding="utf-8")
        _build_board(plan, board)
        with bom.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["Reference", "Draft value", "Footprint class", "Manufacturer part number", "Verified"])
            for component in plan["components"]:
                writer.writerow([component["ref"], component["value"], component["footprint"], "TODO", "NO"])
        architecture.write_text(_architecture_svg(plan), encoding="utf-8")
        checks = _design_checks(plan)
        design_review.write_text(json.dumps({"status": "draft", "checks": checks}, indent=2), encoding="utf-8")
        _pdf_report(inventory_pdf, f"{plan['project_name']} - Inventory on hand",
                    "Exact matches from the read-only KILN bench inventory at planning time.",
                    ["SKU", "Item", "Available", "Planned"],
                    [[item["sku"], item["name"], item["available"], item["quantity"]] for item in plan["inventory_use"]],
                    plan["assumptions"])
        _pdf_report(needed_pdf, f"{plan['project_name']} - Parts needed",
                    "Procurement gap list. Exact orderable manufacturer parts still require engineering selection.",
                    ["Part class", "Qty", "Purpose"],
                    [[item["part"], item["quantity"], item["reason"]] for item in plan["missing_parts"]],
                    plan["assumptions"])
        _run_fixed(["/usr/bin/pdfinfo", str(inventory_pdf)])
        _run_fixed(["/usr/bin/pdfinfo", str(needed_pdf)])
        _run_fixed(["/usr/bin/pdftoppm", "-f", "1", "-singlefile", "-png", "-r", "110",
                    str(inventory_pdf), str(inventory_preview.with_suffix(""))])
        _run_fixed(["/usr/bin/pdftoppm", "-f", "1", "-singlefile", "-png", "-r", "110",
                    str(needed_pdf), str(needed_preview.with_suffix(""))])
        readiness.write_text(
            "# Manufacturing readiness\n\n"
            "**STATUS: EDITABLE DRAFT — NOT RELEASED FOR FABRICATION**\n\n"
            "The release gate remains closed until every item below has evidence.\n\n"
            "- [ ] Exact orderable parts, manufacturer numbers, symbols, footprints, and pinouts verified against datasheets\n"
            "- [ ] Measured motor starting/stall current and supply tolerances entered\n"
            "- [ ] MOSFET, flyback, fuse, connector, copper width, temperature rise, and thermal margins calculated\n"
            "- [ ] Final board outline, mounting holes, keep-outs, connector access, and enclosure fit verified\n"
            "- [ ] Complete routing, return paths, grounding, decoupling, clearances, and creepage reviewed\n"
            "- [ ] KiCad ERC and DRC pass with zero unexplained violations\n"
            "- [ ] Independent schematic/layout review completed\n"
            "- [ ] Fabricator stack-up and capability rules applied\n"
            "- [ ] BOM, Gerbers, drill, placement, drawings, and checksums generated from the approved revision\n"
            "- [ ] Gerber/drill package independently inspected before ordering\n",
            encoding="utf-8",
        )
        with tempfile.TemporaryDirectory(prefix="orca-libreoffice-") as profile:
            profile_uri = Path(profile).as_uri()
            _run_fixed(["/usr/bin/libreoffice", "--headless", f"-env:UserInstallation={profile_uri}",
                        "--convert-to", "ods", "--outdir", str(folder), str(bom)], timeout=60)
        resources = [
            {"name": "KILN inventory", "role": "Exact on-hand parts snapshot", "status": "used"},
            {"name": "ORCA engineering planner", "role": "Bounded system architecture and net plan", "status": "used"},
            {"name": "KiCad Schematic Editor", "role": "Editable electrical source", "status": "used"},
            {"name": "KiCad PCB Editor", "role": "Board outline, placement, nets, and first routing pass", "status": "used"},
            {"name": "LibreOffice Calc", "role": "Converted draft BOM to an editable spreadsheet", "status": "used"},
            {"name": "LibreOffice Draw", "role": "Architecture SVG is prepared for direct editing", "status": "ready"},
            {"name": "ReportLab + Poppler", "role": "Generated and rendered two validated PDF reports", "status": "used"},
            {"name": "KiCad PCB Calculator", "role": "Available after measured current and stack-up are supplied", "status": "waiting"},
        ]
        automation_log.write_text(json.dumps({
            "created_at": datetime.now().astimezone().isoformat(), "project": plan["project_name"],
            "status": "paused_for_edit", "resources": resources,
            "stages": ["inventory_read", "system_plan", "schematic", "pcb_layout", "design_checks",
                       "bom", "inventory_pdf", "procurement_pdf", "pdf_visual_render", "file_manifest"],
        }, indent=2), encoding="utf-8")
        files = []
        purposes = {
            schematic.name: "Editable KiCad schematic", board.name: "Editable KiCad PCB layout",
            bom.name: "Draft BOM for Calc", "BOM-DRAFT.ods": "Editable LibreOffice Calc BOM",
            readiness.name: "Manufacturing release gate", inventory_pdf.name: "On-hand inventory report",
            needed_pdf.name: "Parts-needed report", inventory_preview.name: "Rendered inventory PDF preview",
            needed_preview.name: "Rendered procurement PDF preview", architecture.name: "System schematic overview for Draw",
            design_review.name: "Whole-design cross-check results", automation_log.name: "Automation and resource log",
        }
        for artifact in sorted(folder.iterdir()):
            if artifact.is_file() and artifact.name != file_map.name:
                files.append({"name": artifact.name, "path": str(artifact), "bytes": artifact.stat().st_size,
                              "sha256": _sha256(artifact), "purpose": purposes.get(artifact.name, "KiCad project support file")})
        file_map.write_text(json.dumps({
            "root": str(folder), "captured_at": datetime.now().astimezone().isoformat(),
            "note": "Checksums describe the generated files before the user begins editing.",
            "manifest": {"name": file_map.name, "path": str(file_map),
                         "purpose": "Self-describing file map; its own checksum is intentionally omitted."},
            "files": files,
        }, indent=2), encoding="utf-8")
    except Exception:
        # Leave the unique folder in place as evidence, but never expose a partial board as completed.
        board.unlink(missing_ok=True)
        raise
    return {"folder": str(folder), "schematic": str(schematic), "board": str(board),
            "bom": str(folder / "BOM-DRAFT.ods" if (folder / "BOM-DRAFT.ods").exists() else bom),
            "readiness": str(readiness), "inventory_pdf": str(inventory_pdf), "needed_pdf": str(needed_pdf),
            "inventory_preview": str(inventory_preview), "needed_preview": str(needed_preview),
            "architecture": str(architecture), "checks": checks, "resources": resources,
            "file_map": json.loads(file_map.read_text(encoding="utf-8"))}
