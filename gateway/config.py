"""Where things live: people and roles (policy.yaml) and the apps (a checkout of the apps repo)."""
import os
import re
from pathlib import Path

import yaml

from .connectors import TOOLS, connectors

ROOT = Path(__file__).resolve().parent.parent
APPS_DIR = Path(os.environ.get("APPS_DIR", ROOT.parent / "cognition-takehome-apps"))
POLICY = yaml.safe_load((ROOT / "policy.yaml").read_text())
ROLES = POLICY["roles"]
GROUPS = ("business", "non-business", "blocked")


def users():
    return {u["id"]: dict(u) for u in POLICY["users"]}


def admin_roles():
    return POLICY.get("admin_roles") or []


def audited(app, tool):
    """Nothing is audited by default: only the tools (reads or writes) app.yaml lists under audit."""
    return any(grant_matches(p, tool.name) for p in app["audit"])


def valid_retention(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def can_view_audit(user, app):
    return user["role"] in admin_roles() or user["role"] in app["audit_viewers"]


def low_risk_apps():
    """From app_risk.yaml. Apps not listed are high risk, so every change to them needs an engineer's review."""
    path = ROOT / "app_risk.yaml"
    data = yaml.safe_load(path.read_text()) if path.exists() else None
    low = (data or {}).get("low") if isinstance(data, dict) else None
    if low is not None and not (isinstance(low, list) and all(isinstance(n, str) for n in low)):
        raise ValueError("app_risk.yaml: low must be a list of app names")
    return sorted(low or [])


def app_risk(name):
    return "low" if name in low_risk_apps() else "high"


def connector_group(name):
    group = (POLICY.get("connectors") or {}).get(name)
    return group if group in GROUPS else "blocked"


def grant_matches(pattern, tool_name):
    return pattern == tool_name or (pattern.endswith(".*") and tool_name.startswith(pattern[:-1]))


def tools_for(app, role):
    """Tool names this role may call in this app: granted in app.yaml and from a declared connector."""
    patterns = (app["roles"].get(role) or {}).get("tools") or []
    return sorted(name for name, t in TOOLS.items()
                  if t.connector in app["connectors"] and any(grant_matches(p, name) for p in patterns))


def connector_problems(declared):
    if not isinstance(declared, list) or not all(isinstance(c, str) for c in declared):
        return ["connectors must be a list of connector names"]
    problems = [f"Unknown connector: {c}" for c in declared if c not in connectors()]
    known = [c for c in declared if c in connectors()]
    problems += [f"Connector {c} is Blocked" for c in known if connector_group(c) == "blocked"]
    business = [c for c in known if connector_group(c) == "business"]
    non_business = [c for c in known if connector_group(c) == "non-business"]
    if business and non_business:
        problems.append(f"An app can't combine Business ({', '.join(business)}) and Non-business "
                        f"({', '.join(non_business)}) connectors")
    return problems


def grant_problems(roles, access, declared):
    if not isinstance(roles, dict):
        return ["roles must map each role to its tools"]
    problems = []
    for role, grants in roles.items():
        if role not in (access if isinstance(access, list) else []):
            problems.append(f"Role {role} has tools but is not in access")
        tools = grants.get("tools") if isinstance(grants, dict) else None
        problems += pattern_problems(role, tools, declared)
    return problems


def pattern_problems(where, patterns, declared):
    if not isinstance(patterns, list) or not all(isinstance(t, str) for t in patterns):
        return [f"{where} must be a list of tool names"]
    problems = []
    for pattern in patterns:
        connector = pattern.split(".", 1)[0]
        if pattern.endswith(".*"):
            if pattern.count(".") != 1 or connector not in declared:
                problems.append(f"{where}: {pattern} needs {connector} in connectors")
        elif pattern not in TOOLS:
            problems.append(f"{where}: unknown tool {pattern}")
        elif connector not in declared:
            problems.append(f"{where}: {pattern} needs {connector} in connectors")
    return problems


def app_problems(manifest):
    if not isinstance(manifest, dict):
        return ["app.yaml is not a mapping"]
    problems = []
    if not isinstance(manifest.get("title"), str) or not manifest["title"].strip():
        problems.append("app.yaml needs a title")
    access = manifest.get("access")
    if not isinstance(access, list) or not access:
        problems.append("app.yaml needs an access list of roles")
    else:
        problems += [f"Unknown role in access: {r}" for r in access if not isinstance(r, str) or r not in ROLES]
    declared = manifest.get("connectors", [])
    problems += connector_problems(declared)
    declared = declared if isinstance(declared, list) else []
    problems += grant_problems(manifest.get("roles", {}), access, declared)
    problems += pattern_problems("audit", manifest.get("audit", []), declared)
    viewers = manifest.get("audit_viewers", [])
    if not isinstance(viewers, list):
        problems.append("audit_viewers must be a list of roles")
    else:
        problems += [f"Unknown role in audit_viewers: {r}" for r in viewers if not isinstance(r, str) or r not in ROLES]
    if "audit_retention_days" in manifest and not valid_retention(manifest["audit_retention_days"]):
        problems.append("audit_retention_days must be a whole number of days")
    return problems


def load_apps():
    """Re-read on every request, so a merged app is live as soon as the checkout is updated."""
    apps = {}
    for path in sorted((APPS_DIR / "apps").glob("*/app.yaml")):
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", path.parent.name):
            continue  # app names are lowercase letters, digits and dashes
        try:
            manifest = yaml.safe_load(path.read_text())
        except (OSError, UnicodeDecodeError, yaml.YAMLError):
            manifest = None
        problems = app_problems(manifest)
        manifest = manifest if isinstance(manifest, dict) else {}
        apps[path.parent.name] = {
            **manifest,
            "name": path.parent.name,
            "title": str(manifest.get("title") or path.parent.name),
            "description": str(manifest.get("description") or ""),
            "access": manifest.get("access") if isinstance(manifest.get("access"), list) else [],
            "connectors": manifest.get("connectors") if isinstance(manifest.get("connectors"), list) else [],
            "roles": manifest.get("roles") if isinstance(manifest.get("roles"), dict) else {},
            "audit": manifest.get("audit") if isinstance(manifest.get("audit"), list) else [],
            "audit_viewers": manifest.get("audit_viewers") if isinstance(manifest.get("audit_viewers"), list) else [],
            "audit_retention_days": manifest["audit_retention_days"]
            if valid_retention(manifest.get("audit_retention_days")) else None,
            "problems": problems,
        }
    return apps
