import os, pathlib, time
import pymysql
from pymysql.cursors import DictCursor

def _cfg() -> dict:
    return dict(host=os.getenv("MYSQL_HOST", "localhost"), port=int(os.getenv("MYSQL_PORT", "3306")),
                user=os.getenv("MYSQL_USER", "root"), password=os.getenv("MYSQL_PASSWORD", ""),
                charset="utf8mb4", cursorclass=DictCursor)

def _db() -> str:
    return os.getenv("MYSQL_DATABASE", "loandesk")

def _migrate(cur):
    """Idempotent upgrades for databases created by older versions."""
    for ddl in ("ALTER TABLE outbox ADD COLUMN status VARCHAR(255)",
                "ALTER TABLE applications ADD COLUMN email_status VARCHAR(16)"):
        try:
            cur.execute(ddl)
        except pymysql.err.OperationalError as e:
            if e.args[0] != 1060:  # 1060 = column already exists
                raise
    cur.execute("ALTER TABLE chat_docs MODIFY doc_type VARCHAR(24)")   # room for VEHICLE_QUOTATION etc.
    # applications decided before drafts existed: already-emailed ones are 'sent', the rest become drafts
    cur.execute("UPDATE applications SET email_status='sent' WHERE email_status IS NULL "
                "AND id IN (SELECT app_id FROM outbox WHERE status='sent')")
    cur.execute("UPDATE applications SET email_status='draft' WHERE email_status IS NULL AND status IN ('approved','rejected')")

def init():
    """Create the database and tables from schema.sql if they don't exist, then run migrations."""
    sql = (pathlib.Path(__file__).resolve().parent.parent / "schema.sql").read_text().replace("loandesk", _db())
    c = pymysql.connect(**_cfg())
    try:
        with c.cursor() as cur:
            for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
                cur.execute(stmt)
            _migrate(cur)
        c.commit()
    finally:
        c.close()

def run(sql: str, args: tuple = (), fetch: bool = False):
    """Callers write '?' placeholders; they are converted to MySQL's '%s'."""
    c = pymysql.connect(database=_db(), **_cfg())
    try:
        with c.cursor() as cur:
            cur.execute(sql.replace("?", "%s"), args)
            rows = list(cur.fetchall()) if fetch else None
        c.commit()
        return rows
    finally:
        c.close()

def log(app_id: str, msg: str):
    run("INSERT INTO logs(app_id,ts,msg) VALUES(?,?,?)", (app_id, time.time(), msg))

def set_step(app_id: str, agent: str, status: str, summary: str | None = None):
    now = time.time()
    run("UPDATE steps SET status=?, summary=COALESCE(?,summary) WHERE app_id=? AND agent=?", (status, summary, app_id, agent))
    col = "started" if status == "running" else "finished" if status in ("done", "failed") else None
    if col:
        run(f"UPDATE steps SET {col}=? WHERE app_id=? AND agent=?", (now, app_id, agent))
