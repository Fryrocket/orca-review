from pathlib import Path


def test_action_center_is_a_first_class_non_technical_workspace():
    html = Path("orca/static/index.html").read_text()
    app = Path("orca/static/app.js").read_text()
    script = Path("orca/static/solo-operator.js").read_text()
    assert '<button data-view="solo-operator"><span>☷</span> Action Center</button>' in html
    assert '<section id="solo-operator" class="view">' in html
    assert "One quiet front door" in html
    assert "ORCASoloOperator?.load()" in app
    assert "/api/solo-operator/system" in script
    assert "External actions taken" in script
    assert "Do not send messages" in script
