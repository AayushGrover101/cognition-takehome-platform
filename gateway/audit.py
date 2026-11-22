"""Per-app audit trail. Each app has its own hash chain, so each trail can be checked on its own.

What gets recorded is decided on the server: every write tool, plus the read tools an app lists in
`audit_reads` in its reviewed app.yaml. Nothing in the browser can switch it off.
"""
import hashlib
import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK = threading.Lock()
FIELDS = ["app", "seq", "at", "user_id", "user_name", "role", "tool", "kind", "inputs", "outcome", "detail"]


@contextmanager
def db(write=False):
    """One connection per use, always closed. Writes take SQLite's write lock up front, so gateway
    processes sharing the file can't hand out the same sequence number."""
    path = Path(os.environ.get("AUDIT_DB", ROOT / "data" / "audit.db"))
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS audit (
            app TEXT, seq INTEGER, at TEXT, user_id TEXT, user_name TEXT, role TEXT, tool TEXT, kind TEXT,
            inputs TEXT, outcome TEXT, detail TEXT, prev_hash TEXT, hash TEXT, PRIMARY KEY (app, seq))""")
        if write:
            conn.execute("BEGIN IMMEDIATE")
        yield conn
        if write:
            conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def digest(prev_hash, row):
    body = json.dumps([prev_hash] + [row[f] for f in FIELDS], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()


def record(app, user, tool, kind, inputs, outcome, detail=""):
    """outcome: 'ok' or 'refused'. detail: the refusal reason."""
    with LOCK, db(write=True) as conn:
        last = conn.execute("SELECT seq, hash FROM audit WHERE app = ? ORDER BY seq DESC LIMIT 1", (app,)).fetchone()
        row = {
            "app": app, "seq": (last["seq"] + 1) if last else 1,
            "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "user_id": user["id"], "user_name": user["name"], "role": user["role"], "tool": tool, "kind": kind,
            "inputs": json.dumps(inputs, sort_keys=True), "outcome": outcome, "detail": detail or "",
        }
        prev = last["hash"] if last else ""
        row["prev_hash"], row["hash"] = prev, digest(prev, row)
        conn.execute(f"INSERT INTO audit ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", list(row.values()))


def entries(app=None, limit=200):
    with db() as conn:
        where, args = ("WHERE app = ?", [app]) if app else ("", [])
        rows = conn.execute(f"SELECT * FROM audit {where} ORDER BY rowid DESC LIMIT ?", args + [limit])
        return [dict(r, inputs=json.loads(r["inputs"])) for r in rows]


def verify(app):
    """Recompute the app's chain. Returns (True, None) or (False, first seq that doesn't match)."""
    with db() as conn:
        prev = ""
        for r in conn.execute("SELECT * FROM audit WHERE app = ? ORDER BY seq", (app,)):
            if r["prev_hash"] != prev or digest(prev, r) != r["hash"]:
                return False, r["seq"]
            prev = r["hash"]
    return True, None


def counts():
    with db() as conn:
        return {r["app"]: r["n"] for r in conn.execute("SELECT app, COUNT(*) AS n FROM audit GROUP BY app")}


def clear():
    with LOCK, db(write=True) as conn:
        conn.execute("DELETE FROM audit")
