#!/usr/bin/env python3
"""Small same-origin gateway from a trusted LAN/Tailnet to loopback ORCA."""

from __future__ import annotations

import argparse
import hashlib
import html
import hmac
from http.client import HTTPConnection
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address, ip_network
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
from urllib.parse import urlparse


HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
}

CLIENT_AUTH_HEADERS = {
    "x-orca-identity", "x-orca-identity-token", "x-orca-operator-token",
}
TAILSCALE_V4 = ip_network("100.64.0.0/10")
TAILSCALE_V6 = ip_network("fd7a:115c:a1e0::/48")
MEDIA_GET_PATHS = {"/api/images/health", "/api/videos/health"}
MEDIA_POST_PATHS = {
    "/api/images/generate", "/api/images/edit", "/api/videos/generate",
    "/api/videos/animate", "/api/media/cancel",
}
MEDIA_PATHS = MEDIA_GET_PATHS | MEDIA_POST_PATHS
GET_API_PATHS = {
    "/api/business/muse", "/api/business/state", "/api/communications",
    "/api/config", "/api/edge-inference", "/api/engineering/catalog",
    "/api/health", "/api/inbox", "/api/inventory",
    "/api/inventory/analysis", "/api/inventory/system", "/api/solo-operator/system",
    "/api/state", *MEDIA_GET_PATHS,
}
POST_API_PATHS = {
    "/api/business/muse/email-handoff", "/api/business/muse/handoff",
    "/api/business/records", "/api/business/workflows", "/api/cad/pcb-draft",
    "/api/chat", "/api/control/emergency-stop", "/api/engineering",
    "/api/custom-bots/list", "/api/custom-bots/save", "/api/custom-bots/test",
    "/api/governance/retention-audit", "/api/heartbeats", "/api/inbox/import",
    "/api/inventory/counts", "/api/inventory/counts/preview",
    "/api/inventory/workflows", "/api/jobs", "/api/memory",
    "/api/product-development/plans", "/api/project/plan", "/api/queue",
    "/api/science", "/api/security/scan", "/api/solo-operator/action-plan",
    "/api/solo-operator/snapshot", "/api/temper/inventory-dataset/plan",
    "/api/manuals/export",
    *MEDIA_POST_PATHS,
}
MANUAL_GET_PATTERN = re.compile(r"/api/manuals/([0-9a-f]{64})/manual\.(odt|pdf)")
POST_API_PATTERNS = tuple(re.compile(pattern) for pattern in (
    r"/api/approvals/[A-Za-z0-9_.:-]+",
    r"/api/bots/[A-Za-z0-9_.:-]+/pause",
    r"/api/incidents(?:/[A-Za-z0-9_.:-]+)?",
    r"/api/inventory/counts/[A-Za-z0-9_.:-]+/execute",
    r"/api/inventory/workflows/[A-Za-z0-9_.:-]+/execute",
    r"/api/jobs/[A-Za-z0-9_.:-]+/(?:complete|pause|resume|review|start)",
    r"/api/lanes/[A-Za-z0-9_.:-]+/pause",
    r"/api/nodes/[A-Za-z0-9_.:-]+/(?:health|pause)",
))


def load_gateway_token(path: str | Path) -> str:
    token_path = Path(path)
    metadata = token_path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError("gateway token must be a regular non-symlink file")
    if metadata.st_size < 32 or metadata.st_size > 512:
        raise ValueError("gateway token must contain 32-512 bytes")
    if metadata.st_mode & 0o077:
        raise ValueError("gateway token must be owner-only")
    if metadata.st_uid != os.geteuid():
        raise ValueError("gateway token must be owned by the service user")
    descriptor = os.open(token_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
        opened = os.fstat(handle.fileno())
        if (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
            raise ValueError("gateway token changed while opening")
        token = handle.read().strip()
    if not 32 <= len(token) <= 512 or any(character.isspace() for character in token):
        raise ValueError("gateway token is malformed")
    return token


def trusted_client(address: str) -> bool:
    try:
        candidate = ip_address(address)
    except ValueError:
        return False
    return candidate.is_loopback or candidate in TAILSCALE_V4 or candidate in TAILSCALE_V6


def allowed_request(method: str, path: str) -> bool:
    if method in {"GET", "HEAD"}:
        return (
            path == "/" or path in GET_API_PATHS or MANUAL_GET_PATTERN.fullmatch(path)
            or not path.startswith("/api/")
        )
    if method != "POST":
        return False
    return path in POST_API_PATHS or any(pattern.fullmatch(path) for pattern in POST_API_PATTERNS)


def _inline_markup(value: str) -> str:
    escaped = html.escape(value, quote=True)
    return re.sub(r"\*\*([^*\n]+)\*\*", r"<strong>\1</strong>", escaped)


def manual_html(title: str, content: str) -> str:
    """Render a small, safe Markdown subset for LibreOffice Writer import."""
    blocks: list[str] = []
    list_kind: str | None = None
    in_code = False
    code_lines: list[str] = []

    def close_list() -> None:
        nonlocal list_kind
        if list_kind:
            blocks.append(f"</{list_kind}>")
            list_kind = None

    for raw_line in content.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.rstrip()
        if line.strip().startswith("```"):
            close_list()
            if in_code:
                blocks.append(f"<pre>{html.escape(chr(10).join(code_lines))}</pre>")
                code_lines = []
            in_code = not in_code
            continue
        if in_code:
            code_lines.append(line)
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        bullet = re.match(r"^\s*[-*]\s+(.+)$", line)
        numbered = re.match(r"^\s*\d+[.)]\s+(.+)$", line)
        if heading:
            close_list()
            level = min(len(heading.group(1)) + 1, 6)
            blocks.append(f"<h{level}>{_inline_markup(heading.group(2))}</h{level}>")
        elif bullet or numbered:
            kind = "ul" if bullet else "ol"
            if list_kind != kind:
                close_list()
                blocks.append(f"<{kind}>")
                list_kind = kind
            blocks.append(f"<li>{_inline_markup((bullet or numbered).group(1))}</li>")
        elif not line.strip():
            close_list()
        else:
            close_list()
            blocks.append(f"<p>{_inline_markup(line)}</p>")
    close_list()
    if in_code:
        blocks.append(f"<pre>{html.escape(chr(10).join(code_lines))}</pre>")
    body = "\n".join(blocks)
    safe_title = html.escape(title, quote=True)
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{safe_title}</title>
<style>
@page {{ size: letter; margin: 0.7in; }}
body {{ font-family: 'Liberation Sans', sans-serif; color: #172331; font-size: 10.5pt; line-height: 1.35; }}
h1 {{ color: #126b70; font-size: 25pt; border-bottom: 2px solid #45a7a2; padding-bottom: 8pt; }}
h2 {{ color: #166f78; font-size: 18pt; margin-top: 18pt; }}
h3 {{ color: #245f72; font-size: 14pt; margin-top: 13pt; }}
p {{ margin: 5pt 0; }} li {{ margin: 3pt 0; }}
pre {{ background: #eef6f5; border: 1px solid #b7d8d5; padding: 8pt; white-space: pre-wrap; }}
</style></head><body><h1>{safe_title}</h1>{body}</body></html>"""


def export_manual(
    title: str,
    content: str,
    state_root: Path,
    run=subprocess.run,
) -> dict[str, object]:
    title = title.strip()
    if not 1 <= len(title) <= 160 or any(ord(character) < 32 for character in title):
        raise ValueError("title must contain 1-160 printable characters")
    if not 100 <= len(content) <= 64_000 or "\x00" in content:
        raise ValueError("manual content must contain 100-64,000 characters")
    digest = hashlib.sha256(f"{title}\0{content}".encode("utf-8")).hexdigest()
    manuals = state_root / "manuals"
    destination = manuals / digest
    pdf = destination / "manual.pdf"
    odt = destination / "manual.odt"
    manifest = destination / "manifest.json"
    if pdf.is_file() and odt.is_file() and manifest.is_file():
        result = json.loads(manifest.read_text(encoding="utf-8"))
        if pdf.read_bytes().startswith(b"%PDF-") and odt.read_bytes().startswith(b"PK"):
            return result
    if destination.exists():
        raise RuntimeError("existing manual evidence is incomplete or corrupt; it was preserved")

    manuals.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = Path(tempfile.mkdtemp(prefix=f".{digest}.", dir=manuals))
    try:
        source = temporary / "manual.html"
        source.write_text(manual_html(title, content), encoding="utf-8")
        source.chmod(0o600)
        profile = state_root / "libreoffice-profile"
        profile.mkdir(parents=True, exist_ok=True, mode=0o700)
        common = [
            "/usr/bin/libreoffice", "--headless", "--nologo", "--nodefault", "--nolockcheck",
            f"-env:UserInstallation={profile.as_uri()}",
        ]
        for extension, input_path in (("odt", source), ("pdf", temporary / "manual.odt")):
            completed = run(
                [*common, "--convert-to", extension, "--outdir", str(temporary), str(input_path)],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, timeout=120, check=False,
            )
            output = temporary / f"manual.{extension}"
            if completed.returncode or not output.is_file() or output.stat().st_size < 100:
                detail = (completed.stdout or "LibreOffice produced no diagnostic").strip()[-1000:]
                raise RuntimeError(f"LibreOffice {extension.upper()} export failed: {detail}")
        if not (temporary / "manual.pdf").read_bytes().startswith(b"%PDF-"):
            raise RuntimeError("LibreOffice output did not contain a valid PDF signature")
        if not (temporary / "manual.odt").read_bytes().startswith(b"PK"):
            raise RuntimeError("LibreOffice output did not contain a valid ODT signature")
        pdf_bytes = (temporary / "manual.pdf").read_bytes()
        result = {
            "status": "verified", "id": digest, "title": title,
            "pdf_url": f"/api/manuals/{digest}/manual.pdf",
            "odt_url": f"/api/manuals/{digest}/manual.odt",
            "sha256": hashlib.sha256(pdf_bytes).hexdigest(), "bytes": len(pdf_bytes),
            "generator": "LibreOffice Writer on KILN",
        }
        (temporary / "manifest.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        for artifact in temporary.iterdir():
            artifact.chmod(0o600)
        temporary.rename(destination)
        return result
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


class Gateway(BaseHTTPRequestHandler):
    upstream_host = "127.0.0.1"
    upstream_port = 8787
    image_host = "127.0.0.1"
    image_port = 8790
    identity = "fry"
    identity_token = ""
    state_root = Path("/var/lib/orca-studio")
    manual_lock = threading.Lock()

    def log_message(self, format: str, *args) -> None:
        return

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        event = {
            "event": "orca_gateway_request", "method": self.command,
            "path": urlparse(self.path).path, "status": code,
            "source": "loopback" if ip_address(self.client_address[0]).is_loopback else "tailnet",
        }
        print(json.dumps(event, sort_keys=True), file=sys.stderr, flush=True)

    def _json_response(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _authenticated_local_request(self, limit: int) -> int | None:
        if not trusted_client(self.client_address[0]):
            self.send_error(403, "trusted transport required")
            return None
        supplied_identity = self.headers.get("X-ORCA-Identity", "")
        supplied_token = self.headers.get("X-ORCA-Identity-Token", "")
        header_authenticated = (
            supplied_identity == self.identity
            and hmac.compare_digest(supplied_token, self.identity_token)
        )
        cookies = SimpleCookie()
        try:
            cookies.load(self.headers.get("Cookie", ""))
        except Exception:
            cookies = SimpleCookie()
        session = cookies.get("ORCA_GATEWAY_SESSION")
        expected_session = hmac.new(
            self.identity_token.encode("utf-8"), b"orca-studio-session-v1", hashlib.sha256
        ).hexdigest()
        cookie_authenticated = bool(
            session and hmac.compare_digest(session.value, expected_session)
        )
        if not header_authenticated and not cookie_authenticated:
            self.send_error(401, "authenticated ORCA identity required")
            return None
        if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) > 1:
            self.send_error(400, "ambiguous request framing")
            return None
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_error(400, "invalid content length")
            return None
        if length < 0 or length > limit:
            self.send_error(413, "request body too large")
            return None
        return length

    def _manual_export(self) -> None:
        length = self._authenticated_local_request(70_000)
        if length is None:
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            self.send_error(415, "application/json required")
            return
        try:
            request = json.loads(self.rfile.read(length))
            if not isinstance(request, dict) or set(request) != {"title", "content"}:
                raise ValueError("request must contain exactly title and content")
            if not isinstance(request["title"], str) or not isinstance(request["content"], str):
                raise ValueError("title and content must be strings")
            with self.manual_lock:
                result = export_manual(request["title"], request["content"], self.state_root)
        except (json.JSONDecodeError, ValueError) as error:
            self._json_response(400, {"error": str(error)})
            return
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            self._json_response(502, {"error": str(error)})
            return
        self._json_response(201, result)

    def _manual_download(self, path: str) -> None:
        if self._authenticated_local_request(0) is None:
            return
        match = MANUAL_GET_PATTERN.fullmatch(path)
        if not match:
            self.send_error(404)
            return
        digest, extension = match.groups()
        artifact = self.state_root / "manuals" / digest / f"manual.{extension}"
        if not artifact.is_file():
            self.send_error(404, "manual artifact not found")
            return
        payload = artifact.read_bytes()
        media_type = "application/pdf" if extension == "pdf" else "application/vnd.oasis.opendocument.text"
        self.send_response(200)
        self.send_header("Content-Type", media_type)
        self.send_header("Content-Disposition", f'attachment; filename="ORCA-Manual.{extension}"')
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def _proxy(self) -> None:
        path = urlparse(self.path).path
        if self.command == "POST" and path == "/api/manuals/export":
            self._manual_export()
            return
        if self.command in {"GET", "HEAD"} and MANUAL_GET_PATTERN.fullmatch(path):
            self._manual_download(path)
            return
        if not trusted_client(self.client_address[0]):
            self.send_error(403, "trusted transport required")
            return
        if not allowed_request(self.command, path):
            self.send_error(405, "route or method is not allowlisted")
            return
        if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) > 1:
            self.send_error(400, "ambiguous request framing")
            return
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
            if name.lower() not in HOP_BY_HOP | CLIENT_AUTH_HEADERS | {"host", "content-length"}
        }
        is_media_request = path in MEDIA_PATHS
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
        }.get(path, self.path))
        headers["Host"] = f"{upstream_host}:{upstream_port}"
        if not is_media_request:
            headers["X-ORCA-Identity"] = self.identity
            headers["X-ORCA-Identity-Token"] = self.identity_token
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
            if self.command == "GET" and path == "/" and response.status == 200:
                session = hmac.new(
                    self.identity_token.encode("utf-8"), b"orca-studio-session-v1", hashlib.sha256
                ).hexdigest()
                self.send_header(
                    "Set-Cookie",
                    f"ORCA_GATEWAY_SESSION={session}; Path=/; HttpOnly; SameSite=Strict; Max-Age=86400",
                )
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
    parser.add_argument("--token-file", required=True)
    args = parser.parse_args()
    Gateway.upstream_host = args.upstream_host
    Gateway.upstream_port = args.upstream_port
    Gateway.identity_token = load_gateway_token(args.token_file)
    server = ThreadingHTTPServer((args.host, args.port), Gateway)
    server.serve_forever()


if __name__ == "__main__":
    main()
