"""Natural-language → KiCad project skeleton generator.

Produces a minimal but valid-ish KiCad 6/7 schematic (.kicad_sch) text,
BOM CSV, and design notes from a plain English description.
This is a structured template generator — not a full EE CAD AI.
Always review in KiCad GUI before manufacturing.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List
from datetime import datetime, timezone

from .errors import HardPrivilegeError


@dataclass
class Component:
    ref: str
    value: str
    footprint: str = ""
    mpn: str = ""
    notes: str = ""


@dataclass
class ProjectSpec:
    name: str
    description: str
    components: List[Component] = field(default_factory=list)
    nets: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


# Very small heuristic dictionary for common parts in Fry-style builds
_PART_HINTS = [
    (r"\b(xiao\s*esp32[-_]?c3|esp32[-_]?c3)\b", Component("U1", "XIAO-ESP32-C3", "Module:Seeed_XIAO_ESP32C3", "", "MCU")),
    (r"\b(max30102)\b", Component("U2", "MAX30102", "Module:MAX30102", "", "PPG")),
    (r"\b(lis3dh)\b", Component("U3", "LIS3DH", "Package_LGA:LGA-16_3x3mm_P0.5mm", "", "IMU")),
    (r"\b(bpw34)\b", Component("D1", "BPW34", "Diode_SMD:D_SOD-123", "", "Photodiode")),
    (r"\b(tsal6200|940\s*nm|ir\s*led)\b", Component("D2", "TSAL6200", "LED_THT:LED_D5.0mm", "", "940nm IR emitter")),
    (r"\bjst[-_]?ph|battery\s*connector\b", Component("J1", "JST-PH-2", "Connector_JST:JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical", "", "Battery")),
    (r"\b(oled|ssd1306)\b", Component("U4", "SSD1306_128x64", "Module:SSD1306", "", "OLED")),
    (r"\b(100k)\b", Component("R1", "100k", "Resistor_SMD:R_0603_1608Metric", "", "Bias/load")),
    (r"\b(100\s*ohm|100r)\b", Component("R2", "100", "Resistor_SMD:R_0603_1608Metric", "", "LED series")),
    (r"\b(100u|100\s*µf|100uf)\b", Component("C1", "100uF", "Capacitor_SMD:C_1206_3216Metric", "", "Bulk 3V3")),
]


def _safe_project_name(name: str) -> str:
    """R11-F73: `name` is joined into the output path. A value like
    `../outside` or `/tmp/x` escaped repo_root because ToolRegistry
    path_params do not include `name` (it looks like a title)."""
    if not isinstance(name, str) or not name.strip():
        raise HardPrivilegeError("kicad_gen name must be a non-empty path segment")
    p = Path(name)
    if p.is_absolute() or len(p.parts) != 1 or p.parts[0] in {".", ".."}:
        raise HardPrivilegeError(
            f"kicad_gen name must be a single path segment (got {name!r})"
        )
    if name != p.parts[0]:
        raise HardPrivilegeError(
            f"kicad_gen name must be a single path segment (got {name!r})"
        )
    return p.parts[0]


def parse_nl(description: str, name: str = "orca_board") -> ProjectSpec:
    text = description.lower()
    comps: List[Component] = []
    used_refs = set()
    for pat, proto in _PART_HINTS:
        if re.search(pat, text, re.I):
            c = Component(proto.ref, proto.value, proto.footprint, proto.mpn, proto.notes)
            if c.ref in used_refs:
                base = re.sub(r"\d+$", "", c.ref)
                n = 1
                while f"{base}{n}" in used_refs:
                    n += 1
                c.ref = f"{base}{n}"
            used_refs.add(c.ref)
            comps.append(c)

    nets = ["GND", "3V3"]
    if any(c.value.upper().startswith("XIAO") or "ESP32" in c.value.upper() for c in comps):
        nets += ["SDA", "SCL", "TX", "RX"]
    if any("MAX30102" in c.value.upper() for c in comps):
        nets += ["I2C_SDA", "I2C_SCL"]

    warnings = [
        "AUTO-GENERATED skeleton — open in KiCad and run ERC/DRC before fab.",
        "Footprints are best-effort guesses; verify against your library.",
        "No copper pours, differential pairs, or full hierarchical sheets.",
    ]
    if not comps:
        warnings.append("No known parts matched; added placeholder MCU only.")
        comps.append(Component("U1", "MCU", "", "", "placeholder"))

    return ProjectSpec(name=name, description=description, components=comps, nets=nets, warnings=warnings)


def _kicad_str(s: str) -> str:
    """Escape a value for embedding inside a KiCad S-expression string
    literal.

    R11-F82: render_kicad_sch/_sch_symbol_block interpolated component and
    spec fields into double-quoted S-expression strings with no escaping.
    spec.description is free natural-language text (e.g. 3.3" wide) --
    an embedded `"` terminates the string field early, leaving the rest of
    that description as bare unquoted tokens in the output and producing
    an invalid .kicad_sch file. Escape backslashes and quotes the same way
    the S-expression format itself expects.
    """
    return str(s).replace("\\", "\\\\").replace('"', '\\"')


def _sch_symbol_block(c: Component, x: int, y: int) -> str:
    ref = _kicad_str(c.ref)
    value = _kicad_str(c.value)
    footprint = _kicad_str(c.footprint)
    return f"""\t(symbol (lib_id \"Device:R\") (at {x} {y} 0) (unit 1)
\t\t(in_bom yes) (on_board yes)
\t\t(property \"Reference\" \"{ref}\" (at {x} {y-2.54} 0)
\t\t\t(effects (font (size 1.27 1.27)))
\t\t)
\t\t(property \"Value\" \"{value}\" (at {x} {y+2.54} 0)
\t\t\t(effects (font (size 1.27 1.27)))
\t\t)
\t\t(property \"Footprint\" \"{footprint}\" (at {x} {y} 0)
\t\t\t(effects (font (size 1.27 1.27)) (hide yes))
\t\t)
\t\t(property \"Datasheet\" \"\" (at {x} {y} 0)
\t\t\t(effects (font (size 1.27 1.27)) (hide yes))
\t\t)
\t)
"""


def render_kicad_sch(spec: ProjectSpec) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d")
    body = []
    x, y = 50, 50
    for c in spec.components:
        body.append(_sch_symbol_block(c, x, y))
        y += 15
        if y > 150:
            y = 50
            x += 40
    symbols = "".join(body)
    name = _kicad_str(spec.name)
    description = _kicad_str(spec.description[:120])
    return f"""(kicad_sch (version 20230121) (generator orca_kicad_gen)
\t(paper \"A4\")
\t(title_block
\t\t(title \"{name}\")
\t\t(date \"{ts}\")
\t\t(comment 1 \"{description}\")
\t\t(comment 2 \"Generated by Orca — REVIEW BEFORE FAB\")
\t)
\t(lib_symbols)
{symbols}
\t(sheet_instances
\t\t(path \"/\" (page \"1\"))
\t)
)
"""


def write_project(spec: ProjectSpec, out_dir: str | Path) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    sch_path = out / f"{spec.name}.kicad_sch"
    bom_path = out / f"{spec.name}_bom.csv"
    notes_path = out / f"{spec.name}_notes.md"

    sch_path.write_text(render_kicad_sch(spec))

    with bom_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Ref", "Value", "Footprint", "MPN", "Notes"])
        for c in spec.components:
            w.writerow([c.ref, c.value, c.footprint, c.mpn, c.notes])

    notes = [
        f"# {spec.name} — Orca design notes",
        "",
        f"Source description: {spec.description}",
        "",
        "## Warnings",
        *[f"- {w}" for w in spec.warnings],
        "",
        "## Nets (suggested)",
        *[f"- {n}" for n in spec.nets],
        "",
        "## Components",
        *[f"- {c.ref}: {c.value} ({c.footprint or 'no footprint'})" for c in spec.components],
        "",
        "Open the .kicad_sch in KiCad, assign real symbols/footprints, then ERC/DRC.",
    ]
    notes_path.write_text("\n".join(notes))

    return {
        "schematic": str(sch_path),
        "bom": str(bom_path),
        "notes": str(notes_path),
        "components": [c.ref + ":" + c.value for c in spec.components],
        "warnings": spec.warnings,
    }


def generate_from_nl(description: str, name: str = "orca_board", out_dir: str = "runs/kicad_projects") -> dict:
    name = _safe_project_name(name)
    spec = parse_nl(description, name=name)
    result = write_project(spec, Path(out_dir) / name)
    result["name"] = name
    result["description"] = description
    return result


def register_kicad_gen_tools(registry) -> None:
    def kicad_gen(description: str, name: str = "orca_board") -> str:
        # R11-F76: generate_from_nl defaults out_dir to "runs/kicad_projects"
        # relative to cwd. ToolRegistry path_params never see that implicit
        # path, so a cwd outside repo_root wrote files the allowlist never
        # audited (F73 only constrained `name`). Pin to repo_root/runs/.
        root = Path(registry.repo_root).resolve()
        out_dir = (root / "runs" / "kicad_projects").resolve()
        try:
            out_dir.relative_to(root)
        except ValueError:
            raise HardPrivilegeError(
                f"kicad_gen out_dir escaped repo root: {out_dir}"
            )
        r = generate_from_nl(description, name=name, out_dir=str(out_dir))
        return (
            f"[kicad_gen] {r['name']}\n"
            f"sch: {r['schematic']}\n"
            f"bom: {r['bom']}\n"
            f"notes: {r['notes']}\n"
            f"parts: {', '.join(r['components'])}\n"
            f"warnings: {'; '.join(r['warnings'])}"
        )

    registry.register_function(
        "kicad_gen",
        "Generate a KiCad schematic skeleton + BOM from natural language",
        kicad_gen,
    )
