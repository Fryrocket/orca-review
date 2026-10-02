import ast
from pathlib import Path
import re
import ipaddress

import pytest


def launcher_rules():
    source = Path("desktop/KILNStudio/kiln-studio.py").read_text()
    tree = ast.parse(source)
    nodes = [node for node in tree.body if
             isinstance(node, (ast.Import, ast.ImportFrom)) and
             (getattr(node, "module", "") == "urllib.parse" or
              isinstance(node, ast.Import) and all(item.name in {"re", "json", "ipaddress"} for item in node.names))
             or isinstance(node, ast.FunctionDef) and node.name in {"valid_web_url", "valid_browser_read_url", "validate_launch", "validate_browser_read_request"}
             or isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in {"APP_IDS", "BROWSER_READ_ACCEPTANCE_ORIGIN"} for t in node.targets)]
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
    method = source.split("    def _open_browser(self, uri, capture_request_id=None):", 1)[1].split("    def _decide_policy", 1)[0]
    assert "WebContext.new_ephemeral()" in method
    assert "register_script_message_handler" not in method
    assert "subprocess" not in source
    assert "new_from_filename" in source


def test_private_page_reader_has_strict_request_and_url_boundaries():
    rules = launcher_rules()
    request = {"id": "read-1", "action": "read_browser_page", "url": "https://example.com/"}
    assert rules["validate_browser_read_request"](request) == "https://example.com/"
    for uri in ("http://example.com/", "https://127.0.0.1/", "https://192.168.1.1/",
                "https://localhost/", "https://router.local/", "file:///etc/passwd"):
        with pytest.raises(ValueError):
            rules["validate_browser_read_request"]({**request, "url": uri})
    assert rules["validate_browser_read_request"](
        {**request, "url": "http://127.0.0.1:18799/acceptance"}) == "http://127.0.0.1:18799/acceptance"


def test_page_capture_is_bounded_untrusted_and_cannot_download_or_request_permissions():
    source = Path("desktop/KILNStudio/kiln-studio.py").read_text()
    method = source.split("    def _open_browser(self, uri, capture_request_id=None):", 1)[1].split(
        "    def _decide_policy", 1)[0]
    assert "WebContext.new_ephemeral()" in method
    assert "request.deny()" in method
    assert "download.cancel()" in method
    assert ".slice(0,50000)" in method
    assert "untrusted content" in method


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


def test_kiln_studio_is_fullscreen_without_modifying_gnome_shell():
    source = Path("desktop/KILNStudio/kiln-studio.py").read_text()
    assert "self.window.fullscreen()" in source
    assert 'self.set_accels_for_action("app.toggle-fullscreen", ["F11"])' in source
    assert "gnome-shell" not in source


def test_kiln_studio_recovers_when_gateway_starts_late():
    source = Path("desktop/KILNStudio/kiln-studio.py").read_text()
    assert "GLib.timeout_add_seconds(5, self._retry_studio)" in source
    assert "It will retry automatically." in source


def test_kiln_studio_autostarts_and_restarts_only_the_app():
    autostart = Path("desktop/KILNStudio/kiln-studio-autostart.desktop").read_text()
    installer = Path("desktop/KILNStudio/install.sh").read_text()
    assert "X-GNOME-Autostart-enabled=true" in autostart
    assert "X-GNOME-AutoRestart=true" in autostart
    assert "Exec=/home/fryrocket/.local/lib/kiln-studio/kiln-studio.py" in autostart
    assert "gnome-shell" not in autostart
    assert 'autostart_dir="${HOME}/.config/autostart"' in installer
    assert 'kiln-studio-autostart.desktop' in installer
