from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class BoardPreset:
    name: str
    width: float
    height: float
    connector: str | None = None


def _bounded_prompt(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 4_000:
        raise ValueError("PCB request must contain 1-4,000 characters")
    if any(ord(character) < 32 and character not in "\n\t" for character in value):
        raise ValueError("PCB request contains invalid control characters")
    return " ".join(value.split())


def _preset(prompt: str) -> BoardPreset:
    lower = prompt.casefold()
    if re.search(r"\b(?:raspberry\s*pi|pi\s*5|pi\s+hat|gpio\s*40)\b", lower):
        return BoardPreset("Raspberry Pi HAT", 65.0, 56.5, "pi40")
    if re.search(r"\besp32\b", lower):
        return BoardPreset("ESP32 carrier", 70.0, 50.0, "esp32")
    if re.search(r"\barduino\b", lower):
        return BoardPreset("Arduino shield", 68.6, 53.4, "arduino")
    dimension = re.search(
        r"\b(\d{1,3}(?:\.\d{1,2})?)\s*(?:mm)?\s*(?:x|by|×)\s*"
        r"(\d{1,3}(?:\.\d{1,2})?)\s*mm\b", lower)
    if dimension:
        width, height = map(float, dimension.groups())
        if not 20 <= width <= 300 or not 20 <= height <= 300:
            raise ValueError("board dimensions must be between 20 and 300 mm")
        return BoardPreset("Custom board", width, height)
    return BoardPreset("Custom board", 100.0, 80.0)


def _slug(prompt: str, preset: BoardPreset) -> str:
    words = re.findall(r"[A-Za-z0-9]+", prompt)[:8]
    text = "-".join(words) or preset.name
    return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")[:64] or "orca-board"


def _quote(value: str) -> str:
    return value.replace("\\", " ").replace('"', "'")[:160]


def _mounting_hole(reference: str, x: float, y: float) -> str:
    return f'''  (footprint "MountingHole:MountingHole_2.7mm" (layer "F.Cu") (at {x:.2f} {y:.2f})
    (property "Reference" "{reference}" (at 0 -2 0) (layer "F.SilkS")
      (effects (font (size 0.6 0.6) (thickness 0.1))))
    (property "Value" "M2.5" (at 0 4 0) (layer "F.Fab") hide
      (effects (font (size 1 1) (thickness 0.15))))
    (fp_circle (center 0 0) (end 3 0) (stroke (width 0.3) (type default)) (fill none) (layer "F.CrtYd"))
    (pad "" np_thru_hole circle (at 0 0) (size 2.75 2.75) (drill 2.75) (layers "*.Cu" "*.Mask")))'''


def _pin_header(reference: str, columns: int, rows: int, x: float, y: float) -> str:
    pads = []
    number = 1
    for column in range(columns):
        for row in range(rows):
            px, py = column * 2.54, row * 2.54
            shape = "rect" if number == 1 else "oval"
            pads.append(
                f'    (pad "{number}" thru_hole {shape} (at {px:.2f} {py:.2f}) '
                f'(size 1.7 1.7) (drill 1.0) (layers "*.Cu" "*.Mask"))')
            number += 1
    width, height = max(2.54, (columns - 1) * 2.54 + 2.54), max(2.54, (rows - 1) * 2.54 + 2.54)
    footprint = f"PinHeader_{columns}x{rows:02d}_P2.54mm_Vertical"
    return f'''  (footprint "Connector_PinHeader_2.54mm:{footprint}" (layer "F.Cu") (at {x:.2f} {y:.2f})
    (property "Reference" "{reference}" (at {width / 2:.2f} -2.5 0) (layer "F.SilkS")
      (effects (font (size 1 1) (thickness 0.15))))
    (property "Value" "{columns}x{rows} Pin Header" (at {width / 2:.2f} {height + 2.5:.2f} 0) (layer "F.Fab")
      (effects (font (size 1 1) (thickness 0.15))))
    (fp_rect (start -1.27 -1.27) (end {width - 1.27:.2f} {height - 1.27:.2f})
      (stroke (width 0.25) (type default)) (fill none) (layer "F.SilkS"))
{chr(10).join(pads)})'''


def create_kicad_pcb_draft(prompt: str) -> dict:
    """Create a bounded, editable KiCad board starter; never a manufacturing release."""

    prompt = _bounded_prompt(prompt)
    preset = _preset(prompt)
    slug = _slug(prompt, preset)
    x0, y0 = 20.0, 20.0
    x1, y1 = x0 + preset.width, y0 + preset.height
    footprints = [
        _mounting_hole("H1", x0 + 3.5, y0 + 3.5),
        _mounting_hole("H2", x1 - 3.5, y0 + 3.5),
        _mounting_hole("H3", x0 + 3.5, y1 - 3.5),
        _mounting_hole("H4", x1 - 3.5, y1 - 3.5),
    ]
    if preset.connector == "pi40":
        footprints.append(_pin_header("J1", 2, 20, x0 + 7.0, y0 + 4.5))
    elif preset.connector == "esp32":
        footprints.extend((
            _pin_header("J1", 1, 19, x0 + 10.0, y0 + 2.0),
            _pin_header("J2", 1, 19, x1 - 10.0, y0 + 2.0),
        ))
    elif preset.connector == "arduino":
        footprints.extend((
            _pin_header("J1", 1, 8, x0 + 5.0, y0 + 5.0),
            _pin_header("J2", 1, 10, x1 - 5.0, y0 + 5.0),
            _pin_header("J3", 1, 6, x0 + 5.0, y1 - 20.0),
            _pin_header("J4", 1, 8, x1 - 5.0, y1 - 25.0),
        ))
    title = _quote(preset.name)
    description = _quote(prompt)
    content = f'''(kicad_pcb (version 20240108) (generator pcbnew)
  (general (thickness 1.6))
  (paper "A4")
  (title_block
    (title "{title} — ORCA editable draft")
    (comment 1 "NOT MANUFACTURING READY — unrouted concept starter")
    (comment 2 "{description}"))
  (layers
    (0 "F.Cu" signal)
    (31 "B.Cu" signal)
    (36 "B.SilkS" user "b.silkscreen")
    (37 "F.SilkS" user "f.silkscreen")
    (44 "Edge.Cuts" user))
  (setup (pad_to_mask_clearance 0))
  (gr_rect (start {x0:.2f} {y0:.2f}) (end {x1:.2f} {y1:.2f})
    (stroke (width 0.25) (type default)) (fill none) (layer "Edge.Cuts"))
  (gr_text "ORCA DRAFT"
    (at {x1-11.0:.2f} {y1-5.0:.2f}) (layer "F.SilkS")
    (effects (font (size 0.7 0.7) (thickness 0.12))))
{chr(10).join(footprints)}
)
'''
    return {
        "filename": f"{slug}.kicad_pcb",
        "content": content,
        "preset": preset.name,
        "width_mm": preset.width,
        "height_mm": preset.height,
        "status": "editable_unrouted_draft",
        "warnings": [
            "No schematic connectivity or copper routing is claimed.",
            "Verify footprints, pin mapping, board outline, clearances, stackup, ERC and DRC before fabrication.",
            "Manufacturing release remains blocked pending engineering review.",
        ],
    }
