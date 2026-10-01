from pathlib import Path


def test_communications_hub_is_first_class_and_owner_reviewed():
    html = Path("orca/static/index.html").read_text()
    app = Path("orca/static/app.js").read_text()
    script = Path("orca/static/communications.js").read_text()
    assert '<button data-view="communications"><span>◫</span> Communications</button>' in html
    assert '<section id="communications" class="view">' in html
    assert "Customer and vendor timelines" in html
    assert "Calendar candidates" in html
    assert "LINKS + FILES BLOCKED" in html
    assert "Communications Hub" in app
    assert "globalThis.ORCACommunications?.load()" in app
    assert "/api/communications" in script
    assert "textContent" in script
    assert "safe(task.subject)" in script
