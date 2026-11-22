"""Connectors: engineer-owned menus of named tools, one connector per system.

A tool declares its inputs, the fields it returns and whether it reads or writes. The gateway checks
the inputs, runs the tool and drops any field the tool did not declare. Business rules stay in the
system behind the connector; a tool refuses by raising ToolError with a reason people can read.
"""
from dataclasses import dataclass, field
from importlib import import_module

MODULES = ["kyc", "refunds", "flags", "slack", "gdrive"]
TOOLS = {}
RESETS = []


class ToolError(Exception):
    """The system behind the connector refused the request."""


@dataclass
class Tool:
    name: str
    kind: str
    inputs: dict
    returns: list
    handler: object
    description: str = ""
    connector: str = field(init=False)

    def __post_init__(self):
        self.connector = self.name.split(".", 1)[0]


def tool(name, *, kind, returns, inputs=None, description=""):
    if kind not in ("read", "write"):
        raise ValueError(f"{name}: kind must be read or write")

    def register(fn):
        TOOLS[name] = Tool(name, kind, inputs or {}, list(returns), fn, description)
        return fn
    return register


def on_reset(fn):
    RESETS.append(fn)
    return fn


def reset():
    """Put every connector's made-up data back to its starting state."""
    for fn in RESETS:
        fn()


def connectors():
    return sorted({t.connector for t in TOOLS.values()})


def check_inputs(spec, data):
    """Inputs are written as {'case_id': 'str', 'limit': 'int?', 'decision': ['approve', 'reject']}."""
    if not isinstance(data, dict):
        return None, "Inputs must be a JSON object"
    unknown = sorted(set(data) - set(spec))
    if unknown:
        return None, f"Unknown input: {', '.join(unknown)}"
    clean = {}
    for name, kind in spec.items():
        optional = isinstance(kind, str) and kind.endswith("?")
        value = data.get(name)
        if value is None:
            if not optional:
                return None, f"Missing input: {name}"
            continue
        if isinstance(kind, list):
            ok = value in kind
            expected = "one of " + ", ".join(map(str, kind))
        else:
            base = kind.rstrip("?")
            ok = {
                "str": isinstance(value, str) and value.strip() != "",
                "int": isinstance(value, int) and not isinstance(value, bool),
                "number": isinstance(value, (int, float)) and not isinstance(value, bool),
                "bool": isinstance(value, bool),
            }[base]
            expected = {"str": "text", "int": "a whole number", "number": "a number", "bool": "true or false"}[base]
        if not ok:
            return None, f"{name} must be {expected}"
        clean[name] = value
    return clean, None


def keep_declared(result, returns):
    if isinstance(result, dict):
        return {k: v for k, v in result.items() if k in returns}
    if isinstance(result, list):
        return [keep_declared(r, returns) for r in result]
    return result


for module in MODULES:
    import_module(f"{__name__}.{module}")
