from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class BotDefinition:
    id: str
    name: str
    duty: str
    task_types: tuple[str, ...]
    lanes: tuple[str, ...]
    model_route: str
    may_execute_tools: bool = False
    runtime_enabled: bool = False
    output_contract: str = "evidence-backed result with uncertainty and next gate"


CORE_BOTS = {
    "orca": BotDefinition(
        "orca", "ORCA", "policy, routing, approvals and lane isolation",
        ("orchestration",),
        ("forge", "bgm", "inventory", "cloudflare", "aws", "pccg", "orca"),
        "orchestration",
    ),
    "smith": BotDefinition(
        "smith", "SMITH", "coding and implementation",
        ("coding", "documentation", "operations_plan"),
        ("forge", "bgm", "inventory", "cloudflare", "aws", "pccg", "orca"),
        "coding",
    ),
    "quench": BotDefinition(
        "quench", "QUENCH", "independent technical review and verification",
        ("review", "security_review", "verification"),
        ("forge", "bgm", "inventory", "cloudflare", "aws", "pccg", "orca"),
        "review",
    ),
    "security_gate": BotDefinition(
        "security_gate", "Independent Security Gate",
        "advisory security review, findings and escalation",
        ("security_gate", "dependency_scan", "secret_scan", "configuration_review"),
        ("forge", "bgm", "inventory", "cloudflare", "aws", "pccg", "orca"),
        "review",
    ),
}


# Historical seats are recorded for migration review, not activated. Promoting
# one changes the stable identity roster and therefore requires a documented
# decision and updated capability tests.
MIGRATION_CANDIDATES = {
    "ampere": {
        "name": "AMPERE",
        "legacy_duty": "electronics design lead",
        "status": "candidate",
    },
    "relay": {
        "name": "RELAY",
        "legacy_duty": "embedded firmware and bring-up",
        "status": "candidate",
    },
}


BOT_BUILD_QUEUE = (
    {"order": 1, "item": "persist bot, job and approval state transactionally", "status": "complete"},
    {"order": 2, "item": "define versioned prompt and output contracts", "status": "complete"},
    {"order": 3, "item": "add deny-by-default tool capability manifests", "status": "complete"},
    {"order": 4, "item": "build sandboxed local-model adapters with zero cloud budget", "status": "complete"},
    {"order": 5, "item": "add offline evaluation fixtures for routing, evidence and refusal", "status": "complete"},
    {"order": 6, "item": "decide AMPERE and RELAY migration or replacement", "status": "decision_required"},
    {"order": 7, "item": "design independent security bot without merge or deploy authority", "status": "complete"},
)


class BotRegistry:
    def __init__(self, bots: dict[str, BotDefinition] | None = None) -> None:
        self.bots = bots or dict(CORE_BOTS)
        self.paused: set[str] = set()

    def route(self, task_type: str, lane: str) -> BotDefinition:
        matches = [bot for bot in self.bots.values()
                   if task_type in bot.task_types and lane in bot.lanes]
        if len(matches) != 1:
            raise ValueError(f"task route must resolve to exactly one bot: {task_type}/{lane}")
        bot = matches[0]
        if bot.id in self.paused:
            raise PermissionError(f"bot is paused: {bot.id}")
        return bot

    def snapshot(self) -> list[dict]:
        rows = []
        for bot in self.bots.values():
            row = asdict(bot)
            row["paused"] = bot.id in self.paused
            rows.append(row)
        return rows
