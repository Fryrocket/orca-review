import pytest

from orca.cad import create_kicad_pcb_draft


@pytest.mark.parametrize("prompt,preset,size,connector", [
    ("Create a .kicad_pcb for a Raspberry Pi 5 HAT", "Raspberry Pi HAT", (65.0, 56.5), "J1"),
    ("Create a KiCad PCB board for an ESP32 carrier", "ESP32 carrier", (70.0, 50.0), "J2"),
    ("Create a 42 x 37 mm PCB file for a sensor", "Custom board", (42.0, 37.0), None),
])
def test_create_editable_kicad_board_drafts(prompt, preset, size, connector):
    result = create_kicad_pcb_draft(prompt)
    assert result["preset"] == preset
    assert (result["width_mm"], result["height_mm"]) == size
    assert result["filename"].endswith(".kicad_pcb")
    assert result["content"].startswith("(kicad_pcb (version 20240108)")
    assert 'layer "Edge.Cuts"' in result["content"]
    assert "NOT MANUFACTURING READY" in result["content"]
    assert result["status"] == "editable_unrouted_draft"
    if connector:
        assert f'"{connector}"' in result["content"]


@pytest.mark.parametrize("prompt", ["", "x" * 4001, "Create a 5 x 5 mm PCB", "Create a 900 x 30 mm PCB"])
def test_pcb_draft_rejects_empty_oversized_or_unsafe_dimensions(prompt):
    with pytest.raises(ValueError):
        create_kicad_pcb_draft(prompt)


def test_chat_ui_recognizes_pcb_creation_and_returns_downloadable_file():
    source = open("orca/static/app.js", encoding="utf-8").read()
    assert "function wantsChatPCB" in source
    assert "'/api/cad/pcb-draft'" in source
    assert "application/x-kicad-pcb" in source
    assert "Save and open in PCB Editor" in source
