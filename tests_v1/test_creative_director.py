import sys
from pathlib import Path

import pytest


repository = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repository / "deploy" / "forge"))
from orca_creative_director import evaluate, waiting_report


def creative_brief():
    digest = "a" * 64
    return {
        "allow_external_actions": False,
        "campaign": {
            "id": "guardian-launch", "product": "QuasarVolt Pi 5 Guardian HAT",
            "audience": "Pi 5 operators", "objective": "Explain resilient local operation",
        },
        "brand_rules": [
            "Use QuasarVolt working-brand styling.",
            "Keep board proportions and visible connectors truthful.",
        ],
        "claims": [{
            "id": "claim-watchdog", "type": "technical",
            "text": "Includes an independent watchdog design path.",
            "evidence_url": "https://evidence.invalid/guardian/requirements",
        }],
        "source_assets": [{
            "id": "board-render", "rights": "owned",
            "reference": "drive://quasarvolt/guardian/render-v1.png", "sha256": digest,
        }],
        "assets": [
            {
                "id": "hero-square", "type": "product_image",
                "channels": ["website", "shopify", "amazon"],
                "prompt": "A truthful studio product view of the QuasarVolt Guardian HAT.",
                "negative_prompt": "watermark, invented connector, distorted board",
                "width": 1024, "height": 1024, "seed": 12001,
                "claim_ids": ["claim-watchdog"], "source_asset_ids": ["board-render"],
            },
            {
                "id": "launch-clip", "type": "short_video",
                "channels": ["website", "temu"],
                "prompt": "Slow camera arc around the truthful Guardian HAT render.",
                "negative_prompt": "text, watermark, invented connector, flicker",
                "width": 832, "height": 480, "frames": 73, "fps": 24,
                "seed": 12002, "claim_ids": [], "source_asset_ids": ["board-render"],
            },
        ],
    }


def test_creative_brief_stages_reproducible_crucible_manifests_only():
    report = evaluate(creative_brief(), now=1000)
    image, video = report["media_jobs"]
    assert report["state"] == "healthy"
    assert image["broker_endpoint"] == "/generate"
    assert image["model"] == "sd_xl_base_1.0.safetensors"
    assert image["request"]["seed"] == 12001
    assert len(image["manifest_sha256"]) == 64
    assert video["broker_endpoint"] == "/video/generate"
    assert video["model"] == "wan2.2_ti2v_5B_fp16.safetensors"
    assert video["request"]["length"] == 73
    assert all(job["worker"] == "CRUCIBLE" and not job["generated"]
               for job in report["media_jobs"])


def test_provenance_claims_and_rights_are_retained_for_review():
    report = evaluate(creative_brief(), now=1000)
    assert report["claims"][0]["review_state"] == "evidence_attached_requires_review"
    assert report["source_assets"][0]["rights_review_state"] == "declared_requires_review"
    assert report["media_jobs"][0]["claim_ids"] == ["claim-watchdog"]
    assert report["media_jobs"][0]["source_asset_ids"] == ["board-render"]
    assert report["media_jobs"][0]["state"] == "draft_requires_owner_approval"


def test_every_consequential_media_action_is_gated_and_zero():
    report = evaluate(creative_brief(), now=1000)
    assert report["approval_gates"]["unsupported_claim"] == "prohibited"
    assert set(report["approval_gates"].values()) == {"required", "prohibited"}
    for key in (
        "media_generated", "assets_published", "external_uploads", "paid_ads_started",
        "spend_committed", "likeness_uses", "licenses_purchased",
        "unsupported_claims", "external_actions",
    ):
        assert report[key] == 0


def test_unlicensed_sources_and_unsupported_claims_fail_closed():
    value = creative_brief()
    value["source_assets"][0]["rights"] = "unknown"
    with pytest.raises(ValueError, match="unlicensed"):
        evaluate(value, now=1000)
    value = creative_brief()
    value["claims"][0]["evidence_url"] = "http://untrusted.invalid/evidence"
    with pytest.raises(ValueError, match="HTTPS"):
        evaluate(value, now=1000)
    value = creative_brief()
    value["claims"][0]["type"] = "testimonial"
    with pytest.raises(ValueError, match="prohibited"):
        evaluate(value, now=1000)


def test_unknown_references_duplicates_and_unsafe_media_settings_fail_closed():
    value = creative_brief()
    value["assets"][0]["claim_ids"] = ["missing"]
    with pytest.raises(ValueError, match="unknown"):
        evaluate(value, now=1000)
    value = creative_brief()
    value["assets"][1]["id"] = "hero-square"
    with pytest.raises(ValueError, match="duplicate media"):
        evaluate(value, now=1000)
    value = creative_brief()
    value["assets"][1]["frames"] = 240
    with pytest.raises(ValueError, match="timing"):
        evaluate(value, now=1000)


def test_secret_shaped_text_and_external_permission_fail_closed():
    value = creative_brief()
    value["assets"][0]["prompt"] = "password=do-not-log-this"
    with pytest.raises(ValueError, match="secret-shaped"):
        evaluate(value, now=1000)
    value = creative_brief()
    value["allow_external_actions"] = True
    with pytest.raises(ValueError, match="external-action boundary"):
        evaluate(value, now=1000)


def test_waiting_state_is_truthful_and_inert():
    report = waiting_report(now=1000)
    assert report["state"] == "healthy"
    assert report["mode"] == "waiting_for_approved_creative_brief"
    assert report["media_jobs"] == []
    assert report["external_actions"] == 0


def test_role_contract_is_active_but_cannot_publish_or_spend():
    from orca.roles import ROLE_CATALOG

    role = ROLE_CATALOG["creative_director"]
    assert role.active is True
    assert set(role.authority) == {
        "stage_media_job", "inspect_output", "prepare_campaign_asset"
    }
    assert {
        "publish", "run_paid_ad", "make_unverified_claim", "use_unlicensed_asset",
        "approve",
    } <= set(role.prohibited)
    assert role.activation_gate == "draft_media_provenance_and_claim_review_accepted_20261001"
