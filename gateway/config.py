"""Where things live: people and roles (policy.yaml) and the apps (a checkout of the apps repo)."""
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
APPS_DIR = Path(os.environ.get("APPS_DIR", ROOT.parent / "cognition-takehome-apps"))
POLICY = yaml.safe_load((ROOT / "policy.yaml").read_text())
ROLES = POLICY["roles"]


def users():
    return {u["id"]: dict(u) for u in POLICY["users"]}


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
            "problems": problems,
        }
    return apps
