"""Function tools used by the agents. Stubs are marked: swap them for real services."""
import asyncio, json, math, time
from dataclasses import dataclass
from agents import RunContextWrapper, function_tool
from . import db, email_service 

@dataclass
class Ctx:
    app_id: str
    intake_done: asyncio.Event | None = None   # set when Agent 1 finishes (scheduler signal)

LOAN_POLICY = """Eligibility policy:
- Applicant must be verified (PAN, name and income documents consistent with the form).
- CIBIL score must be 700 or above.
- FOIR (total EMI / monthly income) must be 50% or below.
- Rates: CIBIL >= 780 -> 10.5% p.a.; 700-779 -> 12.6% p.a.
- Max loan Rs 25,00,000. Tenure 6-84 months."""

def _app(app_id: str) -> dict:
    rows = db.run("SELECT * FROM applications WHERE id=?", (app_id,), True)
    return rows[0] if rows else {}

# ---------- Intake / extraction / verification ----------
@function_tool
def get_application_email(ctx: RunContextWrapper[Ctx]) -> str:
    """Return the raw loan application email received from the customer."""
    return _app(ctx.context.app_id).get("email_text", "")

@function_tool
def list_documents(ctx: RunContextWrapper[Ctx]) -> str:
    """List the types of documents attached to this application (PAN, AADHAAR, SALARY_SLIP, PROPERTY_DOC, ...)."""
    return json.dumps([d["type"] for d in json.loads(_app(ctx.context.app_id).get("documents") or "[]")])

@function_tool
def read_document(ctx: RunContextWrapper[Ctx], doc_type: str) -> str:
    """Return the OCR text of an attached document. doc_type is one of the types returned by list_documents.""" 
    docs = json.loads(_app(ctx.context.app_id).get("documents") or "[]")
    print(docs)
    for d in docs:
        if d["type"].upper() == doc_type.upper():
            return d["text"]
    return f"NOT_FOUND: no {doc_type} document attached"

@function_tool
def get_applicant_form(ctx: RunContextWrapper[Ctx]) -> str:
    """Return the data the applicant typed into the application form, as JSON."""
    a = _app(ctx.context.app_id)
    keep = ["id", "name", "email", "phone", "pan", "loan_type", "amount", "tenure", "income", "employment"]
    return json.dumps({k: a.get(k) for k in keep})

# ---------- CRM tools (adapted from your crm namespace) ----------
@function_tool
def get_customer_profile(customer_id: str) -> str:
    """Fetch a customer profile by customer ID (the customer's PAN)."""
    rows = db.run("SELECT name,email,phone,employment,income FROM applications WHERE pan=? ORDER BY created_at DESC LIMIT 1", (customer_id,), True)
    return json.dumps(rows[0]) if rows else "NOT_FOUND: new customer"

@function_tool
def list_open_orders(customer_id: str) -> str:
    """List open (approved, not closed) loans for a customer ID (the customer's PAN)."""
    rows = db.run("SELECT id,loan_type,amount,tenure FROM applications WHERE pan=? AND status='approved'", (customer_id,), True)
    return json.dumps(rows)

# ---------- Credit / eligibility ----------
@function_tool
def fetch_cibil_score(pan: str) -> str:
    """Fetch the CIBIL credit score and bureau summary for a PAN. STUB: replace with a real bureau API."""
    h = 0
    for ch in pan.upper():
        h = (h * 31 + ord(ch)) % 1000
    return json.dumps({"pan": pan.upper(), "score": 640 + h % 260, "written_off_accounts": 0})

@function_tool
def get_existing_emi(pan: str) -> str:
    """Total monthly EMI of the customer's existing approved loans (0 if there are none)."""
    rows = db.run("SELECT amount,tenure FROM applications WHERE pan=? AND status='approved'", (pan.upper(),), True)
    r = 12.6 / 1200
    total = sum(x["amount"] * r * (1 + r) ** x["tenure"] / ((1 + r) ** x["tenure"] - 1) for x in rows)
    return json.dumps({"existing_emi": round(total), "open_loans": len(rows)})

@function_tool
def calculate_emi(principal: float, annual_rate_pct: float, tenure_months: int) -> str:
    """Compute the monthly EMI for a loan."""
    r = annual_rate_pct / 1200
    emi = principal * r * (1 + r) ** tenure_months / ((1 + r) ** tenure_months - 1)
    return json.dumps({"emi": round(emi)})

@function_tool
def calculate_foir(emi: float, monthly_income: float, existing_emi: float = 0) -> str:
    """Compute FOIR = (new EMI + existing EMI) / monthly income."""
    return json.dumps({"foir": round((emi + existing_emi) / monthly_income, 3)})

# ---------- Decision + email ----------
def compose_decision_email(a: dict, d: dict) -> tuple[str, str]:
    """Build (subject, body) for the applicant from the application row and the decision dict."""
    if d.get("approved"):
        body = d.get("letter") or (f"Dear {a['name']},\n\nYour {a['loan_type']} of Rs {int(a['amount'])} has been sanctioned "
                                   f"at {d.get('rate')}% p.a. Estimated EMI: Rs {int(d.get('emi') or 0)}.\n\nLoanDesk AI")
        return f"Loan sanctioned - {a['id']}", body
    return (f"Update on your loan application {a['id']}",
            f"Dear {a['name']},\n\nThank you for applying for a {a['loan_type']}. After review, we are unable to "
            f"approve your application at this time.\n\nReason: {d.get('reason')}\n\nYou are welcome to reapply with a "
            f"different amount or tenure.\n\nLoanDesk AI")

def deliver_email(app_id: str, to: str, subject: str, body: str) -> str:
    """Send over SMTP (if configured) and record the attempt and its result in the outbox table. Never raises."""
    try:
        res = email_service.send_smtp(to, subject, body)
    except Exception as e:  # noqa: BLE001
        res = f"failed: {e}"
    db.run("INSERT INTO outbox(app_id,to_addr,subject,body,ts,status) VALUES(?,?,?,?,?,?)", (app_id, to, subject, body, time.time(), res[:250]))
    db.log(app_id, f"Email to {to} ({subject}): {res}")
    return res

@function_tool
async def finalize_application(ctx: RunContextWrapper[Ctx], approved: bool, reason: str, rate_pct: float,
                         emi: float, cibil: int, foir: float, letter: str) -> str:
    """Record the final decision and email the applicant automatically.
    letter is the sanction letter text (empty when rejected)."""
    aid = ctx.context.app_id
    a = _app(aid)
    if a.get("status") in ("approved", "rejected"):
        return "already recorded"
    decision = dict(approved=approved, reason=reason, rate=rate_pct, emi=emi, cibil=cibil, foir=foir, letter=letter)
    db.run("UPDATE applications SET status=?, decision=? WHERE id=?", ("approved" if approved else "rejected", json.dumps(decision), aid))
    db.log(aid, f"Decision recorded: {'APPROVED' if approved else 'REJECTED'}")
    # No email is sent here: a human reviews the draft in the Drafts screen and sends it.
    db.run("UPDATE applications SET email_status='draft' WHERE id=?", (aid,))
    db.log(aid, "Email draft saved: waiting for a human to review and send")
    return "recorded; email draft saved for human review"

# ---------- Chatbot tools ----------
@function_tool
def get_loan_policy() -> str:
    """Return the bank's loan eligibility policy and rates."""
    return LOAN_POLICY

@function_tool
def get_application_status(application_id: str) -> str:
    """Return the status and agent progress of an application."""
    a = _app(application_id)
    if not a:
        return "NOT_FOUND"
    steps = db.run("SELECT agent,status,summary FROM steps WHERE app_id=?", (application_id,), True)
    return json.dumps({"status": a["status"], "steps": steps})
