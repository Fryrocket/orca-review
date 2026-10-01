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


def plan_inventory_capture_session(*, manifest: dict, session_id: str,
                                   camera_profile: str,
                                   operator: str = "Fry") -> dict:
    """Build a deterministic capture checklist without opening a camera."""
    if not isinstance(manifest, dict) or manifest.get("schema") != "orca.inventory-vision-dataset.v1":
        raise ValueError("capture planning requires an inventory vision manifest")
    capture_id = _text(session_id, "capture session id", 64).upper()
    if not _IDENTIFIER.fullmatch(capture_id):
        raise ValueError("capture session id must be a stable identifier")
    profile = _text(camera_profile, "camera profile", 120)
    capture_operator = _text(operator, "capture operator", 80)
    labels = manifest.get("labels")
    if not isinstance(labels, list) or not labels:
        raise ValueError("capture manifest has no labels")
    target = manifest.get("target_images_per_label")
    if type(target) is not int or not 50 <= target <= 2_000:
        raise ValueError("capture manifest target is invalid")
    scenarios = (
        "front_and_barcode", "rear", "left_and_right", "top_and_rotated",
        "shelf_or_bin", "partly_occluded", "alternate_lighting", "hard_negative",
    )
    base, extra = divmod(target, len(scenarios))
    quotas = [
        {"scenario": scenario, "per_label": base + (index < extra)}
        for index, scenario in enumerate(scenarios)
    ]
    canonical = {
        "schema": "orca.inventory-vision-capture.v1",
        "session_id": capture_id,
        "manifest_sha256": _text(manifest.get("manifest_sha256"), "manifest sha256", 64),
        "camera_profile": profile,
        "operator": capture_operator,
        "label_ids": [row["id"] for row in labels],
        "quotas": quotas,
    }
    digest = hashlib.sha256(json.dumps(
        canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        **canonical,
        "capture_plan_sha256": digest,
        "state": "owner_capture_checklist_ready",
        "frames_planned": target * len(labels),
        "frames_captured": 0,
        "may_open_camera": False,
        "may_capture": False,
        "privacy_preflight": [
            "fixed owner-approved camera zone", "no people or private documents in frame",
            "barcode and SKU agree before label assignment", "remove failed frames before import",
        ],
        "next_gate": "owner starts a bounded capture session and reviews every imported frame",
    }


def validate_inventory_dataset(*, manifest: dict, assets: list[dict]) -> dict:
    """Validate bounded dataset metadata for balance, leakage and provenance."""
    if not isinstance(manifest, dict) or manifest.get("schema") != "orca.inventory-vision-dataset.v1":
        raise ValueError("validation requires an inventory vision manifest")
    if not isinstance(assets, list) or not 1 <= len(assets) <= 10_000:
        raise ValueError("dataset assets must contain 1-10000 rows")
    labels = {row["id"] for row in manifest.get("labels", [])}
    allowed_splits = frozenset({"train", "validation", "test"})
    allowed_fields = frozenset({
        "id", "label_id", "sha256", "perceptual_hash", "source_hash", "split",
        "camera_profile", "reviewers", "has_person", "width", "height",
    })
    seen_ids: set[str] = set()
    seen_sha: dict[str, str] = {}
    seen_phash: dict[str, str] = {}
    issues: list[dict] = []
    counts = {label: {split: 0 for split in allowed_splits} for label in labels}
    normalized: list[dict] = []
    for index, raw in enumerate(assets):
        if not isinstance(raw, dict) or set(raw) - allowed_fields:
            raise ValueError("dataset asset contains unsupported fields")
        asset_id = _text(raw.get("id"), "asset id", 96)
        label_id = _text(raw.get("label_id"), "asset label id", 64).upper()
        split = _text(raw.get("split"), "asset split", 16)
        sha256 = _text(raw.get("sha256"), "asset sha256", 64).lower()
        phash = _text(raw.get("perceptual_hash"), "asset perceptual hash", 64).lower()
        source_hash = _text(raw.get("source_hash"), "asset source hash", 64).lower()
        profile = _text(raw.get("camera_profile"), "asset camera profile", 120)
        reviewers = raw.get("reviewers")
        width, height = raw.get("width"), raw.get("height")
        if label_id not in labels:
            issues.append({"code": "unknown_label", "asset": asset_id})
        if split not in allowed_splits:
            issues.append({"code": "invalid_split", "asset": asset_id})
        if not re.fullmatch(r"[0-9a-f]{64}", sha256) or not re.fullmatch(r"[0-9a-f]{64}", source_hash):
            raise ValueError("asset cryptographic hashes must be lowercase SHA-256")
        if not re.fullmatch(r"[0-9a-f]{16,64}", phash):
            raise ValueError("asset perceptual hash is invalid")
        if asset_id in seen_ids:
            issues.append({"code": "duplicate_asset_id", "asset": asset_id})
        if sha256 in seen_sha:
            issues.append({"code": "duplicate_content", "asset": asset_id,
                           "other": seen_sha[sha256]})
        if phash in seen_phash and seen_phash[phash] != split:
            issues.append({"code": "split_leakage", "asset": asset_id})
        reviewers_valid = (isinstance(reviewers, list)
                           and all(isinstance(value, str) and value.strip()
                                   for value in reviewers))
        if not reviewers_valid or len(set(reviewers)) < 2:
            issues.append({"code": "two_pass_review_missing", "asset": asset_id})
        if raw.get("has_person") is not False:
            issues.append({"code": "privacy_frame_rejected", "asset": asset_id})
        if (type(width) is not int or type(height) is not int
                or not 224 <= width <= 16_384 or not 224 <= height <= 16_384):
            issues.append({"code": "invalid_dimensions", "asset": asset_id})
        seen_ids.add(asset_id)
        seen_sha.setdefault(sha256, asset_id)
        seen_phash.setdefault(phash, split)
        if label_id in labels and split in allowed_splits:
            counts[label_id][split] += 1
        normalized.append({
            "id": asset_id, "label_id": label_id, "sha256": sha256,
            "perceptual_hash": phash, "source_hash": source_hash, "split": split,
            "camera_profile": profile,
            "reviewers": sorted(set(reviewers)) if reviewers_valid else [],
            "has_person": raw.get("has_person"), "width": width, "height": height,
        })
    expected = manifest.get("split", {})
    for label_id, actual in counts.items():
        for split in allowed_splits:
            if actual[split] != expected.get(split):
                issues.append({"code": "dataset_imbalance", "label_id": label_id,
                               "split": split, "expected": expected.get(split),
                               "actual": actual[split]})
    canonical = {"manifest_sha256": manifest.get("manifest_sha256"),
                 "assets": sorted(normalized, key=lambda row: row["id"])}
    digest = hashlib.sha256(json.dumps(
        canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "schema": "orca.inventory-vision-validation.v1",
        "manifest_sha256": manifest.get("manifest_sha256"),
        "dataset_sha256": digest,
        "state": "accepted_for_training" if not issues else "rejected",
        "accepted": not issues,
        "may_train": False,
        "assets": len(assets),
        "counts": counts,
        "issues": sorted(issues, key=lambda row: (row["code"], row.get("asset", ""))),
        "checks": {
            "balance": not any(row["code"] == "dataset_imbalance" for row in issues),
            "exact_duplicates": not any(row["code"] == "duplicate_content" for row in issues),
            "split_leakage": not any(row["code"] == "split_leakage" for row in issues),
            "provenance_and_review": not any(row["code"] in {
                "two_pass_review_missing", "privacy_frame_rejected", "invalid_dimensions"
            } for row in issues),
        },
        "next_gate": "train in an isolated job and submit metrics to QUENCH" if not issues
                     else "resolve every dataset issue and rerun validation",
    }


def plan_hailo_conversion(*, manifest: dict, validation: dict,
                          training_metrics: dict, toolchain: dict) -> dict:
    """Create a Hailo-8 conversion and registry candidate; never run conversion."""
    if validation.get("manifest_sha256") != manifest.get("manifest_sha256"):
        raise ValueError("validation does not match the dataset manifest")
    required_metrics = {"precision", "recall", "count_error_rate", "source_model_sha256"}
    if not isinstance(training_metrics, dict) or set(training_metrics) != required_metrics:
        raise ValueError("training metrics schema is invalid")
    if not isinstance(toolchain, dict) or set(toolchain) != {
            "hailo_dataflow_compiler", "hailort", "target"}:
        raise ValueError("Hailo toolchain schema is invalid")
    source_hash = _text(training_metrics["source_model_sha256"], "source model sha256", 64).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", source_hash):
        raise ValueError("source model hash must be SHA-256")
    target = _text(toolchain["target"], "Hailo target", 32).lower()
    if target != "hailo8":
        raise ValueError("only the enrolled Hailo-8 target is allowed")
    compiler = _text(toolchain["hailo_dataflow_compiler"], "compiler version", 40)
    runtime = _text(toolchain["hailort"], "HailoRT version", 40)
    metrics = {key: training_metrics[key] for key in (
        "precision", "recall", "count_error_rate")}
    if any(type(value) not in {int, float} for value in metrics.values()):
        raise ValueError("training metrics must be numeric")
    gates = manifest.get("quality_gates", {})
    metrics_pass = (
        metrics["precision"] >= gates.get("minimum_precision", 1)
        and metrics["recall"] >= gates.get("minimum_recall", 1)
        and metrics["count_error_rate"] <= gates.get("maximum_count_error_rate", 0)
    )
    eligible = validation.get("accepted") is True and metrics_pass
    canonical = {
        "schema": "orca.hailo-model-registry.v1",
        "model_id": f"{manifest['name']}-{manifest['version']}-hailo8",
        "dataset_sha256": validation.get("dataset_sha256"),
        "source_model_sha256": source_hash,
        "target": target,
        "toolchain": {"hailo_dataflow_compiler": compiler, "hailort": runtime},
        "metrics": metrics,
    }
    registry_id = hashlib.sha256(json.dumps(
        canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        **canonical,
        "registry_record_sha256": registry_id,
        "state": "conversion_plan_ready" if eligible else "blocked_quality_gate",
        "quality_gate_passed": eligible,
        "may_convert": False,
        "may_register": False,
        "may_deploy": False,
        "conversion_steps": [
            "verify isolated source model checksum", "calibrate with train-only samples",
            "compile HEF for hailo8", "run parity and thermal benchmark on TEMPER",
            "QUENCH reviews metrics and evidence", "Fry approves registry and deployment",
        ] if eligible else [],
        "next_gate": "run bounded offline conversion with retained logs" if eligible
                     else "resolve dataset validation or model quality failures",
    }
