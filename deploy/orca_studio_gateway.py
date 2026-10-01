#!/usr/bin/env python3
"""Small same-origin gateway from a trusted LAN/Tailnet to loopback ORCA."""

from __future__ import annotations

import argparse
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
}


class Gateway(BaseHTTPRequestHandler):
    upstream_host = "127.0.0.1"
    upstream_port = 8787
    image_host = "127.0.0.1"
    image_port = 8790

    def log_message(self, format: str, *args) -> None:
        return

    def _proxy(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_error(400, "invalid content length")
            return
        limit = 18_000_000 if self.path in {
            "/api/images/edit", "/api/videos/animate"} else 1_000_000
        if length < 0 or length > limit:
            self.send_error(413, "request body too large")
            return
        body = self.rfile.read(length) if length else None
        headers = {
            name: value for name, value in self.headers.items()
            if name.lower() not in HOP_BY_HOP | {"host", "content-length"}
        }
        is_media_request = self.path in {
            "/api/images/generate", "/api/images/edit", "/api/images/health",
            "/api/videos/generate", "/api/videos/animate", "/api/videos/health",
            "/api/media/cancel",
        }
        upstream_host = self.image_host if is_media_request else self.upstream_host
        upstream_port = self.image_port if is_media_request else self.upstream_port
        upstream_path = ({
            "/api/images/generate": "/generate",
            "/api/images/edit": "/edit",
            "/api/images/health": "/health",
            "/api/videos/generate": "/video/generate",
            "/api/videos/animate": "/video/animate",
            "/api/videos/health": "/health",
            "/api/media/cancel": "/cancel",
        }.get(self.path, self.path))
        headers["Host"] = f"{upstream_host}:{upstream_port}"
        if body is not None:
            headers["Content-Length"] = str(len(body))
        connection = HTTPConnection(
            upstream_host, upstream_port, timeout=1_260 if is_media_request else 120)
        try:
            connection.request(self.command, upstream_path, body=body, headers=headers)
            response = connection.getresponse()
            payload = response.read()
            self.send_response(response.status, response.reason)
            for name, value in response.getheaders():
                if name.lower() not in HOP_BY_HOP | {"content-length"}:
                    self.send_header(name, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)
        except OSError:
            self.send_error(
                502,
                "KILN image generation is unavailable"
                if is_media_request else "FORGE ORCA is unavailable",
            )
        finally:
            connection.close()

    do_GET = _proxy
    do_HEAD = _proxy
    do_POST = _proxy


def main() -> None:
    parser = argparse.ArgumentParser(description="ORCA Studio trusted-network gateway")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--upstream-host", default="127.0.0.1")
    parser.add_argument("--upstream-port", type=int, default=8787)
    args = parser.parse_args()
    Gateway.upstream_host = args.upstream_host
    Gateway.upstream_port = args.upstream_port
    server = ThreadingHTTPServer((args.host, args.port), Gateway)
    server.serve_forever()


if __name__ == "__main__":
    main()
