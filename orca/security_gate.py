from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import re

from .registry import AGENTS, LANES
from .security import find_secret_match, redact_text


MAX_ARTIFACTS = 64
MAX_ARTIFACT_BYTES = 256_000
MAX_TOTAL_BYTES = 1_000_000


@dataclass(frozen=True)
class SecurityFinding:
    check_id: str
    severity: str
    artifact: str
    summary: str
    evidence: str
    remediation: str
    fingerprint: str


@dataclass(frozen=True)
class SecurityReport:
    author: str
    lane: str
    disposition: str
    findings: tuple[SecurityFinding, ...]
    advisory_only: bool = True
    engine: str = "deterministic-v2"

    def snapshot(self) -> dict:
        return {
            "author": self.author,
            "lane": self.lane,
            "disposition": self.disposition,
            "findings": [asdict(finding) for finding in self.findings],
            "advisory_only": self.advisory_only,
            "engine": self.engine,
        }


@dataclass(frozen=True)
class _Check:
    id: str
    severity: str
    summary: str
    remediation: str
    pattern: re.Pattern[str]
    artifact_pattern: re.Pattern[str] | None = None


_SECRET_CHECK = _Check(
    "secret-shaped-value", "S3", "Secret-shaped value is present",
    "Remove the value, rotate the credential if it was real, and use an approved secret store.",
    re.compile(r"$^"),
)


_MISSING_JS_LOCKFILE = _Check(
    "missing-js-lockfile", "S1", "JavaScript dependency manifest has no supplied lockfile",
    "Include the repository lockfile in review, verify it is current, and use the package manager's frozen-lockfile mode.",
    re.compile(r"$^"),
)


_MISSING_PYTHON_LOCKFILE = _Check(
    "missing-python-lockfile", "S1", "Python dependency manifest has no supplied lockfile",
    "Include a reviewed lock or fully pinned requirements file and verify hashes or provenance before release.",
    re.compile(r"$^"),
)


_CHECKS = (
    _Check(
        "privileged-container", "S2", "Privileged container mode is enabled",
        "Remove privileged mode and grant only the specific capabilities the workload requires.",
        re.compile(r"(?im)(?:^\s*privileged\s*:\s*true\b|[\"']privileged[\"']\s*:\s*true\b)"),
    ),
    _Check(
        "tls-verification-disabled", "S2", "TLS certificate verification is disabled",
        "Restore certificate verification and configure the required CA trust explicitly.",
        re.compile(
            r"(?im)(?:\b(?:verify|tls_verify|ssl_verify)\s*[:=]\s*(?:false|0|no)\b|"
            r"\bcurl\b[^\n]*?(?:\s-k\b|\s--insecure\b))"
        ),
    ),
    _Check(
        "world-writable-permissions", "S2", "World-writable permissions are requested",
        "Use the narrowest owner, group, and mode required by the workload.",
        re.compile(r"(?i)\bchmod\s+(?:-R\s+)?(?:0?777)\b"),
    ),
    _Check(
        "download-piped-to-shell", "S2", "Downloaded content is piped directly to a shell",
        "Download a pinned artifact, verify its digest or signature, inspect it, then execute separately.",
        re.compile(r"(?i)\b(?:curl|wget)\b[^\n|]*\|\s*(?:sudo\s+)?(?:sh|bash|zsh)\b"),
    ),
    _Check(
        "remote-docker-add", "S2", "Docker build adds an unverified remote artifact",
        "Fetch the artifact separately, verify a pinned digest or signature, and COPY the verified local file.",
        re.compile(r"(?im)^\s*ADD\s+https?://[^\s]+"),
    ),
    _Check(
        "mutable-ci-action-reference", "S2", "CI action uses a mutable branch reference",
        "Pin third-party CI actions to a reviewed full commit SHA and record the upstream release provenance.",
        re.compile(
            r"(?im)^\s*(?:-\s*)?uses\s*:\s*[\"']?[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@"
            r"(?:main|master|latest|head|dev|develop)\b"
        ),
    ),
    _Check(
        "workflow-write-all", "S2", "CI workflow grants write-all permissions",
        "Declare the minimum per-scope permissions and keep untrusted jobs read-only.",
        re.compile(r"(?im)^\s*permissions\s*:\s*[\"']?write-all[\"']?\s*(?:#.*)?$"),
    ),
    _Check(
        "branch-protection-disabled", "S2", "Repository branch protection is explicitly disabled",
        "Require protected release branches, independent review, and approved status checks before merge.",
        re.compile(r"(?im)^\s*branch[_-]?protection\s*[:=]\s*(?:false|0|no|null)\b"),
    ),
    _Check(
        "required-status-checks-disabled", "S2", "Required repository status checks are disabled or empty",
        "Configure named required checks and independently verify branch-protection state before release.",
        re.compile(
            r"(?im)^\s*required[_-]?status[_-]?checks\s*[:=]\s*"
            r"(?:false|no|null|\[\s*\])\s*(?:#.*)?$"
        ),
    ),
    _Check(
        "wildcard-network-bind", "S1", "Service binds to every network interface",
        "Bind to loopback or an explicit approved interface and document the required exposure.",
        re.compile(
            r"(?im)(?:\b(?:host|bind|listen(?:_address)?)\s*[:=]\s*[\"']?(?:0\.0\.0\.0|::)[\"']?|"
            r"--(?:host|bind)\s+(?:0\.0\.0\.0|::)\b)"
        ),
    ),
    _Check(
        "mutable-container-tag", "S1", "Container image uses the mutable latest tag",
        "Pin the image to a reviewed immutable digest and retain its provenance evidence.",
        re.compile(
            r"(?im)^\s*(?:(?:image\s*:\s*)|(?:FROM\s+(?:--platform=\S+\s+)?))"
            r"[\"']?[A-Za-z0-9./_-]+:latest\b"
        ),
    ),
    _Check(
        "unpinned-python-requirement", "S1", "Python dependency is not exactly pinned",
        "Resolve the dependency to an exact reviewed version and require hashes or equivalent lock provenance.",
        re.compile(
            r"(?im)^[ \t]*(?![#-])"
            r"[A-Za-z0-9][A-Za-z0-9_.-]*(?:\[[^\]\n]+\])?[ \t]*"
            r"(?:(?:>=|<=|~=|!=|>|<)[^#\n]*)?(?:[ \t]*(?:#.*)?)$"
        ),
        re.compile(
            r"(?i)(?:^|/)(?:requirements(?:[-_.][^/]*)?|constraints(?:[-_.][^/]*)?)\.txt$"
        ),
    ),
)


def _evidence_excerpt(content: str, match: re.Match[str]) -> str:
    excerpt = " ".join(content[match.start():match.end()].split())
    return redact_text(excerpt)[:240]


def _fingerprint(*, lane: str, artifact: str, check_id: str, evidence: str) -> str:
    material = f"{lane}|{artifact}|{check_id}|{evidence[:80]}"
    return sha256(material.encode()).hexdigest()


def _finding(*, check: _Check, lane: str, artifact: str, evidence: str) -> SecurityFinding:
    safe_evidence = redact_text(evidence)[:240]
    return SecurityFinding(
        check_id=check.id,
        severity=check.severity,
        artifact=artifact,
        summary=check.summary,
        evidence=safe_evidence,
        remediation=check.remediation,
        fingerprint=_fingerprint(
            lane=lane, artifact=artifact, check_id=check.id, evidence=safe_evidence),
    )


def _directory(name: str) -> str:
    normalized = name.replace("\\", "/").lower()
    return normalized.rsplit("/", 1)[0] + "/" if "/" in normalized else ""


class IndependentSecurityGate:
    """Tool-free advisory scanner with no author, approval, or deployment authority."""

    def scan(self, *, author: str, lane: str, artifacts: dict[str, str]) -> SecurityReport:
        if author not in AGENTS:
            raise ValueError("security scan requires a registered author")
        if author == "security_gate":
            raise PermissionError("the security gate cannot review its own work")
        if lane not in LANES:
            raise ValueError(f"unknown project lane: {lane}")
        if not isinstance(artifacts, dict) or not artifacts:
            raise ValueError("security scan requires at least one named artifact")
        if len(artifacts) > MAX_ARTIFACTS:
            raise ValueError("security scan exceeds the artifact count limit")

        findings: list[SecurityFinding] = []
        validated: list[tuple[str, str, str]] = []
        total_bytes = 0
        for raw_name, content in sorted(artifacts.items()):
            if not isinstance(raw_name, str) or not raw_name.strip() or not isinstance(content, str):
                raise ValueError("security artifacts must map non-empty names to text")
            if (len(raw_name) > 240 or "\x00" in raw_name or "\x00" in content
                    or any(ord(character) < 32 or ord(character) == 127 for character in raw_name)):
                raise ValueError("security artifact name or content is not valid text")
            artifact_bytes = len(content.encode("utf-8"))
            total_bytes += artifact_bytes
            if artifact_bytes > MAX_ARTIFACT_BYTES or total_bytes > MAX_TOTAL_BYTES:
                raise ValueError("security scan exceeds the artifact size limit")
            artifact = redact_text(raw_name.strip())
            validated.append((raw_name, artifact, content))
            checks_and_matches = []
            secret_match = find_secret_match(content)
            if secret_match is not None:
                checks_and_matches.append((_SECRET_CHECK, secret_match))
            checks_and_matches.extend(
                (check, match) for check in _CHECKS
                if check.artifact_pattern is None or check.artifact_pattern.search(raw_name)
                if (match := check.pattern.search(content)) is not None
            )
            for check, match in checks_and_matches:
                evidence = _evidence_excerpt(content, match)
                findings.append(_finding(
                    check=check, lane=lane, artifact=artifact, evidence=evidence))

        normalized_names = {raw_name.replace("\\", "/").lower()
                            for raw_name, _, _ in validated}
        for raw_name, artifact, content in validated:
            normalized = raw_name.replace("\\", "/").lower()
            directory = _directory(raw_name)
            if (normalized.endswith("package.json")
                    and re.search(
                        r'(?i)"(?:dependencies|devDependencies|optionalDependencies)"\s*:',
                        content)):
                lockfiles = {
                    f"{directory}package-lock.json", f"{directory}npm-shrinkwrap.json",
                    f"{directory}pnpm-lock.yaml", f"{directory}yarn.lock",
                    f"{directory}bun.lock", f"{directory}bun.lockb",
                }
                if normalized_names.isdisjoint(lockfiles):
                    findings.append(_finding(
                        check=_MISSING_JS_LOCKFILE, lane=lane, artifact=artifact,
                        evidence="package.json supplied without a same-directory lockfile",
                    ))
            if (normalized.endswith("pyproject.toml")
                    and re.search(r"(?im)^\s*(?:dependencies\s*=\s*\[|\[tool\.poetry\.dependencies\])", content)):
                lockfiles = {
                    f"{directory}uv.lock", f"{directory}poetry.lock",
                    f"{directory}pdm.lock", f"{directory}requirements.lock",
                }
                if normalized_names.isdisjoint(lockfiles):
                    findings.append(_finding(
                        check=_MISSING_PYTHON_LOCKFILE, lane=lane, artifact=artifact,
                        evidence="pyproject.toml dependency declaration supplied without a same-directory lockfile",
                    ))

        disposition = (
            "block_and_escalate"
            if any(finding.severity in {"S2", "S3"} for finding in findings)
            else "review" if findings else "pass"
        )
        return SecurityReport(
            author=author, lane=lane, disposition=disposition, findings=tuple(findings))
