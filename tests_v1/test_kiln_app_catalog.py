import ast
from pathlib import Path


def _app_ids():
    tree = ast.parse(Path("desktop/KILNStudio/kiln-studio.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "APP_IDS" for target in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("APP_IDS not found")


def test_kiln_catalog_covers_productive_non_core_apps_and_excludes_admin_surfaces():
    apps = _app_ids()
    assert {
        "chrome", "firefox", "files", "calculator", "editor", "kicad",
        "kicad_pcb_editor", "kicad_schematic_editor", "freecad",
        "libreoffice_writer", "libreoffice_calc", "document_scanner",
        "document_viewer", "image_viewer", "shotwell", "thunderbird", "videos",
    } <= set(apps)
    assert not {
        "terminal", "disks", "settings", "passwords", "software_updater",
        "network_settings", "remote_desktop", "torrent",
    } & set(apps)


def test_orca_chrome_wrapper_is_scoped_to_a_dedicated_profile():
    wrapper = Path("desktop/KILNStudio/orca-chrome").read_text(encoding="utf-8")
    assert ".local/share/orca-browser/profile" in wrapper
    assert "--no-first-run" in wrapper
    assert "http://*|https://*" in wrapper
    assert "--remote-debugging-port" not in wrapper
