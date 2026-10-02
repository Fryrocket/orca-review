from pathlib import Path


def test_manual_requests_export_through_kiln_libreoffice():
    app = Path("orca/static/app.js").read_text(encoding="utf-8")
    gateway = Path("deploy/orca_studio_gateway.py").read_text(encoding="utf-8")
    converter = Path("deploy/kiln/orca_manual_converter.py").read_text(encoding="utf-8")
    assert "function wantsManualDocument" in app
    assert "await exportManualDocument(prompt.trim(), result.summary, item)" in app
    assert "fetch('/api/manuals/export'" in app
    assert "Download verified PDF" in app
    assert "Download editable LibreOffice document" in app
    assert '"/api/manuals/export"' in gateway
    assert '"/usr/bin/libreoffice"' in converter
    assert "--headless" in converter
    assert "request_manual_conversion" in gateway
    assert "_authenticated_local_request" in gateway


def test_manual_export_is_not_triggered_by_explanations_or_negation():
    app = Path("orca/static/app.js").read_text(encoding="utf-8")
    assert "don't|do not|never" in app
    assert "if (!wantsManualDocument(prompt)) return null" in app
