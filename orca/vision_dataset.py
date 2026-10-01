from __future__ import annotations

import hashlib
import json
import re


_IDENTIFIER = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,63}$")
_PROHIBITED_LABELS = frozenset({
    "face", "person", "identity", "employee", "customer", "license_plate",
    "race", "ethnicity", "religion", "disability", "medical_condition",
})


def _text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    result = value.strip()
    if not result or len(result) > maximum or any(ord(char) < 32 for char in result):
        raise ValueError(f"{field} is invalid")
    return result


def plan_inventory_vision_dataset(*, name: str, version: str,
                                  labels: list[dict], source: str,
                                  license_name: str,
                                  target_images_per_label: int = 120) -> dict:
    """Create a deterministic, non-executing inventory-vision dataset plan."""
    dataset_name = _text(name, "dataset name", 80)
    dataset_version = _text(version, "dataset version", 32)
    provenance_source = _text(source, "dataset source", 240)
    provenance_license = _text(license_name, "dataset license", 80)
    if type(target_images_per_label) is not int or not 50 <= target_images_per_label <= 2_000:
        raise ValueError("target images per label must be 50-2000")
    if not isinstance(labels, list) or not 1 <= len(labels) <= 50:
        raise ValueError("dataset labels must contain 1-50 rows")

    normalized: list[dict] = []
    label_ids: set[str] = set()
    skus: set[str] = set()
    for raw in labels:
        if not isinstance(raw, dict):
            raise ValueError("dataset label row must be an object")
        if set(raw) - {"id", "name", "sku", "barcode", "description"}:
            raise ValueError("dataset label row contains unsupported fields")
        label_id = _text(raw.get("id"), "label id", 64).upper()
        sku = _text(raw.get("sku"), "label sku", 64).upper()
        if not _IDENTIFIER.fullmatch(label_id) or not _IDENTIFIER.fullmatch(sku):
            raise ValueError("label id and sku must be stable inventory identifiers")
        if label_id.casefold() in _PROHIBITED_LABELS:
            raise ValueError("people, identity, or sensitive-trait labels are prohibited")
        if label_id in label_ids or sku in skus:
            raise ValueError("dataset label ids and skus must be unique")
        label_ids.add(label_id)
        skus.add(sku)
        row = {
            "id": label_id,
            "name": _text(raw.get("name"), "label name", 80),
            "sku": sku,
            "barcode": _text(raw.get("barcode", sku), "label barcode", 128),
            "description": _text(
                raw.get("description", f"Visible inventory item {sku}"),
                "label description", 240),
        }
        normalized.append(row)

    normalized.sort(key=lambda row: row["id"])
    train = max(1, round(target_images_per_label * 0.70))
    validation = max(1, round(target_images_per_label * 0.15))
    test = target_images_per_label - train - validation
    canonical = {
        "schema": "orca.inventory-vision-dataset.v1",
        "name": dataset_name,
        "version": dataset_version,
        "task": "inventory_object_detection",
        "labels": normalized,
        "target_images_per_label": target_images_per_label,
        "split": {"train": train, "validation": validation, "test": test},
        "provenance": {
            "source": provenance_source,
            "license": provenance_license,
            "owner_attestation_required": True,
        },
    }
    digest = hashlib.sha256(json.dumps(
        canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        **canonical,
        "manifest_sha256": digest,
        "state": "capture_plan_ready",
        "may_capture": False,
        "may_train": False,
        "may_deploy": False,
        "capture_requirements": [
            "owner-approved fixed camera zone with no people in frame",
            "front, rear, side, top, rotated, stacked and partly occluded examples",
            "representative shelf, bin, bench and packaging backgrounds",
            "bright, normal and dim lighting without unreadable labels",
            "empty-scene and visually similar hard-negative examples",
            "source hash, timestamp, camera profile and label reviewer per image",
        ],
        "quality_gates": {
            "label_review": "two-pass review with SKU/barcode match",
            "split_isolation": "near-duplicate scenes stay in one split",
            "minimum_recall": 0.95,
            "minimum_precision": 0.95,
            "maximum_count_error_rate": 0.02,
            "unknown_item_behavior": "abstain and stage for review",
            "ledger_authority": "canonical inventory remains authoritative",
        },
        "prohibited": [
            "facial recognition", "identity inference", "covert recording",
            "automatic stock mutation", "self-approval", "unreviewed model deployment",
        ],
        "next_gate": "collect owner-approved representative images and complete two-pass labeling",
    }
