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
from datetime import datetime, timedelta, timezone
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
        # Where each app's chain starts after retention deleted its oldest entries.
        conn.execute("CREATE TABLE IF NOT EXISTS pruned (app TEXT PRIMARY KEY, through_seq INTEGER, last_hash TEXT)")
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


def now():
    return datetime.now(timezone.utc)


def stamp(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def chain_start(conn, app):
    p = conn.execute("SELECT through_seq, last_hash FROM pruned WHERE app = ?", (app,)).fetchone()
    return (p["through_seq"], p["last_hash"]) if p else (0, "")


def record(app, user, tool, kind, inputs, outcome, detail="", retention_days=None):
    """outcome: 'ok' or 'refused'. detail: the refusal reason. Entries older than retention_days are deleted."""
    with LOCK, db(write=True) as conn:
        last = conn.execute("SELECT seq, hash FROM audit WHERE app = ? ORDER BY seq DESC LIMIT 1", (app,)).fetchone()
        start_seq, start_hash = chain_start(conn, app)
        row = {
            "app": app, "seq": (last["seq"] if last else start_seq) + 1,
            "at": stamp(now()),
            "user_id": user["id"], "user_name": user["name"], "role": user["role"], "tool": tool, "kind": kind,
            "inputs": json.dumps(inputs, sort_keys=True, ensure_ascii=False), "outcome": outcome, "detail": detail or "",
        }
        prev = last["hash"] if last else start_hash
        row["prev_hash"], row["hash"] = prev, digest(prev, row)
        conn.execute(f"INSERT INTO audit ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", list(row.values()))
        if retention_days:
            _prune(conn, app, retention_days)


def _prune(conn, app, days):
    cutoff = stamp(now() - timedelta(days=days))
    # Only the oldest run of expired entries goes, so an entry is never deleted early and the chain has no gaps.
    keep = conn.execute("SELECT MIN(seq) FROM audit WHERE app = ? AND at >= ?", (app, cutoff)).fetchone()[0]
    through = (keep - 1) if keep is not None else \
        conn.execute("SELECT MAX(seq) FROM audit WHERE app = ?", (app,)).fetchone()[0]
    old = through and conn.execute("SELECT seq, hash FROM audit WHERE app = ? AND seq = ?", (app, through)).fetchone()
    if old:
        conn.execute("DELETE FROM audit WHERE app = ? AND seq <= ?", (app, old["seq"]))
        conn.execute("INSERT OR REPLACE INTO pruned VALUES (?, ?, ?)", (app, old["seq"], old["hash"]))


def prune(app, days):
    with LOCK, db(write=True) as conn:
        _prune(conn, app, days)


def entries(app=None, limit=200, user=None, tool=None, kind=None, outcome=None, q=None):
    """Newest first. Filters match exactly; q searches people, tools, inputs and reasons."""
    where, args = [], []
    for column, value in (("app", app), ("user_id", user), ("tool", tool), ("kind", kind), ("outcome", outcome)):
        if value:
            where.append(f"{column} = ?"); args.append(value)
    if q:
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append("(" + " OR ".join(f"{c} LIKE ? ESCAPE '\\'" for c in ("user_name", "role", "tool", "inputs", "detail")) + ")")
        args += [like] * 5
    sql = "SELECT * FROM audit" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY rowid DESC LIMIT ?"
    with db() as conn:
        return [dict(r, inputs=json.loads(r["inputs"])) for r in conn.execute(sql, args + [limit])]


def facets(app):
    """People and tools that appear in an app's trail, for the filter menus."""
    with db() as conn:
        people = {r["user_id"]: r["user_name"] for r in
                  conn.execute("SELECT DISTINCT user_id, user_name FROM audit WHERE app = ? ORDER BY user_name", (app,))}
        tools = [r["tool"] for r in conn.execute("SELECT DISTINCT tool FROM audit WHERE app = ? ORDER BY tool", (app,))]
    return people, tools


def verify(app):
    """Recompute the app's chain. Returns (True, None) or (False, first seq that doesn't match)."""
    with db() as conn:
        conn.execute("BEGIN")  # one snapshot, so a concurrent prune can't move the start between the two reads
        seq, prev = chain_start(conn, app)
        for r in conn.execute("SELECT * FROM audit WHERE app = ? ORDER BY seq", (app,)):
            if r["seq"] != seq + 1 or r["prev_hash"] != prev or digest(prev, r) != r["hash"]:
                return False, r["seq"]
            seq, prev = r["seq"], r["hash"]
    return True, None


def counts():
    with db() as conn:
        return {r["app"]: r["n"] for r in conn.execute("SELECT app, COUNT(*) AS n FROM audit GROUP BY app")}


def clear():
    with LOCK, db(write=True) as conn:
        conn.execute("DELETE FROM audit")
        conn.execute("DELETE FROM pruned")
