import json, time, uuid
from . import db
from .docreader import LABELS

def create_application(a: dict, docs: list[dict]) -> str:
    app_id = "LN-" + uuid.uuid4().hex[:6].upper()
    attached = ", ".join(LABELS.get(d["type"], d["type"]) for d in docs) or "no documents"
    email_text = (f"From: {a['email']}\nSubject: Loan application - {a['loan_type']}\n\nHello, I am {a['name']} (PAN {a['pan'].upper()}, "
                  f"phone {a.get('phone', '')}). I would like a {a['loan_type']} of Rs {int(a['amount'])} for {a['tenure']} months. "
                  f"I am {a.get('employment', 'Salaried').lower()} with a monthly income of Rs {int(a['income'])}. "
                  f"Attached: {attached}.")
    db.run("INSERT INTO applications(id,name,email,phone,pan,loan_type,amount,tenure,income,employment,email_text,documents,status,decision,created_at) "
           "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
           (app_id, a["name"], a["email"], a.get("phone", ""), a["pan"].upper(), a["loan_type"], a["amount"], a["tenure"], a["income"],
            a.get("employment", "Salaried"), email_text, json.dumps(docs), "received", None, time.time()))
    from . import scheduler   
    scheduler.notify()        
    return app_id
