"""Decides whether an app's list of operations is allowed under the current connector policy."""
from . import config


def audit_settings(app, operation):
    """Effective audit settings for one operation in one app. Returns (settings, problems)."""
    op = config.OPERATIONS[operation]
    base = op["audit"]
    override = (app.get("audit") or {}).get(operation) or {}
    problems = []
    enabled = override.get("enabled", True)
    if not enabled and base["required"]:
        problems.append(f"{operation}: auditing cannot be switched off (it changes data or returns masked fields)")
        enabled = True
    retention = override.get("retention_days", base["min_retention_days"])
    if not isinstance(retention, int) or retention < base["min_retention_days"]:
        problems.append(f"{operation}: retention must be at least {base['min_retention_days']} days")
        retention = base["min_retention_days"]
    extra = override.get("mask_inputs") or []
    if not isinstance(extra, list) or not all(isinstance(p, str) for p in extra):
        problems.append(f"{operation}: mask_inputs must be a list of input names")
        extra = []
    unknown = [p for p in extra if p not in op["params"]]
    if unknown:
        problems.append(f"{operation}: mask_inputs names unknown inputs {unknown}")
    mask_inputs = sorted(set(base["mask_inputs"]) | set(extra))
    return {"enabled": enabled, "retention_days": retention, "mask_inputs": mask_inputs}, problems


def evaluate_app(app):
    """Returns the list of reasons this app may not be published. Empty means it is allowed."""
    problems = []
    if app.get("_error"):
        return [app["_error"]]
    groups, blocked = config.connector_groups(), config.blocked_operations()
    unknown_roles = [r for r in app["access"] if r not in config.ROLES]
    if unknown_roles:
        problems.append(f"access lists unknown roles {unknown_roles}")
    used = {"internal": set(), "external": set()}
    for operation in app["operations"]:
        op = config.OPERATIONS.get(operation)
        if op is None:
            problems.append(f"{operation} is not in the connector catalogue")
            continue
        group = groups[op["connector"]]
        if group == "blocked":
            problems.append(f"{operation} uses the {op['connector']} connector, which is Blocked")
        else:
            used[group].add(op["connector"])
        if operation in blocked:
            problems.append(f"{operation} has been blocked by an admin")
        problems += audit_settings(app, operation)[1]
    for operation in app.get("audit") or {}:
        if operation not in app["operations"]:
            problems.append(f"audit settings name {operation}, which the app does not use")
    if used["internal"] and used["external"]:
        problems.append(
            "combines Internal connectors (" + ", ".join(sorted(used["internal"])) + ") with External connectors ("
            + ", ".join(sorted(used["external"])) + ")"
        )
    return problems
