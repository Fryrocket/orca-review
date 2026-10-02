#!/usr/bin/env python3
"""Local-only LibreOffice conversion broker for authenticated ORCA manual jobs."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import socket
import socketserver
import stat
import struct
import subprocess
import tempfile


MAX_REQUEST = 70_000


def _inline_markup(value: str) -> str:
    escaped = html.escape(value, quote=True)
    return re.sub(r"\*\*([^*\n]+)\*\*", r"<strong>\1</strong>", escaped)


def manual_html(title: str, content: str) -> str:
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
</style></head><body><h1>{safe_title}</h1>{chr(10).join(blocks)}</body></html>"""


def export_manual(title: str, content: str, state_root: Path, run=subprocess.run) -> dict[str, object]:
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

    manuals.mkdir(parents=True, exist_ok=True, mode=0o750)
    temporary = Path(tempfile.mkdtemp(prefix=f".{digest}.", dir=manuals))
    try:
        source = temporary / "manual.html"
        source.write_text(manual_html(title, content), encoding="utf-8")
        source.chmod(0o640)
        profile = state_root / "libreoffice-profile"
        profile.mkdir(parents=True, exist_ok=True, mode=0o750)
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
            artifact.chmod(0o640)
        temporary.chmod(0o750)
        temporary.rename(destination)
        return result
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _receive_exact(connection: socket.socket, length: int) -> bytes:
    chunks: list[bytes] = []
    remaining = length
    while remaining:
        chunk = connection.recv(remaining)
        if not chunk:
            raise ConnectionError("request ended before declared length")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


class ConversionHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        peer_pid, peer_uid, _peer_gid = struct.unpack(
            "3i", self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        )
        del peer_pid
        if peer_uid != self.server.allowed_uid:
            return
        try:
            length = struct.unpack("!I", _receive_exact(self.request, 4))[0]
            if length > MAX_REQUEST:
                raise ValueError("request is too large")
            request = json.loads(_receive_exact(self.request, length))
            if not isinstance(request, dict) or set(request) != {"title", "content"}:
                raise ValueError("request must contain exactly title and content")
            result = export_manual(request["title"], request["content"], self.server.state_root)
            response = {"ok": True, "result": result}
        except Exception as error:
            response = {"ok": False, "error": str(error)}
        payload = json.dumps(response, sort_keys=True).encode("utf-8")
        self.request.sendall(struct.pack("!I", len(payload)) + payload)


class ConversionServer(socketserver.UnixStreamServer):
    def __init__(self, path: str, state_root: Path, allowed_uid: int):
        self.state_root = state_root
        self.allowed_uid = allowed_uid
        super().__init__(path, ConversionHandler)


def main() -> None:
    parser = argparse.ArgumentParser(description="ORCA local LibreOffice conversion broker")
    parser.add_argument("--socket", required=True)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--allowed-peer", default="fryrocket")
    args = parser.parse_args()
    socket_path = Path(args.socket)
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    if socket_path.exists():
        metadata = socket_path.lstat()
        if not stat.S_ISSOCK(metadata.st_mode):
            raise RuntimeError("converter socket path exists and is not a socket")
        socket_path.unlink()
    server = ConversionServer(str(socket_path), args.state_dir, pwd.getpwnam(args.allowed_peer).pw_uid)
    socket_path.chmod(0o660)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        if socket_path.exists() and stat.S_ISSOCK(socket_path.lstat().st_mode):
            socket_path.unlink()


if __name__ == "__main__":
    main()
