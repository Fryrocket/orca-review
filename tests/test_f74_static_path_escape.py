"""R11-F74 ("dashboard static path escape") — a crisp finding.

mao/web_ui/server.py Handler.do_GET serves /static/* with no auth:

    name = path.split("/", 2)[-1]
    f = STATIC / name
    if not f.exists(): ...
    return self._file(f, ctype)

Path join with `../` is not contained to STATIC. GET /static/../auth.py
returns dashboard auth source; enough `..` reads host files. F72 covered
ToolRegistry.read_file, not this HTTP surface.

Fix: contained_static_file() resolves then relative_to(STATIC). Escapes
and missing files return None (HTTP 404).
"""
from __future__ import annotations

import sys
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mao.web_ui.server import Handler, STATIC, contained_static_file


def test_relative_escape_is_blocked(tmp_path):
    static = tmp_path / "static"
    static.mkdir()
    (static / "ok.js").write_text("ok")
    secret = tmp_path / "secret.txt"
    secret.write_text("LEAKME")
    assert contained_static_file("../secret.txt", root=static) is None
    assert secret.read_text() == "LEAKME"


def test_absolute_path_is_blocked(tmp_path):
    static = tmp_path / "static"
    static.mkdir()
    (static / "ok.js").write_text("ok")
    secret = tmp_path / "abs_secret.txt"
    secret.write_text("LEAKABS")
    assert contained_static_file(str(secret), root=static) is None


def test_in_static_file_still_served(tmp_path):
    static = tmp_path / "static"
    static.mkdir()
    (static / "ok.js").write_text("ok")
    got = contained_static_file("ok.js", root=static)
    assert got is not None
    assert got.read_text() == "ok"


def test_real_static_sibling_auth_is_blocked():
    """The bug: /static/../auth.py used to leak mao/web_ui/auth.py."""
    sibling = STATIC.parent / "auth.py"
    assert sibling.is_file()
    assert contained_static_file("../auth.py") is None
    assert contained_static_file("app.js") is not None


def test_handler_get_static_dotdot_is_404():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        conn = HTTPConnection("127.0.0.1", port, timeout=3)
        conn.request("GET", "/static/../auth.py")
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        assert resp.status == 404
        assert b"hmac.compare_digest" not in body
        assert b"dashboard_token" not in body
    finally:
        httpd.shutdown()
        httpd.server_close()
