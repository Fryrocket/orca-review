#!/usr/bin/env python3
"""Deterministic, draft-only media coordinator for ORCA and CRUCIBLE."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path

from orca.security import redact_text


MAX_INPUT_BYTES = 512_000
MAX_ASSETS = 24
ALLOWED_CHANNELS = {
    "website", "shopify", "amazon", "ebay", "alibaba", "temu",
    "wholesale", "organic_social", "maker_community",
}
ALLOWED_RIGHTS = {"owned", "licensed", "public_domain", "generated"}
ALLOWED_ASSET_TYPES = {"product_image", "illustration", "diagram", "short_video"}
ALLOWED_IMAGE_SIZES = {
    (512, 512), (768, 768), (1024, 1024), (1216, 832),
    (832, 1216), (1152, 896), (896, 1152),
}
ALLOWED_VIDEO_SIZES = {
    (832, 480), (480, 832), (640, 640), (1024, 576), (576, 1024),
}
PROHIBITED_CLAIM_TYPES = {"review", "testimonial", "endorsement", "scarcity"}


def _text(value, name, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"invalid {name}")
    cleaned = value.strip()
    if redact_text(cleaned) != cleaned:
        raise ValueError(f"{name} contains secret-shaped data")
    return cleaned


def _channels(value):
    if not isinstance(value, list) or not value or len(value) > len(ALLOWED_CHANNELS):
        raise ValueError("invalid channels")
    channels = []
    for channel in value:
        if channel not in ALLOWED_CHANNELS:
            raise ValueError("unsupported channel")
        if channel in channels:
            raise ValueError("duplicate channel")
        channels.append(channel)
    return channels


def _claims(value):
    if not isinstance(value, list) or len(value) > 50:
        raise ValueError("invalid claims")
    claims = []
    ids = set()
    for row in value:
        if not isinstance(row, dict) or set(row) != {"id", "type", "text", "evidence_url"}:
            raise ValueError("invalid claim schema")
        claim_id = _text(row.get("id"), "claim id", 80)
        claim_type = _text(row.get("type"), "claim type", 40).lower()
        claim_text = _text(row.get("text"), "claim text", 500)
        evidence = _text(row.get("evidence_url"), "claim evidence", 2_000)
        if claim_id in ids:
            raise ValueError("duplicate claim")
        if claim_type in PROHIBITED_CLAIM_TYPES:
            raise ValueError("prohibited claim type")
        if claim_type not in {"technical", "performance", "descriptive"}:
            raise ValueError("unsupported claim type")
        if not evidence.startswith("https://"):
            raise ValueError("claim evidence must use HTTPS")
        ids.add(claim_id)
        claims.append({
            "id": claim_id, "type": claim_type, "text": claim_text,
            "evidence_url": evidence, "review_state": "evidence_attached_requires_review",
        })
    return claims


def _sources(value):
    if not isinstance(value, list) or len(value) > 50:
        raise ValueError("invalid source assets")
    sources, ids = [], set()
    for row in value:
        if not isinstance(row, dict) or set(row) != {"id", "rights", "reference", "sha256"}:
            raise ValueError("invalid source asset schema")
        source_id = _text(row.get("id"), "source id", 80)
        rights = row.get("rights")
        reference = _text(row.get("reference"), "source reference", 2_000)
        digest = row.get("sha256")
        if source_id in ids:
            raise ValueError("duplicate source asset")
        if rights not in ALLOWED_RIGHTS:
            raise ValueError("unlicensed source asset")
        if not isinstance(digest, str) or len(digest) != 64:
            raise ValueError("invalid source digest")
        try:
            bytes.fromhex(digest)
        except ValueError:
            raise ValueError("invalid source digest") from None
        ids.add(source_id)
        sources.append({
            "id": source_id, "rights": rights, "reference": reference,
            "sha256": digest.lower(), "rights_review_state": "declared_requires_review",
        })
    return sources


def _asset_job(row, *, claim_ids, source_ids):
    required = {
        "id", "type", "channels", "prompt", "negative_prompt", "width", "height",
        "seed", "claim_ids", "source_asset_ids",
    }
    optional = {"frames", "fps"}
    if not isinstance(row, dict) or not required <= set(row) or set(row) - required - optional:
        raise ValueError("invalid media asset schema")
    asset_id = _text(row.get("id"), "asset id", 80)
    asset_type = row.get("type")
    if asset_type not in ALLOWED_ASSET_TYPES:
        raise ValueError("unsupported asset type")
    prompt = _text(row.get("prompt"), "prompt", 1_500)
    negative = row.get("negative_prompt")
    if not isinstance(negative, str) or len(negative) > 1_000:
        raise ValueError("invalid negative prompt")
    if redact_text(negative) != negative:
        raise ValueError("negative prompt contains secret-shaped data")
    width, height, seed = row.get("width"), row.get("height"), row.get("seed")
    if type(width) is not int or type(height) is not int:
        raise ValueError("invalid media dimensions")
    if type(seed) is not int or not 0 <= seed < 2**53:
        raise ValueError("invalid media seed")
    dimensions = (width, height)
    if asset_type == "short_video":
        if dimensions not in ALLOWED_VIDEO_SIZES:
            raise ValueError("unsupported video dimensions")
        frames, fps = row.get("frames"), row.get("fps")
        if frames not in {49, 73, 121} or fps not in {16, 24}:
            raise ValueError("unsupported video timing")
        endpoint, model = "/video/generate", "wan2.2_ti2v_5B_fp16.safetensors"
    else:
        if "frames" in row or "fps" in row or dimensions not in ALLOWED_IMAGE_SIZES:
            raise ValueError("unsupported image settings")
        frames = fps = None
        endpoint, model = "/generate", "sd_xl_base_1.0.safetensors"

    selected_claims = row.get("claim_ids")
    selected_sources = row.get("source_asset_ids")
    if (not isinstance(selected_claims, list) or len(selected_claims) != len(set(selected_claims))
            or not set(selected_claims) <= claim_ids):
        raise ValueError("asset references an unknown or duplicate claim")
    if (not isinstance(selected_sources, list) or len(selected_sources) != len(set(selected_sources))
            or not set(selected_sources) <= source_ids):
        raise ValueError("asset references an unknown or duplicate source")

    request = {
        "prompt": prompt, "negative_prompt": negative.strip(), "width": width,
        "height": height, "seed": seed,
    }
    if asset_type == "short_video":
        request.update({"length": frames, "fps": fps, "steps": 20})
    else:
        request.update({"steps": 28, "cfg": 7.0, "sampler": "dpmpp_2m", "scheduler": "karras"})
    manifest_digest = hashlib.sha256(
        json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "id": asset_id, "type": asset_type, "channels": _channels(row.get("channels")),
        "state": "draft_requires_owner_approval", "broker_endpoint": endpoint,
        "worker": "CRUCIBLE", "model": model, "request": request,
        "claim_ids": selected_claims, "source_asset_ids": selected_sources,
        "manifest_sha256": manifest_digest,
        "output_path": f"creative/{asset_id}.{'mp4' if asset_type == 'short_video' else 'png'}",
        "generated": False,
    }


def evaluate(data, now=None):
    if not isinstance(data, dict) or set(data) != {
            "allow_external_actions", "campaign", "brand_rules", "claims",
            "source_assets", "assets"}:
        raise ValueError("invalid creative brief schema")
    if data.get("allow_external_actions") is not False:
        raise ValueError("external-action boundary missing")
    campaign = data.get("campaign")
    if not isinstance(campaign, dict) or set(campaign) != {
            "id", "product", "audience", "objective"}:
        raise ValueError("invalid campaign schema")
    campaign_record = {key: _text(campaign.get(key), key, 500) for key in campaign}
    brand_rules = data.get("brand_rules")
    if not isinstance(brand_rules, list) or not brand_rules or len(brand_rules) > 30:
        raise ValueError("invalid brand rules")
    rules = [_text(rule, "brand rule", 500) for rule in brand_rules]
    claims = _claims(data.get("claims"))
    sources = _sources(data.get("source_assets"))
    assets = data.get("assets")
    if not isinstance(assets, list) or not assets or len(assets) > MAX_ASSETS:
        raise ValueError("assets missing or oversized")
    jobs, ids = [], set()
    claim_ids = {row["id"] for row in claims}
    source_ids = {row["id"] for row in sources}
    for row in assets:
        job = _asset_job(row, claim_ids=claim_ids, source_ids=source_ids)
        if job["id"] in ids:
            raise ValueError("duplicate media asset")
        ids.add(job["id"])
        jobs.append(job)
    return {
        "schema_version": 1,
        "bot_id": "creative_director",
        "state": "healthy",
        "mode": "approved_brief_draft_manifests",
        "observed_epoch": int(time.time() if now is None else now),
        "authority": "draft_media_provenance_and_claim_review",
        "campaign": campaign_record,
        "brand_rules": rules,
        "claims": claims,
        "source_assets": sources,
        "media_jobs": jobs,
        "approval_gates": {
            "generate_media": "required", "publish_or_upload": "required",
            "paid_ad_or_spend": "required", "person_likeness_or_voice": "required",
            "license_asset": "required", "unsupported_claim": "prohibited",
        },
        "media_generated": 0,
        "assets_published": 0,
        "external_uploads": 0,
        "paid_ads_started": 0,
        "spend_committed": 0,
        "likeness_uses": 0,
        "licenses_purchased": 0,
        "unsupported_claims": 0,
        "external_actions": 0,
    }


def waiting_report(now=None):
    report = {
        "schema_version": 1, "bot_id": "creative_director", "state": "healthy",
        "mode": "waiting_for_approved_creative_brief",
        "observed_epoch": int(time.time() if now is None else now),
        "authority": "draft_media_provenance_and_claim_review",
        "campaign": None, "brand_rules": [], "claims": [], "source_assets": [],
        "media_jobs": [], "approval_gates": {},
    }
    for key in (
        "media_generated", "assets_published", "external_uploads", "paid_ads_started",
        "spend_committed", "likeness_uses", "licenses_purchased",
        "unsupported_claims", "external_actions",
    ):
        report[key] = 0
    return report


def _read_input(path):
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError("approved creative brief is oversized")
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="/var/lib/orca-creative-input/approved-brief.json")
    parser.add_argument("--output", default="/var/lib/orca-creative-director/status.json")
    args = parser.parse_args()
    try:
        source = Path(args.input)
        report = evaluate(_read_input(source)) if source.exists() else waiting_report()
    except (OSError, ValueError, json.JSONDecodeError, TypeError) as exc:
        report = waiting_report()
        report.update({
            "state": "degraded", "mode": "invalid_approved_creative_brief",
            "error": type(exc).__name__,
        })
    target = Path(args.output)
    target.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o640)
    os.replace(temporary, target)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["state"] == "healthy" else 1


if __name__ == "__main__":
    raise SystemExit(main())
