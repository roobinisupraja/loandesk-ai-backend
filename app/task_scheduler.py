import asyncio, os
from . import db
from .pipeline import process_application

MAX_ACTIVE = int(os.getenv("MAX_ACTIVE_APPLICATIONS", "3"))
POLL_SECONDS = float(os.getenv("SCHEDULER_POLL_SECONDS", "3"))
_wake = asyncio.Event()

def notify():
    """Called when a new application is saved, so it starts without waiting for the next poll."""
    _wake.set()

def _next_received() -> str | None:
    rows = db.run("SELECT id FROM applications WHERE status='received' ORDER BY created_at LIMIT 1", fetch=True)
    return rows[0]["id"] if rows else None

async def _run(app_id: str, intake_done: asyncio.Event, sem: asyncio.Semaphore):
    try:
        await process_application(app_id, intake_done)
    finally:
        intake_done.set()   # never block the scheduler if intake failed or was skipped
        sem.release()

async def scheduler_loop():
    sem = asyncio.Semaphore(MAX_ACTIVE)
    while True:
        await sem.acquire()                      # wait for a free processing slot
        _wake.clear()
        app_id = await asyncio.to_thread(_next_received)
        if not app_id:
            sem.release()
            try:
                await asyncio.wait_for(_wake.wait(), POLL_SECONDS)
            except asyncio.TimeoutError:
                pass
            continue
        intake_done = asyncio.Event()
        asyncio.create_task(_run(app_id, intake_done, sem))
        await intake_done.wait()                 # Agent 1 finished -> read the next applicant's form
