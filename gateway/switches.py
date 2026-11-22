"""Emergency on/off switches for apps and connectors, flipped by platform admins on the admin page.
Turning something off removes access at once; turning it back on only restores what app.yaml already grants."""
from . import audit

PLATFORM_TRAIL = "_platform"  # app names can't start with "_", so this never collides with a real app


def _table(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS switches (kind TEXT, name TEXT, reason TEXT, by_name TEXT, at TEXT, "
                 "PRIMARY KEY (kind, name))")


def off(kind):
    """{name: {reason, by_name, at}} for every app or connector that is turned off."""
    with audit.db() as conn:
        _table(conn)
        return {r["name"]: dict(r) for r in conn.execute("SELECT * FROM switches WHERE kind = ?", (kind,))}


def is_off(kind, name):
    return off(kind).get(name)


def flip(kind, name, enabled, user, reason):
    with audit.LOCK, audit.db(write=True) as conn:
        _table(conn)
        if enabled:
            conn.execute("DELETE FROM switches WHERE kind = ? AND name = ?", (kind, name))
        else:
            conn.execute("INSERT OR REPLACE INTO switches VALUES (?, ?, ?, ?, ?)",
                         (kind, name, reason, user["name"], audit.stamp(audit.now())))
    audit.record(PLATFORM_TRAIL, user, f"admin.turn_{'on' if enabled else 'off'}_{kind}", "write",
                 {kind: name, "reason": reason}, "ok")


def why(kind, name, title=None):
    s = is_off(kind, name)
    what = title or (f"The {name} connector" if kind == "connector" else name)
    return s and f"{what} is turned off by a platform admin ({s['by_name']}): {s['reason']}"
