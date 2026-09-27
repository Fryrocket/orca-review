#!/usr/bin/env python3
"""Native KILN Studio shell for the KILN Ubuntu desktop."""

from urllib.parse import urlparse

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.0")

from gi.repository import Gio, GLib, Gtk, WebKit2  # noqa: E402


STUDIO_URL = "http://127.0.0.1:8788/"
STUDIO_ORIGIN = ("http", "127.0.0.1", 8788)


class KilnStudio(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id="com.fryrocket.kiln-studio")
        self.window = None
        self.web_view = None

    def do_activate(self) -> None:
        if self.window is not None:
            self.window.present()
            return

        manager = WebKit2.UserContentManager()
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
        self.web_view.connect("decide-policy", self._decide_policy)
        self.web_view.connect("load-failed", self._load_failed)

        self.window = Gtk.ApplicationWindow(application=self)
        self.window.set_title("KILN Studio")
        self.window.set_default_size(1440, 920)
        self.window.set_size_request(980, 680)
        self.window.set_icon_name("kiln-studio")
        self.window.add(self.web_view)
        self.window.show_all()
        self.web_view.load_uri(STUDIO_URL)

        reload_action = Gio.SimpleAction.new("reload", None)
        reload_action.connect("activate", lambda *_: self.web_view.reload_bypass_cache())
        self.add_action(reload_action)
        self.set_accels_for_action("app.reload", ["<Primary>r"])

    @staticmethod
    def _is_studio_uri(uri: str) -> bool:
        parsed = urlparse(uri)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        return (parsed.scheme, parsed.hostname, port) == STUDIO_ORIGIN

    def _decide_policy(self, _view, decision, decision_type) -> bool:
        if decision_type != WebKit2.PolicyDecisionType.NAVIGATION_ACTION:
            return False
        action = decision.get_navigation_action()
        uri = action.get_request().get_uri()
        if self._is_studio_uri(uri):
            decision.use()
            return True
        decision.ignore()
        if action.get_navigation_type() == WebKit2.NavigationType.LINK_CLICKED:
            Gio.AppInfo.launch_default_for_uri(uri, None)
        return True

    def _load_failed(self, _view, _event, _uri, error) -> bool:
        detail = GLib.markup_escape_text(error.message)
        self.web_view.load_html(
            f"""<!doctype html><meta charset="utf-8"><style>
            body{{margin:0;background:#081012;color:#e8f3ef;font:16px system-ui;display:grid;place-items:center;height:100vh}}
            main{{max-width:520px;text-align:center;padding:44px}}h1{{font-size:42px;margin:0 0 12px}}p{{color:#9bb0a9;line-height:1.55}}
            button{{background:#ff9d45;border:0;border-radius:12px;padding:12px 20px;font-weight:700;cursor:pointer}}
            </style><main><h1>KILN is waking up</h1><p>KILN Studio is not ready yet.</p>
            <p>{detail}</p><button onclick="location.href='{STUDIO_URL}'">Try again</button></main>""",
            STUDIO_URL,
        )
        return True


if __name__ == "__main__":
    GLib.set_prgname("kiln-studio")
    raise SystemExit(KilnStudio().run(None))
