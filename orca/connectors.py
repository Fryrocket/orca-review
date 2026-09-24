from __future__ import annotations

from dataclasses import asdict, dataclass

from .domain import PermissionLevel, new_id, utc_now
from .registry import CONNECTORS
from .security import redact_text


@dataclass(frozen=True)
class ConnectorCapability:
    connector: str
    operations: tuple[str, ...]
    writes_enabled: bool = False


@dataclass(frozen=True)
class ConnectorRequest:
    id: str
    connector: str
    operation: str
    resource: str
    level: PermissionLevel
    created_at: str


@dataclass(frozen=True)
class ConnectorActionRule:
    operation: str
    level: PermissionLevel
    mutates: bool
    rationale: str


READ_ONLY_CAPABILITIES = {
    connector_id: ConnectorCapability(connector_id, ("get", "list", "search", "read"))
    for connector_id in CONNECTORS
}


def _read_rules() -> dict[str, ConnectorActionRule]:
    return {
        operation: ConnectorActionRule(operation, PermissionLevel.R0, False, "read-only observation")
        for operation in ("get", "list", "search", "read")
    }


CONNECTOR_ACTIONS = {
    "notion": {**_read_rules(),
               "create": ConnectorActionRule("create", PermissionLevel.R2, True, "durable knowledge write"),
               "update": ConnectorActionRule("update", PermissionLevel.R2, True, "durable knowledge change"),
               "publish": ConnectorActionRule("publish", PermissionLevel.R3, True, "publication requires Fry"),
               "delete": ConnectorActionRule("delete", PermissionLevel.R3, True, "destructive action")},
    "linear": {**_read_rules(),
               "create": ConnectorActionRule("create", PermissionLevel.R2, True, "work-system write"),
               "update": ConnectorActionRule("update", PermissionLevel.R2, True, "work-system change"),
               "close": ConnectorActionRule("close", PermissionLevel.R2, True, "workflow state change"),
               "delete": ConnectorActionRule("delete", PermissionLevel.R3, True, "destructive action")},
    "github": {**_read_rules(),
               "create_branch": ConnectorActionRule("create_branch", PermissionLevel.R2, True, "repository state change"),
               "commit": ConnectorActionRule("commit", PermissionLevel.R2, True, "repository state change"),
               "open_pr": ConnectorActionRule("open_pr", PermissionLevel.R2, True, "review workflow write"),
               "push": ConnectorActionRule("push", PermissionLevel.R3, True, "push remains Fry-gated"),
               "merge": ConnectorActionRule("merge", PermissionLevel.R3, True, "merge remains Fry-gated"),
               "delete": ConnectorActionRule("delete", PermissionLevel.R3, True, "destructive action")},
    "gitea": {**_read_rules(),
              "create_branch": ConnectorActionRule("create_branch", PermissionLevel.R2, True, "repository state change"),
              "commit": ConnectorActionRule("commit", PermissionLevel.R2, True, "repository state change"),
              "open_pr": ConnectorActionRule("open_pr", PermissionLevel.R2, True, "review workflow write"),
              "push": ConnectorActionRule("push", PermissionLevel.R3, True, "push remains Fry-gated"),
              "merge": ConnectorActionRule("merge", PermissionLevel.R3, True, "merge remains Fry-gated"),
              "delete": ConnectorActionRule("delete", PermissionLevel.R3, True, "destructive action")},
    "slack": {**_read_rules(),
              "post": ConnectorActionRule("post", PermissionLevel.R2, True, "coordination message write"),
              "send_alert": ConnectorActionRule("send_alert", PermissionLevel.R2, True, "incident notification write"),
              "publish_external": ConnectorActionRule("publish_external", PermissionLevel.R3, True, "external publication"),
              "delete": ConnectorActionRule("delete", PermissionLevel.R3, True, "destructive action")},
    "drive": {**_read_rules(),
              "upload": ConnectorActionRule("upload", PermissionLevel.R2, True, "artifact write"),
              "update": ConnectorActionRule("update", PermissionLevel.R2, True, "artifact replacement"),
              "share_public": ConnectorActionRule("share_public", PermissionLevel.R3, True, "public sharing"),
              "delete": ConnectorActionRule("delete", PermissionLevel.R3, True, "destructive action")},
    "cloudflare": {**_read_rules(),
                   "change_dns": ConnectorActionRule("change_dns", PermissionLevel.R3, True, "external edge change"),
                   "change_tunnel": ConnectorActionRule("change_tunnel", PermissionLevel.R3, True, "external edge change"),
                   "change_access": ConnectorActionRule("change_access", PermissionLevel.R3, True, "access-control change"),
                   "deploy": ConnectorActionRule("deploy", PermissionLevel.R3, True, "external deployment")},
}


class ConnectorGateway:
    def __init__(self, capabilities: dict[str, ConnectorCapability] | None = None) -> None:
        self.capabilities = capabilities or dict(READ_ONLY_CAPABILITIES)

    def prepare(self, *, connector: str, operation: str, resource: str) -> ConnectorRequest:
        if (not isinstance(resource, str) or not resource.strip() or len(resource) > 2_000
                or redact_text(resource) != resource):
            raise ValueError("connector resource must be bounded text without secret-shaped data")
        capability = self.capabilities.get(connector)
        if capability is None:
            raise PermissionError(f"unknown connector denied: {connector}")
        rule = self.classify_action(connector=connector, operation=operation)
        if rule.mutates or operation not in capability.operations:
            raise PermissionError(f"connector write disabled: {connector}/{operation}")
        if capability.writes_enabled:
            raise RuntimeError("read-only gateway cannot expose write-enabled capability")
        return ConnectorRequest(new_id("connector"), connector, operation, resource.strip(),
                                rule.level, utc_now())

    def classify_action(self, *, connector: str, operation: str) -> ConnectorActionRule:
        if connector not in CONNECTOR_ACTIONS:
            raise PermissionError(f"unknown connector denied: {connector}")
        try:
            return CONNECTOR_ACTIONS[connector][operation]
        except KeyError as exc:
            raise PermissionError(f"connector operation denied: {connector}/{operation}") from exc

    def snapshot(self) -> list[dict]:
        rows = []
        for connector, capability in self.capabilities.items():
            row = asdict(capability)
            row["declared_actions"] = [
                {**asdict(rule), "level": rule.level.name}
                for rule in CONNECTOR_ACTIONS[connector].values()
            ]
            rows.append(row)
        return rows
