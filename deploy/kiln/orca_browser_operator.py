#!/usr/bin/env python3
"""Fail-closed Browser Operator plan validator; it never performs web actions."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

MAX_INPUT_BYTES = 256_000
MAX_TASKS = 30
ALLOWED_ACTIONS = {"navigate", "read_page", "download", "prepare_form", "stage_upload"}
DOWNLOAD_SUFFIXES = {".pdf", ".csv", ".txt", ".png", ".jpg", ".jpeg", ".zip"}
UPLOAD_ROOT = Path("/home/fryrocket/ORCA Projects")
SECRET_PATTERNS = (
    re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"\b(xai-|sk-)[A-Za-z0-9_-]{12,}"),
    re.compile(
        r"\b(?:github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|"
        r"xox[baprs]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{30,}|"
        r"(?:AKIA|ASIA)[A-Z0-9]{16})\b"
    ),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(api[_ -]?key|token|password|secret)\s*[:=]\s*[^\s,;]{8,}"),
)


def _contains_secret(value):
    return any(pattern.search(value) for pattern in SECRET_PATTERNS)


def _text(value, name, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"invalid {name}")
    cleaned = value.strip()
    if _contains_secret(cleaned):
        raise ValueError(f"{name} contains secret-shaped data")
    return cleaned


def _url(value):
    text = _text(value, "URL", 2_048)
    if re.search(r"[\s\\]", text):
        raise ValueError("invalid URL")
    try:
        parsed = urlsplit(text)
        port = parsed.port
    except ValueError:
        raise ValueError("invalid URL") from None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("invalid URL")
    if parsed.username or parsed.password or (port is not None and not 1 <= port <= 65535):
        raise ValueError("URL credentials or port are invalid")
    host = parsed.hostname.casefold()
    if parsed.scheme == "http" and host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("public browser tasks require HTTPS")
    try:
        address = ipaddress.ip_address(host)
        if not address.is_loopback:
            raise ValueError("literal public IP addresses are not allowed")
    except ValueError as exc:
        if str(exc) == "literal public IP addresses are not allowed":
            raise
    return text


def _fields(value):
    if not isinstance(value, list) or len(value) > 50:
        raise ValueError("invalid form fields")
    fields, names = [], set()
    for row in value:
        if not isinstance(row, dict) or set(row) != {"name", "value"}:
            raise ValueError("invalid form field schema")
        name = _text(row.get("name"), "field name", 120)
        field_value = _text(row.get("value"), "field value", 1_000)
        if name in names:
            raise ValueError("duplicate form field")
        names.add(name)
        fields.append({"name": name, "value": field_value})
    return fields


def _task(row):
    if not isinstance(row, dict) or set(row) != {"id", "action", "url", "details"}:
        raise ValueError("invalid browser task schema")
    task_id = _text(row.get("id"), "task id", 80)
    action = row.get("action")
    if action not in ALLOWED_ACTIONS:
        raise ValueError("unsupported browser action")
    url = _url(row.get("url"))
    details = row.get("details")
    if not isinstance(details, dict):
        raise ValueError("invalid browser task details")
    prepared = {}
    if action in {"navigate", "read_page"}:
        if details:
            raise ValueError("navigation details must be empty")
        execution = "private_ephemeral_browser"
    elif action == "download":
        if set(details) != {"filename", "expected_sha256", "max_bytes"}:
            raise ValueError("invalid download details")
        filename = _text(details.get("filename"), "download filename", 180)
        if Path(filename).name != filename or Path(filename).suffix.casefold() not in DOWNLOAD_SUFFIXES:
            raise ValueError("download type is not allowlisted")
        digest = details.get("expected_sha256")
        if digest is not None and (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest)):
            raise ValueError("invalid expected download digest")
        maximum = details.get("max_bytes")
        if type(maximum) is not int or not 1 <= maximum <= 50_000_000:
            raise ValueError("invalid download size limit")
        prepared = {"filename": filename, "expected_sha256": digest, "max_bytes": maximum}
        execution = "approval_required_before_download"
    elif action == "prepare_form":
        if set(details) != {"fields"}:
            raise ValueError("invalid form details")
        prepared = {"fields": _fields(details.get("fields"))}
        execution = "prepare_only_submission_prohibited"
    else:
        if set(details) != {"path", "sha256"}:
            raise ValueError("invalid upload details")
        path_text = _text(details.get("path"), "upload path", 1_000)
        path = Path(path_text)
        try:
            path.relative_to(UPLOAD_ROOT)
        except ValueError:
            raise ValueError("upload path is outside ORCA Projects") from None
        digest = details.get("sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            raise ValueError("invalid upload digest")
        prepared = {"path": str(path), "sha256": digest.lower()}
        execution = "stage_only_upload_prohibited"
    return {
        "id": task_id, "action": action, "url": url, "details": prepared,
        "state": "prepared_requires_policy_execution", "execution": execution,
    }


def evaluate(data, now=None):
    if not isinstance(data, dict) or set(data) != {
            "allow_external_actions", "profile", "tasks"}:
        raise ValueError("invalid browser plan schema")
    if data.get("allow_external_actions") is not False:
        raise ValueError("external-action boundary missing")
    if data.get("profile") != "orca-private-ephemeral":
        raise ValueError("unapproved browser profile")
    tasks = data.get("tasks")
    if not isinstance(tasks, list) or not tasks or len(tasks) > MAX_TASKS:
        raise ValueError("browser tasks missing or oversized")
    prepared, ids = [], set()
    for row in tasks:
        task = _task(row)
        if task["id"] in ids:
            raise ValueError("duplicate browser task")
        ids.add(task["id"])
        prepared.append(task)
    digest = hashlib.sha256(json.dumps(prepared, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "schema_version": 1, "bot_id": "browser_operator", "state": "healthy",
        "mode": "validated_browser_plan_not_executed",
        "observed_epoch": int(time.time() if now is None else now),
        "authority": "validate_and_stage_browser_tasks",
        "profile": "orca-private-ephemeral", "tasks": prepared,
        "plan_sha256": digest,
        "approval_gates": {
            "download": "required", "submit_form": "required",
            "upload": "required", "purchase": "prohibited", "publish": "required",
            "send_message": "required", "change_account": "required",
            "credential_entry": "required",
        },
        "pages_opened": 0, "pages_read": 0, "downloads_started": 0,
        "forms_submitted": 0, "uploads_started": 0, "purchases": 0,
        "messages_sent": 0, "publications": 0, "account_changes": 0,
        "credentials_read": 0, "external_actions": 0,
    }


def waiting_report(now=None):
    report = {
        "schema_version": 1, "bot_id": "browser_operator", "state": "healthy",
        "mode": "waiting_for_approved_browser_plan",
        "observed_epoch": int(time.time() if now is None else now),
        "authority": "validate_and_stage_browser_tasks", "profile": "orca-private-ephemeral",
        "tasks": [], "approval_gates": {},
    }
    for key in ("pages_opened", "pages_read", "downloads_started", "forms_submitted",
                "uploads_started", "purchases", "messages_sent", "publications",
                "account_changes", "credentials_read", "external_actions"):
        report[key] = 0
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="/var/lib/orca-browser-input/approved-plan.json")
    parser.add_argument("--output", default="/var/lib/orca-browser-operator/status.json")
    args = parser.parse_args()
    try:
        source = Path(args.input)
        if source.exists() and source.stat().st_size > MAX_INPUT_BYTES:
            raise ValueError("approved browser plan is oversized")
        report = evaluate(json.loads(source.read_text())) if source.exists() else waiting_report()
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        report = waiting_report()
        report.update({"state": "degraded", "mode": "invalid_approved_browser_plan",
                       "error": type(exc).__name__})
    target = Path(args.output)
    target.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, sort_keys=True) + "\n")
    os.chmod(temporary, 0o640)
    os.replace(temporary, target)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["state"] == "healthy" else 1


if __name__ == "__main__":
    raise SystemExit(main())
