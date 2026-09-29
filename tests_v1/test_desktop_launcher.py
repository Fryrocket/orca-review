import ast
from pathlib import Path
import re

import pytest


def launcher_rules():
    source = Path("desktop/KILNStudio/kiln-studio.py").read_text()
    tree = ast.parse(source)
    nodes = [node for node in tree.body if
             isinstance(node, (ast.Import, ast.ImportFrom)) and
             (getattr(node, "module", "") == "urllib.parse" or
              isinstance(node, ast.Import) and all(item.name in {"re", "json"} for item in node.names))
             or isinstance(node, ast.FunctionDef) and node.name in {"valid_web_url", "validate_launch"}
             or isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "APP_IDS" for t in node.targets)]
    scope = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "launcher_rules", "exec"), scope)
    return scope


@pytest.mark.parametrize("app", ["browser", "firefox", "files", "calculator", "editor",
    "kicad", "kicad_image_converter", "kicad_pcb_calculator", "kicad_pcb_editor",
    "kicad_schematic_editor", "kicad_gerber_viewer", "freecad",
    "libreoffice", "libreoffice_writer", "libreoffice_calc",
    "libreoffice_draw", "libreoffice_impress", "libreoffice_math"])
def test_allowed_apps(app):
    assert launcher_rules()["validate_launch"]({"id": "test-1", "app": app, "url": ""}) == (app, "")


@pytest.mark.parametrize("uri", ["javascript:alert(1)", "file:///tmp/a", "https://user:pw@example.com",
                                 "https://example.com:99999", "https://example.com\\evil", "https://example.com\n"])
def test_rejects_non_web_or_ambiguous_urls(uri):
    assert not launcher_rules()["valid_web_url"](uri)


@pytest.mark.parametrize("payload", [
    {"id": "a", "app": "terminal", "url": ""},
    {"id": "a", "app": "files", "url": "https://example.com"},
    {"id": "a", "app": "calculator", "url": "", "command": "sh"},
    {"id": "a", "app": [], "url": ""},
    {"id": "a", "app": "browser", "url": "file:///etc/passwd"},
])
def test_launch_envelope_restricted(payload):
    with pytest.raises(ValueError):
        launcher_rules()["validate_launch"](payload)


def test_external_browser_has_no_privileged_manager():
    source = Path("desktop/KILNStudio/kiln-studio.py").read_text()
    method = source.split("    def _open_browser(self, uri):", 1)[1].split("    def _decide_policy", 1)[0]
    assert "WebContext.new_ephemeral()" in method
    assert "register_script_message_handler" not in method
    assert "subprocess" not in source
    assert "new_from_filename" in source


def test_project_artifacts_are_confined_to_orca_project_root():
    source = Path("desktop/KILNStudio/kiln-studio.py").read_text()
    method = source.split("def validate_artifact_request(payload):", 1)[1].split("\n\n\nclass KilnStudio", 1)[0]
    assert "PROJECT_ROOT.resolve()" in method
    assert "root not in path.parents" in method
    assert '"board": {".kicad_pcb"}' in method
    assert '"pdf": {".pdf"}' in method


def test_engineering_app_buttons_are_only_fixed_allowlisted_ids():
    source = Path("orca/static/index.html").read_text()
    buttons = set(re.findall(r'data-launch-app="([a-z_]+)"', source))
    assert buttons == {
        "kicad", "kicad_image_converter", "kicad_pcb_calculator",
        "kicad_pcb_editor", "kicad_schematic_editor", "kicad_gerber_viewer", "freecad", "libreoffice",
        "libreoffice_writer", "libreoffice_calc", "libreoffice_draw",
        "libreoffice_impress", "libreoffice_math",
    }
    app_ids = launcher_rules()["APP_IDS"]
    assert buttons <= set(app_ids)
    assert all("/" not in filename and filename.endswith(".desktop")
               for filename in app_ids.values())


def test_kicad10_launchers_are_fixed_to_the_installed_bundle():
    launcher_dir = Path("desktop/KILNStudio/kicad10")
    launchers = sorted(launcher_dir.glob("*.desktop"))
    assert len(launchers) == 6
    for launcher in launchers:
        text = launcher.read_text()
        assert "Exec=/home/fryrocket/.local/lib/kiln-studio/kicad10-launch" in text
        assert "Terminal=false" in text
    wrapper = Path("desktop/KILNStudio/kicad10-launch").read_text()
    assert "umask 077" in wrapper
    assert "exec /opt/kicad/10.0.6/kicad-10.0.6-x86_64.AppImage" in wrapper


def test_chat_cad_drafts_are_bounded_before_native_save():
    source = Path("desktop/KILNStudio/kiln-studio.py").read_text()
    method = source.split("def validate_cad_draft_request(payload):", 1)[1].split(
        "\n\n\ndef desktop_app_info", 1)[0]
    assert 'set(payload) != {"id", "action", "filename", "content"}' in method
    assert 'payload["action"] != "save_cad_draft"' in method
    assert '1_000_000' in method
    assert 'startswith("(kicad_pcb ")' in method
    assert 'PROJECT_ROOT / "Chat CAD"' in source
