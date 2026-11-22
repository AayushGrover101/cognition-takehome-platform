"""Where things live: people and roles (policy.yaml) and the apps (a checkout of the apps repo)."""
import os
from pathlib import Path

import yaml

from .connectors import TOOLS, connectors

ROOT = Path(__file__).resolve().parent.parent
APPS_DIR = Path(os.environ.get("APPS_DIR", ROOT.parent / "cognition-takehome-apps"))
POLICY = yaml.safe_load((ROOT / "policy.yaml").read_text())
ROLES = POLICY["roles"]
GROUPS = ("internal", "external", "blocked")


def users():
    return {u["id"]: dict(u) for u in POLICY["users"]}


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
    internal = [c for c in known if connector_group(c) == "internal"]
    external = [c for c in known if connector_group(c) == "external"]
    if internal and external:
        problems.append(f"An app can't combine Internal ({', '.join(internal)}) and External "
                        f"({', '.join(external)}) connectors")
    return problems


def grant_problems(roles, access, declared):
    if not isinstance(roles, dict):
        return ["roles must map each role to its tools"]
    problems = []
    for role, grants in roles.items():
        if role not in (access if isinstance(access, list) else []):
            problems.append(f"Role {role} has tools but is not in access")
        tools = grants.get("tools") if isinstance(grants, dict) else None
        if not isinstance(tools, list) or not all(isinstance(t, str) for t in tools):
            problems.append(f"{role}: tools must be a list of tool names")
            continue
        for pattern in tools:
            connector = pattern.split(".", 1)[0]
            if pattern.endswith(".*"):
                if pattern.count(".") != 1 or connector not in declared:
                    problems.append(f"{role}: {pattern} needs {connector} in connectors")
            elif pattern not in TOOLS:
                problems.append(f"{role}: unknown tool {pattern}")
            elif connector not in declared:
                problems.append(f"{role}: {pattern} needs {connector} in connectors")
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
        problems += [f"Unknown role in access: {r}" for r in access if r not in ROLES]
    declared = manifest.get("connectors", [])
    problems += connector_problems(declared)
    declared = declared if isinstance(declared, list) else []
    problems += grant_problems(manifest.get("roles", {}), access, declared)
    return problems


def load_apps():
    """Re-read on every request, so a merged app is live as soon as the checkout is updated."""
    apps = {}
    for path in sorted((APPS_DIR / "apps").glob("*/app.yaml")):
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
            "access": manifest.get("access") if isinstance(manifest.get("access"), list) else [],
            "connectors": manifest.get("connectors") if isinstance(manifest.get("connectors"), list) else [],
            "roles": manifest.get("roles") if isinstance(manifest.get("roles"), dict) else {},
            "problems": problems,
        }
    return apps
