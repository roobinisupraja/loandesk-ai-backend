import asyncio, json
from agents import RunContextWrapper, RunHooks, Runner
from . import db
from .agent_definitions import KEYS, SPECIALISTS, orchestrator
from .tools import Ctx

NAMES = {k: n for k, n, _ in SPECIALISTS}

class StatusHooks(RunHooks[Ctx]):
    """Mirrors the orchestrator's delegations into the DB so the UI can show live progress."""
    async def on_tool_start(self, context: RunContextWrapper[Ctx], agent, tool):
        aid = context.context.app_id
        if tool.name in NAMES:
            db.set_step(aid, tool.name, "running")
            db.log(aid, f"Orchestrator → {NAMES[tool.name]} started")

    async def on_tool_end(self, context: RunContextWrapper[Ctx], agent, tool, result):
        aid = context.context.app_id
        if tool.name in NAMES:
            db.set_step(aid, tool.name, "done", str(result)[:500])
            db.log(aid, f"{NAMES[tool.name]}: {str(result)[:200]}")
        if tool.name == "email_intake_agent" and context.context.intake_done:
            context.context.intake_done.set()   # scheduler may now start the next application

async def process_application(app_id: str, intake_done: asyncio.Event | None = None):
    for k in KEYS:
        db.run("REPLACE INTO steps(app_id,agent,status) VALUES(?,?,'pending')", (app_id, k))
    db.run("UPDATE applications SET status='processing' WHERE id=?", (app_id,))
    db.log(app_id, f"Orchestrator: case {app_id} received")
    try:
        # The Runner loops model <-> tools (multi-turn) until the manager gives its final answer.
        result = await Runner.run(
            orchestrator, f"New loan application {app_id}. Process it end to end.",
            context=Ctx(app_id=app_id, intake_done=intake_done), hooks=StatusHooks(), max_turns=25)
        db.log(app_id, f"Orchestrator summary: {result.final_output}")
    except Exception as e:  # noqa: BLE001
        db.log(app_id, f"Orchestrator error: {e}")
        db.run("UPDATE steps SET status='failed' WHERE app_id=? AND status='running'", (app_id,))
    db.run("UPDATE steps SET status='skipped' WHERE app_id=? AND status='pending'", (app_id,))
    row = db.run("SELECT status FROM applications WHERE id=?", (app_id,), True)[0]
    if row["status"] == "processing":
        db.run("UPDATE applications SET status='manual_review' WHERE id=?", (app_id,))
        db.log(app_id, "No decision recorded: routed to manual review")
