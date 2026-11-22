"""Append-only audit log. One row per gateway call."""
import hashlib
import json
import time

from . import config

FIELDS = ["ts", "user_id", "user_name", "role", "app", "connector", "operation", "inputs", "record_id",
          "outcome", "reason", "retention_days", "expires_at"]


def init():
    c = config.db()
    c.execute(
        "CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, user_id TEXT, "
        "user_name TEXT, role TEXT, app TEXT, connector TEXT, operation TEXT, inputs TEXT, record_id TEXT, "
        "outcome TEXT, reason TEXT, retention_days INTEGER, expires_at REAL, prev_hash TEXT, hash TEXT)"
    )
    # Enforced by the database itself: rows cannot be edited, and can only be deleted once expired.
    c.execute(
        "CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit "
        "BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END"
    )
    c.execute(
        "CREATE TRIGGER IF NOT EXISTS audit_no_early_delete BEFORE DELETE ON audit "
        "WHEN OLD.expires_at > CAST(strftime('%s','now') AS REAL) "
        "BEGIN SELECT RAISE(ABORT, 'audit rows can only be removed after their retention period'); END"
    )
    for col in ("user_id", "app", "operation", "record_id", "ts"):
        c.execute(f"CREATE INDEX IF NOT EXISTS audit_{col} ON audit({col})")


def _hash(prev_hash, row):
    body = json.dumps([row[f] for f in FIELDS], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256((prev_hash + body).encode()).hexdigest()


def record(user, app, operation, inputs, outcome, reason="", record_id=None, retention_days=90, mask_inputs=()):
    safe = {k: ("•••" if k in mask_inputs else v) for k, v in (inputs or {}).items()}
    now = time.time()
    row = {
        "ts": now,
        "user_id": user["id"] if user else "",
        "user_name": user["name"] if user else "Not signed in",
        "role": user["role"] if user else "",
        "app": app or "",
        "connector": operation.split(".")[0] if operation and "." in operation else "",
        "operation": operation or "",
        "inputs": json.dumps(safe, sort_keys=True),
        "record_id": str(record_id) if record_id is not None else "",
        "outcome": outcome,
        "reason": reason,
        "retention_days": retention_days,
        "expires_at": now + retention_days * 86400,
    }
    c = config.db()
    with config._lock:
        last = c.execute("SELECT hash FROM audit ORDER BY id DESC LIMIT 1").fetchone()
        prev = last["hash"] if last else ""
        c.execute(
            f"INSERT INTO audit ({', '.join(FIELDS)}, prev_hash, hash) VALUES ({', '.join('?' * len(FIELDS))}, ?, ?)",
            [row[f] for f in FIELDS] + [prev, _hash(prev, row)],
        )


def search(user=None, app=None, operation=None, record_id=None, outcome=None, since=None, until=None, limit=200):
    where, args = [], []
    for col, val in (("user_id", user), ("app", app), ("operation", operation), ("record_id", record_id),
                     ("outcome", outcome)):
        if val:
            where.append(f"{col} = ?")
            args.append(val)
    if since:
        where.append("ts >= ?")
        args.append(float(since))
    if until:
        where.append("ts <= ?")
        args.append(float(until))
    sql = "SELECT * FROM audit" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id DESC LIMIT ?"
    rows = [dict(r) for r in config.db().execute(sql, args + [int(limit)])]
    for r in rows:
        r["inputs"] = json.loads(r["inputs"])
        del r["prev_hash"]
    return rows


def verify():
    """Recomputes every fingerprint. Any edited, inserted or removed row in the middle breaks the chain."""
    prev, count = None, 0
    for r in config.db().execute("SELECT * FROM audit ORDER BY id"):
        r = dict(r)
        if prev is not None and r["prev_hash"] != prev:
            return {"ok": False, "rows": count, "broken_at": r["id"]}
        if _hash(r["prev_hash"], r) != r["hash"]:
            return {"ok": False, "rows": count, "broken_at": r["id"]}
        prev, count = r["hash"], count + 1
    return {"ok": True, "rows": count, "broken_at": None}


def purge_expired():
    cur = config.db().execute("DELETE FROM audit WHERE expires_at <= CAST(strftime('%s','now') AS REAL)")
    return cur.rowcount
