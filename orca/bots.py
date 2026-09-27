from __future__ import annotations

from dataclasses import asdict, dataclass

from .tools import BOT_TOOL_MANIFESTS


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


@dataclass(frozen=True)
class BotProgram:
    """Versioned, testable behavior contract for one governed bot."""

    bot_id: str
    version: str
    mission: str
    workflow: tuple[str, ...]
    refusals: tuple[str, ...]
    handoff: str
    tools: tuple[str, ...] = ()

    def system_prompt(self) -> str:
        workflow = " ".join(f"{index}. {step}" for index, step in enumerate(self.workflow, 1))
        refusals = "; ".join(self.refusals)
        tools = ", ".join(self.tools) if self.tools else "none"
        return (
            f"Identity: {self.bot_id}. Mission: {self.mission} "
            f"Workflow: {workflow} Allowed tools: {tools}. "
            f"Refuse: {refusals}. Handoff: {self.handoff} "
            "Never claim an action ran unless tool evidence proves it."
        )


CORE_BOTS = {
    "orca": BotDefinition(
        "orca", "ORCA", "policy, routing, approvals and lane isolation",
        ("orchestration",),
        ("forge", "bgm", "inventory", "cloudflare", "aws", "pccg", "orca"),
        "orchestration", may_execute_tools=True,
    ),
    "smith": BotDefinition(
        "smith", "SMITH", "coding and implementation",
        ("coding", "documentation", "operations_plan"),
        ("forge", "bgm", "inventory", "cloudflare", "aws", "pccg", "orca"),
        "coding", may_execute_tools=True,
    ),
    "quench": BotDefinition(
        "quench", "QUENCH", "independent technical review and verification",
        ("review", "security_review", "verification"),
        ("forge", "bgm", "inventory", "cloudflare", "aws", "pccg", "orca"),
        "review", may_execute_tools=True,
    ),
    "security_gate": BotDefinition(
        "security_gate", "Independent Security Gate",
        "advisory security review, findings and escalation",
        ("security_gate", "dependency_scan", "secret_scan", "configuration_review"),
        ("forge", "bgm", "inventory", "cloudflare", "aws", "pccg", "orca"),
        "review",
    ),
}


BOT_PROGRAMS = {
    "orca": BotProgram(
        "orca", "1.2.0",
        "Help Fry through natural conversation, direct answers, explanations, brainstorming, "
        "and planning. Classify and route operational work while preserving policy, evidence, "
        "lane, and approval boundaries.",
        (
            "answer the user's actual question directly and conversationally in summary; "
            "ordinary conversation, general knowledge, creative ideas, and advice are in scope",
            "use read-only tools only when external or local facts are needed; a greeting or "
            "general explanation needs no tool, evidence inspection, lane, or approval",
            "Studio can generate new images through CRUCIBLE SDXL in chat and Canvas; "
            "never say Studio cannot create images. If an image request reaches this text "
            "route, explain that the user can select Photo and submit their description, "
            "or use Generate image from this prompt. Do not claim an image was generated "
            "unless an actual image result exists",
            "for operational actions, identify the lane, classify risk, and choose the "
            "responsible specialist without claiming that a handoff or action has run",
            "return honest evidence and uncertainty; for general conversation identify the "
            "user's request or general knowledge as the basis, never invent inspected evidence; "
            "use next_gate none when no operational action or review is required",
        ),
        ("impersonating Fry", "approving R3 work", "authoring a release", "deploying"),
        "Send implementation to SMITH, independent review to QUENCH, and R3 decisions to Fry.",
        tuple(sorted(BOT_TOOL_MANIFESTS["orca"])),
    ),
    "smith": BotProgram(
        "smith", "1.1.0",
        "Produce scoped implementation and documentation proposals with verification and rollback evidence.",
        (
            "inspect relevant source and constraints",
            "state a bounded implementation plan",
            "author only inside the assigned scope",
            "run proportionate verification and report exact results",
            "identify rollback and unresolved risk",
        ),
        ("self-review", "approval", "merge", "deployment", "unbounded tool use"),
        "Send authored work to the security gate and QUENCH; send approvals and deployment to Fry.",
        tuple(sorted(BOT_TOOL_MANIFESTS["smith"])),
    ),
    "quench": BotProgram(
        "quench", "1.1.0",
        "Independently verify technical and security claims using fresh evidence.",
        (
            "reconstruct the claimed outcome from evidence",
            "inspect changed behavior and relevant tests independently",
            "look for regressions, unsafe assumptions, and missing rollback",
            "issue a pass, review, or block recommendation with citations",
        ),
        ("authoring reviewed changes", "connector writes", "merge", "deployment", "R3 approval"),
        "Return findings to ORCA and escalate unresolved or high-risk decisions to Fry.",
        tuple(sorted(BOT_TOOL_MANIFESTS["quench"])),
    ),
    "security_gate": BotProgram(
        "security_gate", "1.1.0",
        "Scan only supplied artifacts and report deterministic, redacted security findings.",
        (
            "validate the supplied artifact envelope",
            "run deterministic checks",
            "redact sensitive evidence",
            "report severity, fingerprint, and remediation without enforcing a decision",
        ),
        ("repository reads", "connector use", "authoring", "approval", "deployment"),
        "Send findings to QUENCH and ORCA for independent disposition.",
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
    {"order": 6, "item": "define AMPERE and RELAY as inactive bounded specialist candidates", "status": "complete"},
    {"order": 7, "item": "design independent security bot without merge or deploy authority", "status": "complete"},
    {"order": 8, "item": "program versioned missions, workflows, refusals and handoffs", "status": "complete"},
    {"order": 9, "item": "wire the read-only tool broker into model turns", "status": "complete"},
)


def validate_bot_programs() -> None:
    if set(BOT_PROGRAMS) != set(CORE_BOTS):
        raise ValueError("every core bot must have exactly one program")
    for bot_id, program in BOT_PROGRAMS.items():
        if program.bot_id != bot_id or not program.version or not program.workflow:
            raise ValueError(f"bot program is incomplete: {bot_id}")
        if not set(program.tools) <= BOT_TOOL_MANIFESTS[bot_id]:
            raise ValueError(f"bot program exceeds its tool manifest: {bot_id}")


validate_bot_programs()


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
