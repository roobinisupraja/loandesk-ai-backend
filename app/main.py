import asyncio, json, os, time, uuid
from contextlib import asynccontextmanager
from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from agents import Runner, SQLiteSession
from . import db
from .agent_definitions import KEYS, SPECIALISTS, assistant
from . import applications, chat_tools, docreader, task_scheduler
from .tools import compose_decision_email, deliver_email

@asynccontextmanager
async def lifespan(_):
    db.init()
    db.run("UPDATE steps SET status='running' WHERE status='running'")
    db.run("UPDATE applications SET status='manual_review' WHERE status='processing'")
    db.run("UPDATE steps SET status='skipped' WHERE status='pending' AND app_id IN "
           "(SELECT id FROM applications WHERE status IN ('manual_review','approved','rejected'))")
    task = asyncio.create_task(task_scheduler.scheduler_loop())
    yield
    task.cancel()


app = FastAPI(title="LoanDesk AI", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","),
                   allow_methods=["*"], allow_headers=["*"])

class Doc(BaseModel):
    type: str   # PAN | AADHAAR | SALARY_SLIP
    text: str   # OCR text (file upload + OCR comes later)

class ApplicationIn(BaseModel):
    name: str; email: str; phone: str = ""; pan: str
    loan_type: str; amount: float; tenure: int; income: float; employment: str = "Salaried"
    documents: list[Doc] = []

def mock_docs(a: ApplicationIn) -> list[dict]:
    return [
        {"type": "PAN", "text": f"INCOME TAX DEPARTMENT. Name: {a.name.upper()}. Permanent Account Number: {a.pan.upper()}"},
        {"type": "AADHAAR", "text": f"Government of India. {a.name}. XXXX XXXX 4321"},
        {"type": "SALARY_SLIP", "text": (
            f"Income Tax Return summary. Name: {a.name}. Average monthly business income: Rs {int(a.income)}. Occupation: Self-employed"
            if a.employment.lower().startswith("self") else
            f"Salary slip. Employee: {a.name}. Net monthly salary: Rs {int(a.income)}. Employer: Acme Pvt Ltd")},
    ]

@app.post("/api/applications")
async def create_application(a: ApplicationIn):
    docs = [d.model_dump() for d in a.documents] or mock_docs(a)
    app_id = applications.create_application(a.model_dump(exclude={"documents"}), docs)
    return {"id": app_id, "status": "received"}

@app.get("/api/applications")
def list_applications(limit: int = 100):
    """Live board: every application with per-agent status, current stage and queue position."""
    apps = db.run("SELECT id,name,loan_type,amount,status,email_status,created_at FROM applications ORDER BY created_at DESC LIMIT ?", (limit,), True)
    if not apps:
        return []
    ids = tuple(x["id"] for x in apps)
    steps = db.run(f"SELECT app_id,agent,status FROM steps WHERE app_id IN ({','.join(['?'] * len(ids))})", ids, True)
    by: dict[str, dict[str, str]] = {}
    for st in steps:
        by.setdefault(st["app_id"], {})[st["agent"]] = st["status"]
    queued = [x["id"] for x in sorted(apps, key=lambda x: x["created_at"]) if x["status"] == "received"]
    out = []
    for x in apps:
        st = by.get(x["id"], {})
        out.append({**x, "agents": [st.get(k, "pending") for k in KEYS],
                    "current": next((n for k, n, _ in SPECIALISTS if st.get(k) == "running"), None),
                    "queue_position": queued.index(x["id"]) + 1 if x["id"] in queued else None})
    return out

@app.get("/api/applications/{app_id}")
def get_application(app_id: str):
    rows = db.run("SELECT * FROM applications WHERE id=?", (app_id,), True)
    if not rows:
        raise HTTPException(404, "Application not found")
    a = rows[0]
    steps = {s["agent"]: s for s in db.run("SELECT * FROM steps WHERE app_id=?", (app_id,), True)}
    agents = [{"key": k, "name": n, "status": steps.get(k, {}).get("status", "pending"), "summary": steps.get(k, {}).get("summary")}
              for k, n, _ in SPECIALISTS]
    logs = [f"[{time.strftime('%H:%M:%S', time.localtime(l['ts']))}] {l['msg']}"
            for l in db.run("SELECT ts,msg FROM logs WHERE app_id=? ORDER BY id", (app_id,), True)]
    last = db.run("SELECT to_addr,subject,status,ts FROM outbox WHERE app_id=? ORDER BY id DESC LIMIT 1", (app_id,), True)
    qpos = None
    if a["status"] == "received":
        qpos = db.run("SELECT COUNT(*) AS n FROM applications WHERE status='received' AND created_at<=?", (a["created_at"],), True)[0]["n"]
    return {"id": app_id, "status": a["status"], "email": last[0] if last else None, "email_status": a["email_status"], "queue_position": qpos,
            "application": {k: a[k] for k in ("name", "email", "phone", "pan", "loan_type", "amount", "tenure", "income", "employment")},
            "agents": agents, "logs": logs, "decision": json.loads(a["decision"]) if a["decision"] else None}

class SendIn(BaseModel):
    subject: str | None = None   # optional edits made by the human reviewer
    body: str | None = None

@app.post("/api/applications/{app_id}/send-email")
def send_decision_email(app_id: str, p: SendIn | None = None):
    """Human action: send the approval/rejection email (optionally edited) to the address on the application."""
    rows = db.run("SELECT * FROM applications WHERE id=?", (app_id,), True)
    if not rows:
        raise HTTPException(404, "Application not found")
    a = rows[0]
    if not a["decision"]:
        raise HTTPException(400, "No decision recorded yet")
    subject, body = compose_decision_email(a, json.loads(a["decision"]))
    if p and p.subject and p.subject.strip():
        subject = p.subject.strip()
    if p and p.body and p.body.strip():
        body = p.body
    res = deliver_email(app_id, a["email"], subject, body)
    if res == "sent":
        db.run("UPDATE applications SET email_status='sent' WHERE id=?", (app_id,))
    return {"to": a["email"], "result": res}

@app.get("/api/drafts")
def drafts(state: str = "draft"):
    """state=draft: decided applications whose email still needs a human. state=sent: already emailed."""
    if state not in ("draft", "sent"):
        raise HTTPException(400, "state must be draft or sent")
    rows = db.run("SELECT * FROM applications WHERE email_status=? AND status IN ('approved','rejected') "
                  "ORDER BY created_at DESC LIMIT 200", (state,), True)
    out = []
    for a in rows:
        d = json.loads(a["decision"]) if a["decision"] else {}
        item = {"id": a["id"], "name": a["name"], "email": a["email"], "loan_type": a["loan_type"],
                "amount": a["amount"], "status": a["status"], "reason": d.get("reason")}
        if state == "draft":
            item["subject"], item["body"] = compose_decision_email(a, d)
        else:
            m = db.run("SELECT subject,body,ts FROM outbox WHERE app_id=? AND status='sent' ORDER BY id DESC LIMIT 1", (a["id"],), True)
            item.update(m[0] if m else {"subject": None, "body": None, "ts": None})
        out.append(item)
    return out

class ChatIn(BaseModel):
    session_id: str
    message: str

@app.post("/api/chat")
async def chat(c: ChatIn):
    # SQLiteSession keeps the conversation history, so the chatbot is multi-turn per session_id.
    sid = _sid(c.session_id)
    chat_tools.bump_turn(sid)   # lets the code verify the customer answered the summary in a later turn
    r = await Runner.run(assistant, c.message, session=SQLiteSession(sid, "chat.db"), context=chat_tools.ChatCtx(session_id=sid))
    return {"reply": r.final_output}

def _sid(raw: str) -> str:
    try:
        return chat_tools.clean_session(raw)
    except ValueError:
        raise HTTPException(400, "Invalid session id")

@app.post("/api/chat/upload")
async def chat_upload(session_id: str = Form(...), doc_type: str | None = Form(None), file: UploadFile = File(...)):
    """The customer uploads any loan document. Its type is detected automatically (doc_type is only a hint).
    Text is read and stored (Aadhaar masked)."""
    sid = _sid(session_id)
    name = file.filename or "upload"
    if os.path.splitext(name)[1].lower() not in docreader.ALLOWED:
        raise HTTPException(415, "Upload a JPG, PNG, WEBP or PDF file")
    data = await file.read(docreader.MAX_BYTES + 1)
    if len(data) > docreader.MAX_BYTES:
        raise HTTPException(413, "File is larger than 5 MB")
    try:
        dt, text = await docreader.extract(data, name)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Could not read the document: {e}")
    if len(text) < 15:
        raise HTTPException(422, "I couldn't read any text in this file. Please upload a clearer photo or a text-based PDF.")
    dt = dt or chat_tools.norm_doc_type(doc_type)
    if not dt:
        raise HTTPException(422, "I couldn't tell which document this is. Please upload a clear PAN card, Aadhaar, income proof, or the property / vehicle / business document.")
    text = docreader.mask_sensitive(text)
    db.run("INSERT INTO chat_docs(session_id,doc_type,filename,content,uploaded_at) VALUES(?,?,?,?,?) "
           "ON DUPLICATE KEY UPDATE filename=VALUES(filename), content=VALUES(content), uploaded_at=VALUES(uploaded_at)",
           (sid, dt, name[:255], text, time.time()))
    return {"doc_type": dt, "label": docreader.LABELS[dt], "filename": name, "chars": len(text), "preview": text[:160]}

@app.get("/api/chat/state")
def chat_state(session_id: str):
    """Checklist for the chat screen: saved details, uploaded documents, what is missing, submitted case id."""
    return chat_tools.readiness(_sid(session_id))

@app.get("/api/scheduler")
def scheduler_status():
    rows = db.run("SELECT status, COUNT(*) AS n FROM applications GROUP BY status", fetch=True)
    return {"max_active": task_scheduler.MAX_ACTIVE, "counts": {r["status"]: r["n"] for r in rows}}

@app.get("/api/health")
def health():
    return {"ok": True}
