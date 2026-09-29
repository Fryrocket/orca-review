"""Build the dated owner checklist with the bundled document Python runtime.

Requires reportlab, pypdf and pdfplumber for artifact creation/validation only;
these are not ORCA runtime dependencies. Edit the dated content for a new review.
"""

from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    Flowable, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer,
    Table, TableStyle,
)
from pypdf import PdfReader
import pdfplumber


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output/pdf/ORCA_action_checklist_2026-09-23.pdf"
NAVY = colors.HexColor("#17333F")
TEAL = colors.HexColor("#087D80")
MUTED = colors.HexColor("#52636C")
PALE = colors.HexColor("#EEF6F6")
LINE = colors.HexColor("#D5DFE3")

BODY = ParagraphStyle(
    "Body", fontName="Helvetica", fontSize=10, leading=14,
    textColor=NAVY, spaceAfter=5, alignment=TA_LEFT,
)
SMALL = ParagraphStyle(
    "Small", parent=BODY, fontSize=8.7, leading=12, textColor=MUTED,
)
TITLE = ParagraphStyle(
    "Title", parent=BODY, fontName="Helvetica-Bold", fontSize=25,
    leading=29, spaceAfter=8,
)
SECTION = ParagraphStyle(
    "Section", parent=BODY, fontName="Helvetica-Bold", fontSize=11,
    leading=15, textColor=TEAL, spaceBefore=12, spaceAfter=7,
)


def para(text, style=BODY):
    return Paragraph(text, style)


class CheckBox(Flowable):
    def __init__(self):
        super().__init__()
        self.width, self.height = 13, 14

    def draw(self):
        self.canv.setStrokeColor(TEAL)
        self.canv.setLineWidth(1)
        self.canv.rect(0, 2, 10, 10)


def check(title, detail):
    row = Table(
        [[CheckBox(), para(f"<b>{escape(title)}</b><br/>{escape(detail)}")]],
        colWidths=[23, 481], hAlign="LEFT",
    )
    row.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return KeepTogether([row])


def note(text):
    box = Table([[para(text)]], colWidths=[504])
    box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE),
        ("BOX", (0, 0), (-1, -1), 0.5, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return box


def footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(LINE)
    canvas.line(48, 42, 564, 42)
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(48, 28, "ORCA / LOCAL REBUILD REVIEW / 23 SEP 2026")
    canvas.drawRightString(564, 28, f"{doc.page} / 2")
    canvas.restoreState()


def build():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUTPUT), pagesize=(8.5 * inch, 11 * inch),
        leftMargin=48, rightMargin=48, topMargin=44, bottomMargin=56,
        title="ORCA - Owner action checklist and review results",
        author="Codex consultant", subject="Local ORCA review, 2026-09-23",
    )
    story = [
        para("ORCA / OWNER CHECKLIST", SECTION),
        para("Your next actions", TITLE),
        para("Prepared for Fry | September 23, 2026", SMALL),
        Spacer(1, 8),
        note("<b>Local result: 355 tests passed.</b> The review fixed defects covered by "
             "23 new regression cases. This is not production acceptance."),
        para("NOW - INPUT OR ACCESS", SECTION),
        check("1. Locate the '-266' display, if it still appears.",
              "Send its screenshot or exact command/output. The fresh baseline had no "
              "failures; STATE's 266 is a historical passing-test count."),
        check("2. Make a browser available for visual testing.",
              "Connect a browser in this Codex session so desktop and phone-size "
              "dashboard, approval, and Resume flows can be checked on screen."),
        check("3. Arrange independent Claude / QUENCH review.",
              "Give the reviewer the local changes and CODE_REVIEW_2026-09-23.md. "
              "Codex authored these fixes, so this review does not count as independent."),
        para("BEFORE LIVE ROLLOUT - NOT REQUIRED TO KEEP CODING", SECTION),
        check("4. Confirm the service host and hardware availability.",
              "Confirm where ORCA should run and when ANVIL, FORGE, KILN, EMBER, and "
              "TEMPER is available for live checks using existing approved access."),
        check("5. Confirm safe credential provisioning.",
              "Provide the approved secret-store reference, never a key in chat or "
              "documents. Replace exposed credentials before enabling providers."),
        check("6. Confirm restore inputs and physical backup issues.",
              "Confirm secure coverage for Compose, .env, and /srv/vault. Verify the "
              "current status of off-site backup, WD replacement, and UPS concerns "
              "carried in STATE; older notes are not a fresh hardware check."),
        check("7. Approve the specific release only after acceptance.",
              "Review the named version, independent findings, live recovery evidence, "
              "and rollback steps. No deployment, removal, or cloud-spend action was taken."),
        PageBreak(),
        para("ORCA / REVIEW SNAPSHOT", SECTION),
        para("What passed. What remains.", TITLE),
        para("Local working tree | agent/orca-rebuild-v1 | September 23, 2026", SMALL),
        Spacer(1, 9),
    ]

    rows = [
        ["CHECK", "RESULT"],
        ["Rebuilt control plane + retained legacy tests", "355 passed (112 + 243)"],
        ["New regression cases reproduced, then fixed", "23 cases"],
        ["Python compilation / both JavaScript syntax checks", "Passed"],
        ["Fresh-install / synthetic-state recovery drill", "Passed; 112 tests"],
        ["Rendered browser / independent review / live fleet", "Not yet verified"],
    ]
    table = Table(
        [[para(escape(cell), SMALL) for cell in row] for row in rows],
        colWidths=[324, 180], hAlign="LEFT",
    )
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PALE),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story += [table, para("FIXES COMPLETED IN THIS REVIEW", SECTION)]
    fixes = [
        ("Approvals and jobs", "Pause/resume preserves approvals and terminal states; "
         "read-only ORCA/QUENCH work can finish with a distinct reviewer."),
        ("Secrets and configuration", "Named credential fields redact even arbitrary "
         "values; permission, cloud-approval, and cost-cap inputs are stricter."),
        ("Fleet and accounting", "Same-key enrollment retains replay protection; "
         "shared SQLite cost/control operations use the same lock."),
        ("Legacy safety and recovery", "LAN binds require configured authentication; "
         "cost data is validated; supplied event buses and malformed saved metadata "
         "are handled correctly."),
        ("Legacy approval form", "Loopback/Host/route checks, per-prompt CSRF tokens, "
         "body limits, and serialized prompt handling protect submissions."),
    ]
    for title, detail in fixes:
        story.append(para(f"<b>{title}.</b> {detail}", SMALL))
    story += [para("ENGINEERING STILL OWNS THESE ITEMS", SECTION)]
    for item in [
        "Real bot runners, provider-specific integrations, local-model quality tests, "
        "and end-to-end cancellation/error handling.",
        "Per-identity authentication before remote/multi-user control; reviewed fleet "
        "transport, key lifecycle, and live reboot/reconnect testing.",
        "Live security advisory/provenance checks, actual alerts, stronger external "
        "evidence anchoring, and approved-release/secret restoration proof.",
    ]:
        story.append(para("- " + item, SMALL))
    story += [Spacer(1, 5), note(
        "<b>Deployment stays off.</b> Connector writes, remote execution, autonomous "
        "bot runtimes, and cloud spending remain disabled. The recovery drill used "
        "synthetic state; it did not restore production services or secrets."
    ), Spacer(1, 9), para(
        "Evidence in docs/: CODE_REVIEW_2026-09-23.md; "
        "RECOVERY_DRILL_2026-09-23.json; STATE_v11_upload.md. "
        "Recovery completed 21:12 UTC. Full review contains commands and limitations.", SMALL
    )]
    doc.build(story, onFirstPage=footer, onLaterPages=footer)

    reader = PdfReader(OUTPUT)
    assert len(reader.pages) == 2, f"Unexpected page count: {len(reader.pages)}"
    extracted = "\n".join(page.extract_text() for page in reader.pages)
    for expected in ("Your next actions", "7. Approve", "355", "112 + 243", "23 cases"):
        assert expected in extracted, f"Missing PDF content: {expected}"
    with pdfplumber.open(OUTPUT) as pdf:
        for page in pdf.pages:
            for word in page.extract_words():
                assert 47 <= word["x0"] < word["x1"] <= 565, word
                assert 20 <= word["top"] < word["bottom"] <= 772, word
    print(f"Verified {len(reader.pages)} pages: {OUTPUT}")


if __name__ == "__main__":
    build()
