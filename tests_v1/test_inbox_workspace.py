from pathlib import Path


def test_inbox_is_a_first_class_private_read_only_workspace():
    html = Path("orca/static/index.html").read_text()
    app = Path("orca/static/app.js").read_text()
    script = Path("orca/static/inbox.js").read_text()
    assert '<button data-view="inbox"><span>✉</span> Inbox</button>' in html
    assert '<section id="inbox" class="view">' in html
    assert "Raw bodies and attachments are not stored" in html
    assert "Mailbox actions</span><strong>0</strong>" in html
    assert "inbox: ['PRIVATE COMMUNICATIONS', 'Inbox']" in app
    assert "globalThis.ORCAInbox?.load()" in app
    assert "/api/inbox" in script
    assert "/api/inbox/import" in script
    assert "/api/business/muse/email-handoff" in script
    assert "textContent" in script
    assert "innerHTML" in script and "safe(message.subject)" in script
