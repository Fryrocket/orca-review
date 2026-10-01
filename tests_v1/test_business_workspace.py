from pathlib import Path
import re

import pytest

from orca.control_plane import ControlPlane
from orca.domain import JobStatus


def test_business_is_a_first_class_workspace_below_operations():
    source = Path("orca/static/index.html").read_text()
    nav = source.split('<nav class="primary-nav"', 1)[1].split("</nav>", 1)[0]
    assert nav.index('data-view="operations"') < nav.index('data-view="business"')
    assert '<section id="business" class="view">' in source
    assert '<button data-view="business"><span>◆</span> QuasarVolt</button>' in nav
    assert 'business: [\'QUASARVOLT SUPPLY\', \'Business\']' in Path("orca/static/app.js").read_text()


def test_business_uses_the_quasarvolt_working_brand():
    source = Path("orca/static/index.html").read_text()
    assert '<p class="eyebrow">QUASARVOLT SUPPLY</p>' in source
    assert 'QuasarVolt Works developing original boards' in source
    assert '<span class="business-state">WORKING BRAND</span>' in source


def test_bot_monitor_is_a_first_class_read_only_sidebar_workspace():
    source = Path("orca/static/index.html").read_text()
    app = Path("orca/static/app.js").read_text()
    launcher = Path("orca/static/launcher.js").read_text()
    assert '<button data-view="bot-monitor"><span>◉</span> Bot Monitor</button>' in source
    assert '<section id="bot-monitor" class="view">' in source
    assert 'Positions and live activity' in source
    assert 'Prepare bot report' in source
    assert "function renderBotMonitor()" in app
    assert "continuity_keeper" in app
    assert "state.role_catalog" in app
    assert "Do not change bot permissions, schedules, jobs, or services" in app
    assert "'bot monitor': 'bot-monitor'" in launcher


def test_business_covers_online_sales_lifecycle_and_office_apps():
    source = Path("orca/static/index.html").read_text()
    section = source.split('<section id="business" class="view">', 1)[1].split(
        '<section id="product-builder"', 1
    )[0]
    headings = set(re.findall(r"<h3>([^<]+)</h3>", section))
    assert headings == {
        "Market discovery", "Vendors", "Product discovery", "Products &amp; catalog",
        "Inventory", "Sales", "Customers", "Marketing", "Orders &amp; fulfillment",
        "Accounting", "Finance", "Documents", "AWS &amp; cloud", "Amazon seller",
        "Strategy &amp; KPIs", "Storefront &amp; channels", "Pricing", "Procurement",
        "Legal, tax &amp; compliance", "Analytics &amp; reporting", "Security &amp; risk",
        "People &amp; procedures", "Muse product scout", "Automations",
        "Launch Control", "Product Compliance", "Quality &amp; RMA", "Product Lifecycle",
        "Logistics &amp; Customs", "Marketplace Health", "Customer Support Desk",
        "Wholesale &amp; Partnerships", "Fraud &amp; Chargebacks", "Competitor Watch",
        "Experiment Lab", "Intellectual Property", "Daily Command Center",
        "Product Information Manager", "Demand &amp; Replenishment", "Cash &amp; Treasury",
        "Tax Operations", "Contracts Center", "Product Safety &amp; Recall",
        "Supplier Intelligence", "Manufacturing Planner", "Returns Recovery",
        "Warranty Reserve", "Localization", "Insurance &amp; Risk Transfer",
        "Data Governance", "Agent Control Room", "Business Simulator",
    }
    assert section.count("data-business-prompt=") == 104
    assert set(re.findall(r'data-launch-app="([a-z_]+)"', section)) == {
        "libreoffice", "libreoffice_writer", "libreoffice_calc", "libreoffice_draw",
        "libreoffice_impress", "libreoffice_math",
    }


def test_supplier_plan_records_prospects_without_claiming_contracts():
    source = Path("orca/static/index.html").read_text()
    section = source.split('<section class="panel supplier-plan"', 1)[1].split("</section>", 1)[0]
    assert all(name in section for name in ("Elecrow", "Makerfabs", "Seeed Studio"))
    assert section.count("APPROVED PROSPECT") == 3
    assert "No supplier goes live" in section
    assert "QuasarVolt sample shipment passes inspection" in section
    assert "Required legal markings stay visible" in section
    assert "Loose lithium batteries remain excluded" in section


def test_product_search_is_a_prominent_evidence_based_workspace():
    source = Path("orca/static/index.html").read_text()
    section = source.split('<section class="panel product-search"', 1)[1].split("</section>", 1)[0]
    assert "<h2>Product Search</h2>" in section
    assert all(step in section for step in (
        "Find demand", "Verify supply", "Model profit", "Check risk", "Validate cheaply",
    ))
    assert "source links and timestamps" in section
    assert "landed cost" in section
    assert "product compliance" in section
    assert "Do not scrape prohibited sources" in section
    assert 'data-business-site="muse"' in section


def test_muse_is_invoked_as_a_governed_orca_business_tool():
    source = Path("orca/static/index.html").read_text()
    card = source.split('<h3>Muse product scout</h3>', 1)[1].split('</article>', 1)[0]
    business = Path("orca/static/business.js").read_text()
    assert 'data-business-tool="muse"' in card
    assert "invoke Meta Muse as the product-research tool" in card
    assert "Cross-check important facts outside Muse" in card
    assert "claim direct Muse API access" in card
    assert "button.dataset.businessTool" in business
    assert "StudioLauncher.launch" in business


def test_advertising_creative_studio_uses_crucible_with_publish_approval():
    source = Path("orca/static/index.html").read_text()
    section = source.split('<h2>Advertising Creative Studio</h2>', 1)[1].split('</section>', 1)[0]
    assert all(value in section for value in (
        "CRUCIBLE locally", "text-to-video", "image-to-video", "small MP4 clips",
        "explicit approval before publishing", "Never fabricate reviews",
    ))


def test_business_records_route_libreoffice_drive_notion_and_tax_truthfully():
    source = Path("orca/static/index.html").read_text()
    section = source.split('<section class="panel business-records"', 1)[1].split("</section>", 1)[0]
    assert all(name in section for name in (
        "Writer + Google Docs", "Calc + Google Sheets", "Draw", "Impress + Google Slides",
        "LibreOffice Math", "Calc + Writer", "ERPNext",
    ))
    assert "update the QuasarVolt Document Register" in section
    assert "no LibreTax application is installed" in section
    assert "not a tax-filing or professional-advice replacement" in section
    assert 'data-business-site="google_drive"' in section
    assert 'data-business-site="erpnext"' in section
    assert "Do not install, expose, create credentials, migrate data" in section


def test_business_record_sites_are_fixed_and_governed():
    business = Path("orca/static/business.js").read_text()
    launcher = Path("orca/static/launcher.js").read_text()
    folder = "https://drive.google.com/drive/folders/1gDmk8L_NyVi6Hc7kSjIAQyhiAAyYOYl_"
    assert folder in business
    assert folder in launcher
    assert "https://erpnext.com/" in business
    assert "https://erpnext.com/" in launcher


def test_locked_agentic_systems_stack_is_staged_and_governed():
    source = Path("orca/static/index.html").read_text()
    section = source.split(
        '<section class="panel business-systems" aria-label="QuasarVolt agentic business systems stack">',
        1,
    )[1].split("</section>", 1)[0]
    assert all(name in section for name in (
        "Paperless-ngx", "ERPNext", "Monthly Close Agent", "Receipt &amp; Invoice Agent",
        "W-9 &amp; 1099 Center", "Documenso", "Metabase", "Audit Room",
        "Backup &amp; Recovery Vault", "Secrets Vault",
    ))
    assert section.count("data-business-prompt=") == 11
    assert "No services installed, exposed, credentialed, or connected yet" in section
    assert "Google Drive as the collaboration repository" in section
    assert "Notion as the operating map" in section
    assert "Do not install, expose, create credentials" in section
    assert "ORCA records references, never secret values" in section


def test_locked_stack_sites_use_fixed_official_urls():
    business = Path("orca/static/business.js").read_text()
    launcher = Path("orca/static/launcher.js").read_text()
    for url in (
        "https://docs.paperless-ngx.com/", "https://docs.documenso.com/",
        "https://www.metabase.com/docs/latest/", "https://erpnext.com/",
    ):
        assert url in business
        assert url in launcher


def test_multichannel_plan_includes_platforms_and_approval_boundaries():
    source = Path("orca/static/index.html").read_text()
    section = source.split('<section class="panel channel-plan"', 1)[1].split("</section>", 1)[0]
    assert all(name in section for name in ("Shopify", "Amazon Seller", "eBay", "Alibaba.com", "Temu", "AWS"))
    assert "AWS used only as the secure infrastructure layer" in section
    assert "Require my explicit approval" in section
    assert "sandbox or dry-run mode" in section


def test_sales_sites_are_fixed_and_use_governed_browser_launcher():
    business = Path("orca/static/business.js").read_text()
    launcher = Path("orca/static/launcher.js").read_text()
    for url in (
        "https://accounts.shopify.com/store-login", "https://sellercentral.amazon.com/",
        "https://www.ebay.com/sh/ovw", "https://seller.alibaba.com/",
        "https://seller.temu.com/", "https://console.aws.amazon.com/",
    ):
        assert url in business
        assert url in launcher
    assert "StudioLauncher.launch({kind: 'app', target: 'browser', url})" in business


def test_organic_growth_covers_every_channel_without_paid_or_deceptive_tactics():
    source = Path("orca/static/index.html").read_text()
    section = source.split('<section class="panel growth-plan"', 1)[1].split("</section>", 1)[0]
    assert all(name in section for name in (
        "Website &amp; SEO", "Shopify", "Amazon", "eBay", "Alibaba.com", "Temu",
        "Projects &amp; community", "AWS",
    ))
    assert "without paid advertising" in section
    assert "Require my explicit approval before publishing" in section
    assert "Never use fake reviews" in section
    assert "draft-only mode" in section


def test_business_workflows_stage_tracked_jobs_without_auto_submitting():
    source = Path("orca/static/business.js").read_text()
    app = Path("orca/static/app.js").read_text()
    assert "Operate agentically inside the approved scope" in source
    assert "Continue until the requested outcome is complete" in source
    assert "Do not stop merely to explain what could be done" in source
    assert "Pause for explicit approval" in source
    assert "show('studio')" in source
    assert "selectMode('auto')" in source
    assert "input.value = `${agenticBusinessContract}" in source
    assert "requestSubmit" not in source
    assert "ORCABusinessWorkflow.stage(workflow)" in source
    assert "ORCABusinessWorkflow?.take?.(prompt.trim())" in app
    assert "postMutation('/api/business/workflows'" in app
    assert "business_job_id" in app


def test_business_workflow_job_has_fixed_safe_scope_and_result_evidence():
    control = ControlPlane()
    job = control.start_business_workflow(
        workflow_id="business-01-market-discovery",
        title="Market discovery",
        requested_by="fry",
    )
    assert job.status is JobStatus.RUNNING
    assert job.assigned_to == "orca"
    assert job.lane == "orca"
    assert job.task_type == "business_workflow"
    assert job.action.kind == "analyze"
    assert job.action.resource == "business-workflow:business-01-market-discovery"
    assert job.level.name == "R0"
    assert job.approval_id is None

    reviewed = control.record_business_workflow_result(
        job.id, success=True, result_sha256="a" * 64,
        result_bytes=128, routed_mode="reason",
    )
    assert reviewed.status is JobStatus.REVIEW
    assert reviewed.reviewer == "quench"
    events = control.evidence.list(correlation_id=job.correlation_id, limit=20)
    assert any(event["kind"] == "business.workflow.result" for event in events)
    assert any(event["kind"] == "job.review_requested" for event in events)


def test_business_workflow_rejects_client_controlled_or_malformed_identity():
    control = ControlPlane()
    with pytest.raises(ValueError, match="workflow id"):
        control.start_business_workflow(
            workflow_id="../../publish", title="Bad", requested_by="fry")


def test_business_explains_the_agentic_execution_loop():
    source = Path("orca/static/index.html").read_text()
    section = source.split('<section class="panel agentic-business"', 1)[1].split("</section>", 1)[0]
    assert "Agentic by default" in section
    assert all(stage in section for stage in ("Observe", "Plan", "Act", "Verify", "Record"))
    assert "Business workflows do the safe work" in section
    assert "STOP FOR YOU" in section


def test_legal_connections_accounting_and_final_simulation_are_first_class():
    source = Path("orca/static/index.html").read_text()
    assert "LEGAL COMMAND CENTER" in source
    assert "Legal, contracts &amp; compliance" in source
    assert "CONNECTIONS &amp; AI PATHS" in source
    assert "Drive · Notion · Linear" in source
    assert "ChatGPT Finances · Plaid" in source
    assert "ORCA never receives bank login credentials" in source
    assert "Codex · Qwen · QUENCH · CRUCIBLE" in source
    assert "ORCA Executive Orchestrator" in source
    assert "Fry remains the sole human authority" in source
    assert "Credential &amp; remote-access broker" in source
    assert "bots cannot enumerate or export the keychain" in source
    assert "SMITH is retired" in source
    assert "TEMPER · FORGE · Hailo-8 · MQTT" in source
    assert "ACCOUNTING CONTROL CENTER" in source
    assert "FINAL ACCEPTANCE PLAN" in source
    assert "Concept-to-sale business simulation" in source
    assert "disposable synthetic records" in source


def test_budget_center_and_finances_handoff_are_read_only_and_truthful():
    source = Path("orca/static/index.html").read_text()
    business = Path("orca/static/business.js").read_text()
    launcher = Path("orca/static/launcher.js").read_text()
    assert "BUDGET CONTROL CENTER" in source
    assert "Budget, cash &amp; runway" in source
    assert "Operating budget" in source
    assert "Cash flow &amp; runway" in source
    assert "Budget vs. actual" in source
    assert "read-only ChatGPT Finances context" in source
    assert "ChatGPT Finances cannot move money" in source
    assert "chatgpt_finances: 'https://chatgpt.com/'" in business
    assert "'chatgpt finances': 'https://chatgpt.com/'" in launcher


def test_business_dashboard_uses_live_canonical_record_counts():
    source = Path("orca/static/index.html").read_text()
    app = Path("orca/static/app.js").read_text()
    assert 'id="business-record-count"' in source
    assert "Object.values(state.business?.counts || {})" in app
    assert "recordNode.textContent = records" in app


def test_business_operating_system_covers_controls_and_approval_boundaries():
    source = Path("orca/static/index.html").read_text()
    section = source.split('<section class="panel business-operations"', 1)[1].split("</section>", 1)[0]
    assert section.count('class="business-card"') == 13
    assert all(name in section for name in (
        "Launch Control", "Product Compliance", "Quality &amp; RMA", "Product Lifecycle",
        "Logistics &amp; Customs", "Marketplace Health", "Customer Support Desk",
        "Wholesale &amp; Partnerships", "Fraud &amp; Chargebacks", "Competitor Watch",
        "Experiment Lab", "Intellectual Property", "Daily Command Center",
    ))
    assert "Never claim a filing, certification, test, contract, refund, recall" in section
    assert "Require my explicit approval" in section
    assert "AUTO</b> Read, reconcile, calculate, draft, prioritize, document, alert" in section
    assert "APPROVAL</b> Commit, publish, contact, buy, refund, file, certify, recall, delete" in section


def test_advanced_operations_are_connected_agentic_control_rooms():
    source = Path("orca/static/index.html").read_text()
    section = source.split('<section class="panel business-expansion"', 1)[1].split("</section>", 1)[0]
    expected = (
        "Product Information Manager", "Demand &amp; Replenishment", "Cash &amp; Treasury",
        "Tax Operations", "Contracts Center", "Product Safety &amp; Recall",
        "Supplier Intelligence", "Manufacturing Planner", "Returns Recovery",
        "Warranty Reserve", "Localization", "Insurance &amp; Risk Transfer",
        "Data Governance", "Agent Control Room", "Business Simulator",
    )
    assert section.count('class="business-card"') == 15
    assert all(name in section for name in expected)
    assert "shared identifiers, sources of truth, owners, timestamps, confidence, evidence links" in section
    assert "SHARED TRUTH" in section
    assert "HUMAN AUTHORITY" in section


def test_muse_uses_a_fixed_official_site_and_the_governed_browser_launcher():
    business = Path("orca/static/business.js").read_text()
    launcher = Path("orca/static/launcher.js").read_text()
    assert "https://ai.meta.com/muse/" in business
    assert "StudioLauncher.launch({kind: 'app', target: 'browser', url})" in business
    assert "muse: 'https://ai.meta.com/muse/'" in launcher
