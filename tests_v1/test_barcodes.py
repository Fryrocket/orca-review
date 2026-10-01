import pytest

from orca.barcodes import normalize_barcode
from orca.inventory_count import validate_count_observations


@pytest.mark.parametrize(("value", "kind"), [
    ("036000291452", "UPC-A"),
    ("4006381333931", "EAN-13"),
    ("96385074", "EAN-8"),
    ("10012345678902", "GTIN-14"),
])
def test_standard_retail_barcodes_validate_check_digits(value, kind):
    result = normalize_barcode(value)
    assert result["value"] == value
    assert result["symbology"] == kind
    assert result["checksum_valid"] is True


def test_aim_prefix_and_internal_code_are_normalized_without_guessing_checksum():
    result = normalize_barcode("]C1QVP-HAT-001")
    assert result["value"] == "QVP-HAT-001"
    assert result["symbology"] == "GS1-128"
    assert result["checksum_valid"] is None


def test_bad_checksum_control_characters_and_oversize_values_fail_closed():
    with pytest.raises(ValueError, match="check digit"):
        normalize_barcode("036000291453")
    with pytest.raises(ValueError, match="control"):
        normalize_barcode("ABC\n123")
    with pytest.raises(ValueError, match="too long"):
        normalize_barcode("A" * 129)


def test_inventory_counts_store_normalized_scanner_value():
    rows = validate_count_observations([{
        "barcode": "]C1QVP-HAT-001", "location": "BIN-A",
        "counted_quantity": 1, "condition": "good",
    }])
    assert rows[0]["sku"] == "QVP-HAT-001"
    assert rows[0]["barcode"] == "QVP-HAT-001"
