#!/usr/bin/env python3
"""Fleet Viewer — local web UI aggregating GitHub, Google Drive, and Gitea.

Runs on ANVIL, binds to localhost only. Auto-refreshes every 30 seconds.

Endpoints:
    GET /files          -> merged file list from all sources
    GET /file?src=&path= -> content of a single file
    GET /               -> the HTML UI

Config: deploy/fleet-viewer/config.json (see config.example.json)
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"


def load_config() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return {
        "github": {"token": "", "owner": "Fryrocket"},
        "gitea": {"url": "", "token": ""},
        "drive": {"credentials_path": ""},
        "port": 8787,
        "refresh_seconds": 30,
    }


CFG = load_config()


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------

def github_list(path: str = "") -> list[dict]:
    token = CFG["github"]["token"]
    owner = CFG["github"]["owner"]
    url = f"https://api.github.com/repos/{owner}/orca-review/contents/{path}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "fleet-viewer",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode())
    except Exception as e:
        return [{"source": "github", "error": str(e)}]
    if isinstance(data, dict):
        data = [data]
    out = []
    for item in data:
        out.append({
            "source": "github",
            "name": item["name"],
            "path": item["path"],
            "type": item["type"],
            "size": item.get("size", 0),
            "sha": item.get("sha", ""),
        })
    return out


def github_file(path: str) -> dict:
    token = CFG["github"]["token"]
    owner = CFG["github"]["owner"]
    url = f"https://api.github.com/repos/{owner}/orca-review/contents/{urllib.parse.quote(path)}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "fleet-viewer",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            item = json.loads(r.read().decode())
        content = base64.b64decode(item["content"]).decode("utf-8", errors="replace")
        return {"source": "github", "path": item["path"], "content": content,
                "encoding": "utf-8", "size": item.get("size", 0)}
    except Exception as e:
        return {"source": "github", "error": str(e)}


# ---------------------------------------------------------------------------
# Google Drive
# ---------------------------------------------------------------------------

_DRIVE_TOKEN = None
_DRIVE_TOKEN_EXP = 0


def _drive_access_token() -> str:
    global _DRIVE_TOKEN, _DRIVE_TOKEN_EXP
    if _DRIVE_TOKEN and time.time() < _DRIVE_TOKEN_EXP - 60:
        return _DRIVE_TOKEN
    creds_path = CFG["drive"].get("credentials_path") or ""
    if not creds_path or not Path(creds_path).exists():
        return ""
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
        creds = service_account.Credentials.from_service_account_file(
            creds_path,
            scopes=["https://www.googleapis.com/auth/drive.readonly"],
        )
        creds.refresh(Request())
        _DRIVE_TOKEN = creds.token
        _DRIVE_TOKEN_EXP = time.time() + 3500
        return _DRIVE_TOKEN
    except Exception:
        return ""


def drive_list(folder_id: str = "root") -> list[dict]:
    token = _drive_access_token()
    if not token:
        return [{"source": "drive", "error": "no drive credentials configured"}]
    q = f"'{folder_id}' in parents and trashed = false"
    params = urllib.parse.urlencode({"q": q, "fields": "files(id,name,mimeType,size,modifiedTime)", "pageSize": 200})
    url = f"https://www.googleapis.com/drive/v3/files?{params}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode())
    except Exception as e:
        return [{"source": "drive", "error": str(e)}]
    out = []
    for f in data.get("files", []):
        out.append({
            "source": "drive",
            "name": f["name"],
            "path": f["id"],
            "type": "folder" if "folder" in f["mimeType"] else "file",
            "size": int(f.get("size") or 0),
            "modified": f.get("modifiedTime", ""),
        })
    return out


def drive_file(file_id: str) -> dict:
    token = _drive_access_token()
    if not token:
        return {"source": "drive", "error": "no drive credentials configured"}
    # Try export as text for Google Docs/Sheets/Slides
    meta_url = f"https://www.googleapis.com/drive/v3/files/{file_id}?fields=id,name,mimeType"
    req = urllib.request.Request(meta_url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            meta = json.loads(r.read().decode())
    except Exception as e:
        return {"source": "drive", "error": str(e)}
    mime = meta.get("mimeType", "")
    export_map = {
        "application/vnd.google-apps.document": "text/plain",
        "application/vnd.google-apps.spreadsheet": "text/csv",
        "application/vnd.google-apps.presentation": "text/plain",
    }
    if mime in export_map:
        url = f"https://www.googleapis.com/drive/v3/files/{file_id}/export?mimeType={urllib.parse.quote(export_map[mime])}"
    else:
        url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            content = r.read().decode("utf-8", errors="replace")
        return {"source": "drive", "path": meta["name"], "content": content,
                "encoding": "utf-8", "size": len(content)}
    except Exception as e:
        return {"source": "drive", "error": str(e)}


# ---------------------------------------------------------------------------
# Gitea
# ---------------------------------------------------------------------------

def gitea_list(path: str = "") -> list[dict]:
    base = CFG["gitea"].get("url", "").rstrip("/")
    token = CFG["gitea"].get("token", "")
    if not base or not token:
        return [{"source": "gitea", "error": "gitea not configured"}]
    url = f"{base}/api/v1/repos/search?limit=50"
    req = urllib.request.Request(url, headers={
        "Authorization": f"token {token}",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode())
    except Exception as e:
        return [{"source": "gitea", "error": str(e)}]
    out = []
    for repo in data.get("data", []):
        out.append({
            "source": "gitea",
            "name": repo["name"],
            "path": repo["full_name"],
            "type": "repo",
            "size": 0,
            "default_branch": repo.get("default_branch", "main"),
        })
    return out


def gitea_file(repo: str, path: str, branch: str = "main") -> dict:
    base = CFG["gitea"].get("url", "").rstrip("/")
    token = CFG["gitea"].get("token", "")
    url = f"{base}/api/v1/repos/{urllib.parse.quote(repo)}/contents/{urllib.parse.quote(path)}?ref={urllib.parse.quote(branch)}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"token {token}",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            item = json.loads(r.read().decode())
        content = base64.b64decode(item["content"]).decode("utf-8", errors="replace")
        return {"source": "gitea", "path": item["path"], "content": content,
                "encoding": "utf-8", "size": item.get("size", 0)}
    except Exception as e:
        return {"source": "gitea", "error": str(e)}


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

HTML_PATH = Path(__file__).resolve().parent / "index.html"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # quiet

    def _send(self, code: int, body: bytes, content_type: str = "application/json"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/" or parsed.path == "/index.html":
            if HTML_PATH.exists():
                body = HTML_PATH.read_bytes()
                self._send(200, body, "text/html; charset=utf-8")
            else:
                self._send(404, b"index.html missing")
            return
        if parsed.path == "/files":
            qs = urllib.parse.parse_qs(parsed.query)
            src = qs.get("src", ["all"])[0]
            results = []
            if src in ("all", "github"):
                results.extend(github_list())
            if src in ("all", "drive"):
                results.extend(drive_list())
            if src in ("all", "gitea"):
                results.extend(gitea_list())
            self._send(200, json.dumps(results).encode())
            return
        if parsed.path == "/file":
            qs = urllib.parse.parse_qs(parsed.query)
            src = qs.get("src", [""])[0]
            path = qs.get("path", [""])[0]
            if src == "github":
                self._send(200, json.dumps(github_file(path)).encode())
            elif src == "drive":
                self._send(200, json.dumps(drive_file(path)).encode())
            elif src == "gitea":
                repo = qs.get("repo", [""])[0]
                branch = qs.get("branch", ["main"])[0]
                self._send(200, json.dumps(gitea_file(repo, path, branch)).encode())
            else:
                self._send(400, json.dumps({"error": "missing src"}).encode())
            return
        self._send(404, b"not found")


def main():
    port = int(CFG.get("port", 8787))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Fleet Viewer running on http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
        server.server_close()


if __name__ == "__main__":
    main()
