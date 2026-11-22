"""Turned-off apps, connectors and tools, from switches.yaml in this repo. Changes go through pull requests,
so git history records who turned what off and why. Re-read on every request, so a merged change is live at once.
Turning something off removes access; turning it back on only restores what app.yaml already grants."""
import os
from pathlib import Path

import yaml

from .config import ROOT

KINDS = {"app": "apps", "connector": "connectors", "tool": "tools"}


def path():
    return Path(os.environ.get("SWITCHES_FILE", ROOT / "switches.yaml"))


def load():
    """{'apps': {name: reason}, 'connectors': {...}, 'tools': {...}}. A malformed file raises, so it fails closed."""
    try:
        data = yaml.safe_load(path().read_text()) or {}
    except FileNotFoundError:
        data = {}
    problems = file_problems(data)
    if problems:
        raise ValueError(f"{path().name} is invalid: {'; '.join(problems)}")
    return {key: dict(data.get(key) or {}) for key in KINDS.values()}


def file_problems(data):
    if not isinstance(data, dict):
        return ["the file must be a mapping"]
    problems = [f"unknown section {k}" for k in data if k not in KINDS.values()]
    for key in KINDS.values():
        section = data.get(key) or {}
        if not isinstance(section, dict):
            problems.append(f"{key} must map each name to a reason")
            continue
        problems += [f"{key}.{name} needs a reason" for name, reason in section.items()
                     if not isinstance(name, str) or not isinstance(reason, str) or not reason.strip()]
    return problems


def off(kind):
    return load()[KINDS[kind]]


def why(kind, name, title=None):
    reason = off(kind).get(name)
    what = title or (f"The {name} connector" if kind == "connector" else f"{name}")
    return reason and f"{what} is turned off: {reason}"
