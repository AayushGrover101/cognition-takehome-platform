"""Loads connectors and policy, and keeps the live (admin-editable) settings in SQLite."""
import json
import os
import sqlite3
import threading
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("PLATFORM_DB", ROOT / "data" / "platform.db"))
APPS_DIR = Path(os.environ.get("APPS_DIR", ROOT.parent / "cognition-takehome-apps"))
GROUPS = ("internal", "external", "blocked")

_lock = threading.Lock()
_conn = None


def db():
    global _conn
    if _conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
        _conn.row_factory = sqlite3.Row
        _conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        _conn.execute(
            "CREATE TABLE IF NOT EXISTS outbox (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, "
            "service TEXT, destination TEXT, content TEXT, user_name TEXT, app TEXT)"
        )
    return _conn


def close_db():
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None


def load_connectors():
    """Returns {"kyc.list_cases": {...operation..., "connector": "kyc"}} and connector metadata."""
    connectors, operations = {}, {}
    for path in sorted((ROOT / "connectors").glob("*.yaml")):
        doc = yaml.safe_load(path.read_text())
        name = doc["connector"]
        connectors[name] = {"title": doc.get("title", name), "description": doc.get("description", "")}
        for op_name, op in doc["operations"].items():
            op = dict(op)
            op["connector"] = name
            op.setdefault("params", {})
            op.setdefault("mask", {})
            op.setdefault("changes_data", False)
            audit = dict(op.get("audit") or {})
            audit.setdefault("min_retention_days", 2555 if op["changes_data"] else 90)
            audit.setdefault("mask_inputs", [])
            # Audit cannot be switched off for operations that change data or return masked fields.
            audit["required"] = bool(op["changes_data"] or op["mask"])
            op["audit"] = audit
            operations[f"{name}.{op_name}"] = op
    return connectors, operations


CONNECTORS, OPERATIONS = load_connectors()
SEED = yaml.safe_load((ROOT / "policy.yaml").read_text())
ROLES = SEED["roles"]


def get_setting(key):
    row = db().execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    if row:
        return json.loads(row["value"])
    seed = {
        "users": SEED["users"],
        "connector_groups": SEED["connector_groups"],
        "blocked_operations": SEED.get("blocked_operations", []),
    }[key]
    return json.loads(json.dumps(seed))


def set_setting(key, value):
    with _lock:
        db().execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )


def users():
    return {u["id"]: u for u in get_setting("users")}


def connector_groups():
    groups = get_setting("connector_groups")
    return {name: groups.get(name, "blocked") for name in CONNECTORS}


def blocked_operations():
    return set(get_setting("blocked_operations"))


def load_apps():
    """Reads every app manifest from the apps repository checkout."""
    apps = {}
    root = APPS_DIR / "apps"
    if not root.is_dir():
        return apps
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        manifest = folder / "app.yaml"
        if not manifest.is_file():
            continue
        try:
            doc = yaml.safe_load(manifest.read_text()) or {}
        except yaml.YAMLError as e:
            doc = {"_error": f"app.yaml could not be read: {e}"}
        doc["name"] = folder.name
        doc.setdefault("title", folder.name)
        doc.setdefault("access", [])
        doc.setdefault("operations", [])
        doc.setdefault("audit", {})
        apps[folder.name] = doc
    return apps


def catalog():
    """Everything the apps repository needs to know about the platform, as plain data."""
    groups, blocked = connector_groups(), blocked_operations()
    return {
        "roles": ROLES,
        "connectors": {
            name: {**meta, "group": groups[name]} for name, meta in CONNECTORS.items()
        },
        "operations": {
            full: {
                "connector": op["connector"],
                "description": op.get("description", ""),
                "roles": op["roles"],
                "params": op["params"],
                "returns": op.get("returns", []),
                "masked_fields": {f: m["show_full_to"] for f, m in op["mask"].items()},
                "changes_data": op["changes_data"],
                "rules": op.get("rules", []),
                "record": op.get("record"),
                "audit": op["audit"],
                "blocked": full in blocked,
            }
            for full, op in OPERATIONS.items()
        },
    }
