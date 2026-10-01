from __future__ import annotations

from dataclasses import asdict, dataclass
import re


_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/+ -]{0,127}$")
_AIM_PREFIXES = {"]C0": "Code 128", "]C1": "GS1-128", "]E0": "EAN/UPC",
                 "]E4": "EAN/UPC", "]Q3": "QR"}
_GTIN_TYPES = {8: "EAN-8", 12: "UPC-A", 13: "EAN-13", 14: "GTIN-14"}


@dataclass(frozen=True)
class Barcode:
    raw: str
    value: str
    symbology: str
    checksum_valid: bool | None
    lookup_candidates: tuple[str, ...]


def _gtin_checksum(value: str) -> bool:
    body, supplied = value[:-1], int(value[-1])
    total = sum(int(char) * (3 if index % 2 == 0 else 1)
                for index, char in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == supplied


def normalize_barcode(raw: object) -> dict:
    """Normalize decoded scanner text; never controls a scanner or mutates stock."""
    if not isinstance(raw, str):
        raise ValueError("barcode must be text")
    original = raw
    value = raw.strip()
    if not value or len(value) > 128 or not value.isprintable():
        raise ValueError("barcode is empty, too long, or contains control characters")
    declared = None
    if value[:3] in _AIM_PREFIXES:
        declared, value = _AIM_PREFIXES[value[:3]], value[3:]
    if not value or not _SAFE.fullmatch(value):
        raise ValueError("barcode contains unsupported characters")
    checksum = None
    symbology = declared or "internal/code-128-compatible"
    if value.isdigit() and len(value) in _GTIN_TYPES:
        symbology = _GTIN_TYPES[len(value)]
        checksum = _gtin_checksum(value)
        if not checksum:
            raise ValueError(f"{symbology} check digit is invalid")
    candidates = [value]
    if value.isdigit():
        unpadded = value.lstrip("0") or "0"
        if unpadded not in candidates:
            candidates.append(unpadded)
        if len(value) == 12:
            candidates.append("0" + value)
        if len(value) in {12, 13}:
            candidates.append(value.zfill(14))
    return asdict(Barcode(original, value, symbology, checksum,
                          tuple(dict.fromkeys(candidates))))
