from __future__ import annotations

from html.parser import HTMLParser
from ipaddress import ip_address
import json
from pathlib import Path
import socket
import stat
import subprocess
from urllib.parse import parse_qs, quote, urlencode, urlparse
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen


def _public_url(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 2_000:
        raise ValueError("web URL must be bounded text")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("web URL must use HTTP or HTTPS")
    if parsed.username or parsed.password or parsed.port not in {None, 80, 443}:
        raise PermissionError("web URL credentials and nonstandard ports are denied")
    addresses = {
        ip_address(item[4][0])
        for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    }
    if not addresses or any(not address.is_global for address in addresses):
        raise PermissionError("web URL must resolve only to public addresses")
    return value


def _default_text_transport(url: str, headers: dict[str, str], limit: int) -> tuple[str, str]:
    request = Request(url, headers={"Accept": "text/html,text/plain,application/json", **headers})
    class NoRedirects(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, response_headers, newurl):
            return None

    try:
        response = build_opener(NoRedirects).open(request, timeout=15)
    except HTTPError as exc:
        if 300 <= exc.code < 400:
            raise PermissionError("web redirects are denied; fetch the public target explicitly") from None
        raise
    with response:
        final_url = response.geturl()
        content_type = response.headers.get_content_type()
        if not (content_type.startswith("text/") or content_type == "application/json"):
            raise ValueError("web response is not readable text")
        body = response.read(limit + 1)
    if len(body) > limit:
        raise ValueError("web response exceeds the bounded envelope")
    return final_url, body.decode("utf-8", errors="replace")


class _DuckResults(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        values = dict(attrs)
        if tag == "a" and "result-link" in values.get("class", ""):
            self._href = values.get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            href = self._href
            parsed = urlparse(href)
            if parsed.hostname and parsed.hostname.endswith("duckduckgo.com"):
                href = parse_qs(parsed.query).get("uddg", [href])[0]
            title = " ".join("".join(self._text).split())
            if title and href:
                self.results.append({"title": title[:500], "url": href[:2_000]})
            self._href = None
            self._text = []


class PublicWebReadTools:
    def __init__(self, transport=_default_text_transport) -> None:
        self.transport = transport

    def fetch(self, *, url: str) -> dict:
        safe_url = _public_url(url)
        final_url, text = self.transport(safe_url, {}, 256_000)
        return {"url": final_url, "text": text, "truncated": False}

    def search(self, *, query: str) -> dict:
        if not isinstance(query, str) or not query.strip() or len(query) > 500:
            raise ValueError("web search query must be bounded text")
        url = "https://html.duckduckgo.com/html/?" + urlencode({"q": query.strip()})
        _, html = self.transport(url, {}, 256_000)
        parser = _DuckResults()
        parser.feed(html)
        return {"query": query.strip(), "results": parser.results[:10]}

    def handlers(self) -> dict:
        return {"web.search": self.search, "web.fetch": self.fetch}


def _drive_transport(url: str, token: str, limit: int) -> tuple[str, bytes]:
    request = Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    with urlopen(request, timeout=20) as response:
        content_type = response.headers.get_content_type()
        body = response.read(limit + 1)
    if len(body) > limit:
        raise ValueError("Drive response exceeds the bounded envelope")
    return content_type, body


class GoogleDriveReadTools:
    api = "https://www.googleapis.com/drive/v3"

    def __init__(self, token_file: str | Path, transport=_drive_transport) -> None:
        path = Path(token_file)
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            raise PermissionError("Drive token file must be owner-only")
        self.token = path.read_text().strip()
        if not self.token or len(self.token) > 8_192:
            raise ValueError("Drive token is missing or invalid")
        self.transport = transport

    def _json(self, url: str) -> dict:
        _, body = self.transport(url, self.token, 512_000)
        value = json.loads(body)
        if not isinstance(value, dict):
            raise ValueError("Drive returned an invalid response")
        return value

    def search(self, *, query: str) -> dict:
        if not isinstance(query, str) or not query.strip() or len(query) > 500:
            raise ValueError("Drive search query must be bounded text")
        escaped = query.strip().replace("\\", "\\\\").replace("'", "\\'")
        params = urlencode({
            "q": f"name contains '{escaped}' and trashed = false",
            "pageSize": 20,
            "fields": "files(id,name,mimeType,modifiedTime,webViewLink)",
        })
        return self._json(f"{self.api}/files?{params}")

    def read(self, *, file_id: str) -> dict:
        if (not isinstance(file_id, str) or not file_id or len(file_id) > 256
                or not all(char.isalnum() or char in "-_" for char in file_id)):
            raise ValueError("Drive file ID is invalid")
        metadata = self._json(
            f"{self.api}/files/{quote(file_id)}?fields=id,name,mimeType,modifiedTime,webViewLink")
        mime = metadata.get("mimeType", "")
        if mime == "application/vnd.google-apps.document":
            url = f"{self.api}/files/{quote(file_id)}/export?mimeType=text%2Fplain"
        else:
            url = f"{self.api}/files/{quote(file_id)}?alt=media"
        _, body = self.transport(url, self.token, 256_000)
        return {"metadata": metadata, "text": body.decode("utf-8", errors="replace")}

    def handlers(self) -> dict:
        return {"drive.search": self.search, "drive.read": self.read}


class RcloneDriveReadTools:
    """Durable read-only Drive adapter using an owner-only rclone config."""

    def __init__(self, config_file: str | Path, *, executable: str = "/usr/bin/rclone",
                 runner=None) -> None:
        self.config_file = Path(config_file)
        mode = stat.S_IMODE(self.config_file.stat().st_mode)
        if mode & 0o077:
            raise PermissionError("rclone config must be owner-only")
        self.executable = executable
        if runner is None and not Path(executable).is_file():
            raise ValueError("rclone executable is unavailable")
        self.runner = runner or self._run

    def _run(self, arguments: list[str], limit: int = 512_000) -> str:
        process = subprocess.Popen(
            [self.executable, "--config", str(self.config_file), *arguments],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=False, env={"PATH": "/usr/bin:/bin"},
        )
        try:
            stdout, stderr = process.communicate(timeout=90)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise RuntimeError("Drive read timed out") from None
        if len(stdout) > limit or len(stderr) > 32_000:
            raise ValueError("Drive response exceeds the bounded envelope")
        if process.returncode:
            raise RuntimeError("Drive read failed")
        return stdout.decode("utf-8", errors="replace")

    def search(self, *, query: str) -> dict:
        if not isinstance(query, str) or not query.strip() or len(query) > 500:
            raise ValueError("Drive search query must be bounded text")
        raw_query = query.strip()
        if not all(char.isalnum() or char in " ._-" for char in raw_query):
            raise ValueError("Drive search query contains unsupported filename characters")
        needle = raw_query.casefold()
        output = self.runner([
            "lsjson", "--recursive", "--files-only", "--max-depth", "12",
            "--include", f"*{raw_query}*", "gdrive:",
        ])
        value = json.loads(output)
        if not isinstance(value, list):
            raise ValueError("Drive search returned an invalid response")
        matches = [
            item for item in value
            if isinstance(item, dict) and needle in str(
                item.get("Path") or item.get("Name") or ""
            ).casefold()
        ]
        return {"query": raw_query, "results": matches[:20],
                "truncated": len(matches) > 20}

    def read(self, *, path: str) -> dict:
        if (not isinstance(path, str) or not path or len(path) > 1_000
                or path.startswith("/") or ".." in Path(path).parts):
            raise ValueError("Drive path must be a bounded relative path")
        output = self.runner(["cat", f"gdrive:{path}"] , 256_000)
        return {"path": path, "text": output}

    def handlers(self) -> dict:
        return {"drive.search": self.search, "drive.read": self.read}
