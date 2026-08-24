"""R11-F75 ("dashboard HEAD cwd escape") — a crisp finding.

Handler subclasses SimpleHTTPRequestHandler and overrides do_GET /
do_POST, but not do_HEAD. Parent do_HEAD → send_head → translate_path
serves files under cwd. GET /mao/web_ui/auth.py is 404; HEAD of the
same path is 200 with Content-Length of the source file.

F74 contained GET /static/ joins. It did not cover inherited HEAD.

Fix: do_HEAD uses the same public-file map as GET; cwd is never served.
"""
from __future__ import annotations

import sys
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mao.web_ui.server import Handler, STATIC


def _serve():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


def _req(httpd, method: str, path: str):
    conn = HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=3)
    conn.request(method, path)
    resp = conn.getresponse()
    body = resp.read()
    headers = dict(resp.getheaders())
    conn.close()
    return resp.status, headers, body


def test_head_repo_source_is_404():
    """The bug: HEAD /mao/web_ui/auth.py used to be 200 from cwd."""
    auth = Path("mao/web_ui/auth.py")
    assert auth.is_file()
    httpd = _serve()
    try:
        status, headers, body = _req(httpd, "HEAD", "/mao/web_ui/auth.py")
        assert status == 404
        assert body == b"" or b"dashboard_token" not in body
        assert headers.get("Content-Length") != str(auth.stat().st_size)
        gstatus, _, gbody = _req(httpd, "GET", "/mao/web_ui/auth.py")
        assert gstatus == 404
        assert b"dashboard_token" not in gbody
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_head_status_md_is_404():
    httpd = _serve()
    try:
        status, _, _ = _req(httpd, "HEAD", "/STATUS.md")
        assert status == 404
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_head_index_still_ok():
    index = STATIC / "index.html"
    httpd = _serve()
    try:
        status, headers, body = _req(httpd, "HEAD", "/")
        assert status == 200
        assert body == b""
        assert headers.get("Content-Length") == str(index.stat().st_size)
        gstatus, _, gbody = _req(httpd, "GET", "/")
        assert gstatus == 200
        assert len(gbody) == index.stat().st_size
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_head_static_app_js_still_ok():
    js = STATIC / "app.js"
    assert js.is_file()
    httpd = _serve()
    try:
        status, headers, body = _req(httpd, "HEAD", "/static/app.js")
        assert status == 200
        assert body == b""
        assert headers.get("Content-Length") == str(js.stat().st_size)
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_head_static_dotdot_still_404():
    httpd = _serve()
    try:
        status, _, body = _req(httpd, "HEAD", "/static/../auth.py")
        assert status == 404
        assert b"dashboard_token" not in body
    finally:
        httpd.shutdown()
        httpd.server_close()
