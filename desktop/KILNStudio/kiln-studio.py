#!/usr/bin/env python3
"""Native KILN Studio shell for the KILN Ubuntu desktop."""

from urllib.parse import urlparse
import ipaddress
import json
from pathlib import Path
import re

from project_builder import PROJECT_ROOT, create_project

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("WebKit2", "4.0")

from gi.repository import Gdk, Gio, GLib, Gtk, WebKit2  # noqa: E402


STUDIO_URL = "http://127.0.0.1:8788/"
STUDIO_ORIGIN = ("http", "127.0.0.1", 8788)
BROWSER_READ_ACCEPTANCE_ORIGIN = ("http", "127.0.0.1", 18799)
APP_IDS = {
    "chrome": "orca-chrome.desktop",
    "firefox": "firefox.desktop",
    "files": "org.gnome.Nautilus.desktop",
    "calculator": "org.gnome.Calculator.desktop",
    "editor": "org.gnome.gedit.desktop",
    "kicad": "org.kicad.kicad10.desktop",
    "kicad_image_converter": "org.kicad.bitmap2component10.desktop",
    "kicad_pcb_calculator": "org.kicad.pcbcalculator10.desktop",
    "kicad_pcb_editor": "org.kicad.pcbnew10.desktop",
    "kicad_schematic_editor": "org.kicad.eeschema10.desktop",
    "kicad_gerber_viewer": "org.kicad.gerbview10.desktop",
    "freecad": "freecad.desktop",
    "libreoffice": "libreoffice-startcenter.desktop",
    "libreoffice_writer": "libreoffice-writer.desktop",
    "libreoffice_calc": "libreoffice-calc.desktop",
    "libreoffice_draw": "libreoffice-draw.desktop",
    "libreoffice_impress": "libreoffice-impress.desktop",
    "libreoffice_math": "libreoffice-math.desktop",
    "archive_manager": "org.gnome.FileRoller.desktop",
    "calendar": "org.gnome.Calendar.desktop",
    "characters": "org.gnome.Characters.desktop",
    "chatbox": "xyz.chatboxapp.app.desktop",
    "cheese": "org.gnome.Cheese.desktop",
    "document_scanner": "simple-scan.desktop",
    "document_viewer": "org.gnome.Evince.desktop",
    "fonts": "org.gnome.font-viewer.desktop",
    "image_viewer": "org.gnome.eog.desktop",
    "power_statistics": "org.gnome.PowerStats.desktop",
    "rhythmbox": "rhythmbox.desktop",
    "shotwell": "shotwell.desktop",
    "thunderbird": "thunderbird.desktop",
    "todo": "org.gnome.Todo.desktop",
    "videos": "org.gnome.Totem.desktop",
    "help": "yelp.desktop",
}
LOCAL_APPS = {
    "chrome",
    "kicad", "kicad_image_converter", "kicad_pcb_calculator",
    "kicad_pcb_editor", "kicad_schematic_editor", "kicad_gerber_viewer",
}
HEADER_CSS = b"""
headerbar#kiln-header, headerbar#kiln-header:backdrop {
 background-image:none; background-color:#0b211a; color:#edf7f3;
 border-bottom:1px solid #213c34; box-shadow:none;
}
headerbar#kiln-header label {color:#edf7f3;}
headerbar#kiln-header button {background-image:none; background-color:transparent;
 color:#edf7f3; border-color:transparent; box-shadow:none; text-shadow:none;}
headerbar#kiln-header button:hover {background-color:#193c30;}
"""


def valid_web_url(uri):
    if not isinstance(uri, str) or len(uri) > 2048 or re.search(r"[\s\\]", uri):
        return False
    try:
        parsed = urlparse(uri)
        return (parsed.scheme in {"http", "https"} and bool(parsed.hostname)
                and parsed.username is None and parsed.password is None
                and (parsed.port is None or 1 <= parsed.port <= 65535))
    except ValueError:
        return False


def valid_browser_read_url(uri):
    """Allow public HTTPS plus one fixed loopback origin used by acceptance."""
    if not valid_web_url(uri):
        return False
    try:
        parsed = urlparse(uri)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        origin = (parsed.scheme, parsed.hostname, port)
        if origin == BROWSER_READ_ACCEPTANCE_ORIGIN:
            return True
        if parsed.scheme != "https" or parsed.hostname.endswith((".local", ".internal")):
            return False
        try:
            address = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            return parsed.hostname not in {"localhost"}
        return not (address.is_private or address.is_loopback or address.is_link_local
                    or address.is_reserved or address.is_multicast or address.is_unspecified)
    except (ValueError, TypeError):
        return False


def validate_browser_read_request(payload):
    if not isinstance(payload, dict) or set(payload) != {"id", "action", "url"}:
        raise ValueError("Invalid browser read request")
    if not isinstance(payload["id"], str) or not re.fullmatch(r"[a-zA-Z0-9-]{1,64}", payload["id"]):
        raise ValueError("Invalid request ID")
    if payload["action"] != "read_browser_page" or not valid_browser_read_url(payload["url"]):
        raise ValueError("Browser read URL is not allowed")
    return payload["url"]


def validate_launch(payload):
    if not isinstance(payload, dict) or set(payload) != {"id", "app", "url"}:
        raise ValueError("Invalid launch request")
    if not isinstance(payload["id"], str) or not re.fullmatch(r"[a-zA-Z0-9-]{1,64}", payload["id"]):
        raise ValueError("Invalid request ID")
    app, uri = payload["app"], payload["url"]
    if not isinstance(app, str) or app not in {*APP_IDS, "browser"}:
        raise ValueError("App is not in the launch allowlist")
    if not isinstance(uri, str) or (uri and (app not in {"browser", "chrome"} or not valid_web_url(uri))):
        raise ValueError("Invalid website address")
    return app, uri


def validate_project_request(payload):
    if not isinstance(payload, dict) or set(payload) != {"id", "action", "plan"}:
        raise ValueError("Invalid project request")
    if not isinstance(payload["id"], str) or not re.fullmatch(r"[a-zA-Z0-9-]{1,64}", payload["id"]):
        raise ValueError("Invalid request ID")
    if payload["action"] != "create_project" or not isinstance(payload["plan"], dict):
        raise ValueError("Project action is not allowlisted")
    return payload["plan"]


def validate_artifact_request(payload):
    if not isinstance(payload, dict) or set(payload) != {"id", "action", "kind", "path"}:
        raise ValueError("Invalid artifact request")
    if not isinstance(payload["id"], str) or not re.fullmatch(r"[a-zA-Z0-9-]{1,64}", payload["id"]):
        raise ValueError("Invalid request ID")
    kinds = {"board": {".kicad_pcb"}, "schematic": {".sch", ".kicad_sch"},
             "bom": {".ods", ".csv"}, "diagram": {".svg", ".odg"},
             "pdf": {".pdf"}, "folder": set()}
    if payload["action"] != "open_artifact" or payload["kind"] not in kinds or not isinstance(payload["path"], str):
        raise ValueError("Artifact action is not allowlisted")
    path = Path(payload["path"]).resolve()
    root = PROJECT_ROOT.resolve()
    if root not in path.parents or not path.exists():
        raise ValueError("Artifact is outside the ORCA project folder")
    if payload["kind"] == "folder":
        if not path.is_dir():
            raise ValueError("Project folder is invalid")
    elif not path.is_file() or path.suffix.lower() not in kinds[payload["kind"]]:
        raise ValueError("Artifact type does not match the requested app")
    return payload["kind"], path


def validate_cad_draft_request(payload):
    if not isinstance(payload, dict) or set(payload) != {"id", "action", "filename", "content"}:
        raise ValueError("Invalid CAD draft request")
    if not isinstance(payload["id"], str) or not re.fullmatch(r"[a-zA-Z0-9-]{1,64}", payload["id"]):
        raise ValueError("Invalid request ID")
    filename, content = payload["filename"], payload["content"]
    if payload["action"] != "save_cad_draft" or not isinstance(filename, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}\.kicad_pcb", filename):
        raise ValueError("CAD filename is invalid")
    if not isinstance(content, str) or not 1 <= len(content.encode("utf-8")) <= 1_000_000:
        raise ValueError("CAD content is outside the size limit")
    stripped = content.strip()
    if not stripped.startswith("(kicad_pcb ") or not stripped.endswith(")") or "\x00" in content:
        raise ValueError("CAD content is not a KiCad PCB document")
    return filename, content


def desktop_app_info(app):
    """Resolve only fixed allowlisted desktop entries from trusted directories."""
    root = Path.home() / ".local/share/applications" if app in LOCAL_APPS else Path("/usr/share/applications")
    return Gio.DesktopAppInfo.new_from_filename(str(root / APP_IDS[app]))


class KilnStudio(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id="com.fryrocket.kiln-studio")
        self.window = None
        self.web_view = None
        self.browser_windows = []
        self.fullscreen_enabled = True
        self.retry_source_id = None

    def do_activate(self) -> None:
        if self.window is not None:
            self.window.present()
            return

        Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", True)
        manager = WebKit2.UserContentManager()
        manager.connect("script-message-received::orcaLauncher", self._launch_message)
        manager.register_script_message_handler("orcaLauncher")
        manager.add_script(
            WebKit2.UserScript.new(
                "window.ORCA_DESKTOP_APP=true;window.ORCA_STUDIO_NODE='KILN';",
                WebKit2.UserContentInjectedFrames.TOP_FRAME,
                WebKit2.UserScriptInjectionTime.START,
                None,
                None,
            )
        )
        self.web_view = WebKit2.WebView.new_with_user_content_manager(manager)
        background = Gdk.RGBA()
        background.parse("#0b211a")
        self.web_view.set_background_color(background)
        self.web_view.connect("decide-policy", self._decide_policy)
        self.web_view.connect("load-changed", self._studio_load_changed)
        self.web_view.connect("load-failed", self._load_failed)

        self.window = Gtk.ApplicationWindow(application=self)
        self.window.set_title("KILN Studio")
        self.window.set_default_size(1440, 920)
        self.window.set_size_request(980, 680)
        self.window.set_icon_name("kiln-studio")
        header = Gtk.HeaderBar()
        header.set_name("kiln-header")
        header.set_title("KILN Studio")
        header.set_show_close_button(True)
        header.set_decoration_layout(":minimize,maximize,close")
        self.window.set_titlebar(header)
        self.header_style = Gtk.CssProvider()
        self.header_style.load_from_data(HEADER_CSS)
        Gtk.StyleContext.add_provider_for_screen(self.window.get_screen(), self.header_style,
                                                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.window.add(self.web_view)
        self.window.show_all()
        self.window.fullscreen()
        self.web_view.load_uri(STUDIO_URL)

        reload_action = Gio.SimpleAction.new("reload", None)
        reload_action.connect("activate", lambda *_: self.web_view.reload_bypass_cache())
        self.add_action(reload_action)
        self.set_accels_for_action("app.reload", ["<Primary>r"])

        fullscreen_action = Gio.SimpleAction.new("toggle-fullscreen", None)
        fullscreen_action.connect("activate", self._toggle_fullscreen)
        self.add_action(fullscreen_action)
        self.set_accels_for_action("app.toggle-fullscreen", ["F11"])

    def _toggle_fullscreen(self, *_args) -> None:
        if self.fullscreen_enabled:
            self.window.unfullscreen()
        else:
            self.window.fullscreen()
        self.fullscreen_enabled = not self.fullscreen_enabled

    def _studio_load_changed(self, _view, event) -> None:
        if event == WebKit2.LoadEvent.FINISHED and self.retry_source_id is not None:
            GLib.source_remove(self.retry_source_id)
            self.retry_source_id = None

    def _retry_studio(self) -> bool:
        self.retry_source_id = None
        if self.web_view is not None:
            self.web_view.load_uri(STUDIO_URL)
        return GLib.SOURCE_REMOVE

    @staticmethod
    def _is_studio_uri(uri: str) -> bool:
        try:
            parsed = urlparse(uri)
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            return (parsed.scheme, parsed.hostname, port) == STUDIO_ORIGIN and parsed.username is None and parsed.password is None
        except (ValueError, TypeError):
            return False

    def _launch_message(self, _manager, result):
        if not self._is_studio_uri(self.web_view.get_uri()):
            return
        payload = None
        try:
            raw = result.get_js_value().to_string()
            if len(raw) > 32_768:
                raise ValueError("Studio request is too large")
            payload = json.loads(raw)
            if payload.get("action") == "read_browser_page":
                uri = validate_browser_read_request(payload)
                self._open_browser(uri, capture_request_id=payload["id"])
                return
            if payload.get("action") == "open_artifact":
                kind, path = validate_artifact_request(payload)
                artifact_apps = {"board": "kicad_pcb_editor", "schematic": "kicad_schematic_editor",
                                 "bom": "libreoffice_calc", "diagram": "libreoffice_draw", "folder": "files"}
                if kind == "pdf":
                    if not Gio.AppInfo.launch_default_for_uri(path.as_uri(), None):
                        raise ValueError("KILN could not open the PDF viewer")
                else:
                    info = desktop_app_info(artifact_apps[kind])
                    if info is None or not info.launch([Gio.File.new_for_path(str(path))], None):
                        raise ValueError("KILN could not open the selected project artifact")
                reply = {"id": payload["id"], "ok": True, "message": f"Opened {path.name} on KILN."}
            elif payload.get("action") == "save_cad_draft":
                filename, content = validate_cad_draft_request(payload)
                root = PROJECT_ROOT / "Chat CAD"
                root.mkdir(parents=True, exist_ok=True)
                stem = Path(filename).stem
                folder = root / stem
                counter = 2
                while folder.exists():
                    folder = root / f"{stem}-{counter}"
                    counter += 1
                folder.mkdir(mode=0o750)
                path = folder / filename
                path.write_text(content, encoding="utf-8")
                info = desktop_app_info("kicad_pcb_editor")
                if info is None or not info.launch([Gio.File.new_for_path(str(path))], None):
                    raise ValueError("The CAD draft was saved, but KILN could not open PCB Editor")
                reply = {"id": payload["id"], "ok": True,
                         "message": f"Saved {filename} under ORCA Projects and opened it in KiCad PCB Editor."}
            elif payload.get("action") == "create_project":
                paths = create_project(validate_project_request(payload))
                info = desktop_app_info("kicad_pcb_editor")
                if info is None or not info.launch([Gio.File.new_for_path(paths["board"])], None):
                    raise ValueError("The project was created, but KILN could not open PCB Editor")
                message = "Created a new editable AI Dog Feeder project and opened its PCB layout."
                reply = {"id": payload["id"], "ok": True, "message": message,
                         "project": paths}
            else:
                app, uri = validate_launch(payload)
                if app == "browser":
                    self._open_browser(uri)
                    message = "Opened the Studio browser."  # Window opened, not proof a site loaded.
                else:
                    info = desktop_app_info(app)
                    if info is None:
                        raise ValueError("This app is not installed on KILN")
                    files = [Gio.File.new_for_uri(uri)] if uri else []
                    if not info.launch(files, None):
                        raise ValueError("KILN could not launch this app")
                    message = f"KILN accepted the launch request for {app}."
                reply = {"id": payload["id"], "ok": True, "message": message}
        except Exception as error:
            reply = {"id": payload.get("id", "") if isinstance(payload, dict) else "",
                     "ok": False, "message": str(error)[:240]}
        self._send_launcher_reply(reply)

    def _send_launcher_reply(self, reply):
        self.web_view.run_javascript(
            "window.dispatchEvent(new CustomEvent('orca-launch-result',{detail:"
            + json.dumps(reply) + "}));", None, None, None)

    def _open_browser(self, uri, capture_request_id=None):
        if len(self.browser_windows) >= 6:
            raise ValueError("Close an ORCA browser window before opening another (maximum six).")
        # Separate ephemeral context and content manager: no Studio cookies or app bridge.
        window = Gtk.ApplicationWindow(application=self)
        window.set_title("ORCA Browser — private session")
        window.set_default_size(1100, 800)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        toolbar = Gtk.Box(spacing=6)
        address = Gtk.Entry()
        address.set_placeholder_text("https://example.com")
        view = WebKit2.WebView.new_with_context(WebKit2.WebContext.new_ephemeral())
        status = Gtk.Label(label="Private session. No cookies, ORCA tools, or memory access. Downloads and device permissions are disabled.")
        status.set_line_wrap(True)
        for label, callback in [("Back", view.go_back), ("Forward", view.go_forward), ("Reload", view.reload)]:
            button = Gtk.Button(label=label)
            button.connect("clicked", lambda _, action=callback: action())
            toolbar.pack_start(button, False, False, 0)
        toolbar.pack_start(address, True, True, 0)
        def navigate(_entry):
            target = address.get_text().strip()
            if ":" not in target:
                target = "https://" + target
            validator = valid_browser_read_url if capture_request_id else valid_web_url
            if validator(target):
                view.load_uri(target)
            else:
                status.set_text("Enter an HTTP or HTTPS address without a username or password.")
        address.connect("activate", navigate)
        def policy(_view, decision, kind):
            if kind not in (WebKit2.PolicyDecisionType.NAVIGATION_ACTION, WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION):
                return False
            target = decision.get_navigation_action().get_request().get_uri()
            validator = valid_browser_read_url if capture_request_id else valid_web_url
            if target == "about:blank" or validator(target):
                if kind == WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION:
                    decision.ignore()
                    view.load_uri(target)
                else:
                    decision.use()
            else:
                decision.ignore()
                status.set_text("Blocked a non-web link. Websites cannot launch KILN apps.")
            return True
        view.connect("decide-policy", policy)
        view.connect("permission-request", lambda _view, request: (request.deny(), True)[1])
        view.get_context().connect("download-started", lambda _context, download: download.cancel())
        view.connect("notify::uri", lambda *_: address.set_text(view.get_uri() or ""))
        completed = {"value": False}
        def reply_once(reply):
            if completed["value"]:
                return
            completed["value"] = True
            self._send_launcher_reply(reply)
        def load_failed(_view, _event, _uri, error):
            status.set_text("Page could not load: " + error.message)
            if capture_request_id:
                reply_once({"id": capture_request_id, "ok": False,
                            "message": "Private browser could not read the page."})
            return False
        view.connect("load-failed", load_failed)
        if capture_request_id:
            def capture_done(browser_view, js_result, _data):
                try:
                    result = browser_view.run_javascript_finish(js_result)
                    captured = json.loads(result.get_js_value().to_string())
                    if (not isinstance(captured, dict) or set(captured) != {"url", "title", "text"}
                            or not valid_browser_read_url(captured["url"])):
                        raise ValueError("Invalid page capture")
                    reply_once({"id": capture_request_id, "ok": True,
                                "message": "Read a private browser page as untrusted content.",
                                "page": captured})
                    status.set_text("Page text captured for ORCA as untrusted content. No form was submitted.")
                except Exception:
                    reply_once({"id": capture_request_id, "ok": False,
                                "message": "Private browser returned an invalid page capture."})
            def load_changed(browser_view, event):
                if event != WebKit2.LoadEvent.FINISHED or completed["value"]:
                    return
                script = "JSON.stringify({url:location.href,title:(document.title||'').slice(0,500),text:(document.body?document.body.innerText:'').slice(0,50000)})"
                browser_view.run_javascript(script, None, capture_done, None)
            view.connect("load-changed", load_changed)
        box.pack_start(toolbar, False, False, 0)
        box.pack_start(status, False, False, 0)
        box.pack_start(view, True, True, 0)
        window.add(box)
        self.browser_windows.append(window)
        window.connect("destroy", lambda widget: self.browser_windows.remove(widget))
        window.show_all()
        if uri:
            address.set_text(uri)
            view.load_uri(uri)
        else:
            view.load_html("<body style='background:#0b211a;color:#edf7f3;font:20px sans-serif;padding:40px'><h1>ORCA Browser</h1><p>Enter a website above. This private browser cannot access Studio's app-launch controls.</p></body>", "about:blank")

    def _decide_policy(self, _view, decision, decision_type) -> bool:
        if decision_type != WebKit2.PolicyDecisionType.NAVIGATION_ACTION:
            return False
        action = decision.get_navigation_action()
        uri = action.get_request().get_uri()
        if self._is_studio_uri(uri):
            decision.use()
            return True
        decision.ignore()
        if action.get_navigation_type() == WebKit2.NavigationType.LINK_CLICKED and valid_web_url(uri):
            self._open_browser(uri)
        return True

    def _load_failed(self, _view, _event, _uri, error) -> bool:
        detail = GLib.markup_escape_text(error.message)
        if self.retry_source_id is None:
            self.retry_source_id = GLib.timeout_add_seconds(5, self._retry_studio)
        self.web_view.load_html(
            f"""<!doctype html><meta charset="utf-8"><style>
            body{{margin:0;background:#081012;color:#e8f3ef;font:16px system-ui;display:grid;place-items:center;height:100vh}}
            main{{max-width:520px;text-align:center;padding:44px}}h1{{font-size:42px;margin:0 0 12px}}p{{color:#9bb0a9;line-height:1.55}}
            button{{background:#ff9d45;border:0;border-radius:12px;padding:12px 20px;font-weight:700;cursor:pointer}}
            </style><main><h1>KILN is waking up</h1><p>KILN Studio is not ready yet. It will retry automatically.</p>
            <p>{detail}</p><button onclick="location.href='{STUDIO_URL}'">Try again</button></main>""",
            STUDIO_URL,
        )
        return True


if __name__ == "__main__":
    GLib.set_prgname("kiln-studio")
    raise SystemExit(KilnStudio().run(None))
