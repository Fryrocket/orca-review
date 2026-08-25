"""R11-F82 ("kicad_sch string escaping").

render_kicad_sch/_sch_symbol_block interpolated spec.name, description,
and component ref/value/footprint into double-quoted KiCad S-expression
strings with no escaping. A free-text description containing an ordinary
quote (e.g. 3.3" wide) closed the literal early and produced an invalid
.kicad_sch file.

Fix: _kicad_str() escapes backslashes and quotes before embedding.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mao.kicad_gen import Component, ProjectSpec, parse_nl, render_kicad_sch


def _unescaped_quotes(s: str) -> int:
    n = 0
    i = 0
    while i < len(s):
        if s[i] == "\\":
            i += 2
            continue
        if s[i] == '"':
            n += 1
        i += 1
    return n


def _line_containing(sch: str, needle: str) -> str:
    for line in sch.splitlines():
        if needle in line:
            return line
    raise AssertionError(f"no line containing {needle!r} in:\n{sch}")


def test_description_with_embedded_quote_produces_well_formed_comment_line():
    description = 'XIAO ESP32-C3 board, 3.3" wide, with a MAX30102 sensor "v2"'
    spec = parse_nl(description, name="orca_board")
    sch = render_kicad_sch(spec)
    line = _line_containing(sch, "(comment 1 ")
    assert _unescaped_quotes(line) == 2, line
    assert '\\"' in line
    assert "3.3" in line
    assert "v2" in line


def test_name_with_embedded_quote_produces_well_formed_title_line():
    spec = ProjectSpec(
        name='board "v2"',
        description="plain",
        components=[Component("U1", "MCU")],
    )
    sch = render_kicad_sch(spec)
    line = _line_containing(sch, "(title ")
    assert _unescaped_quotes(line) == 2, line
    assert '\\"v2\\"' in line


def test_component_value_with_embedded_quote_is_escaped():
    spec = ProjectSpec(
        name="orca_board",
        description="plain",
        components=[Component("R1", '3.3"', "Resistor_SMD:R_0603_1608Metric")],
    )
    sch = render_kicad_sch(spec)
    line = _line_containing(sch, '(property "Value"')
    assert _unescaped_quotes(line) == 4, line  # "Value" + "3.3\""
    assert re.search(r'\"3\.3\\\"\"', line), line


def test_plain_description_is_unaffected():
    spec = parse_nl("xiao esp32-c3 with max30102", name="orca_board")
    sch = render_kicad_sch(spec)
    assert '(title "orca_board")' in sch
    comment = _line_containing(sch, "(comment 1 ")
    assert spec.description[:120] in comment
    assert "\\" not in comment
    assert _unescaped_quotes(comment) == 2
