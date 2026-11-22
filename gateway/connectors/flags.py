"""Feature-flag service (made-up data)."""
import copy

from . import ToolError, on_reset, tool

START = [
    {"key": "new_checkout", "description": "New checkout flow", "env": "prod", "enabled": False, "rollout": 0},
    {"key": "instant_payouts", "description": "Instant payouts for verified merchants", "env": "prod", "enabled": True, "rollout": 25},
    {"key": "kyc_auto_approve_low_risk", "description": "Auto-approve low-risk KYC cases", "env": "staging", "enabled": True, "rollout": 100},
]
FLAGS = {}
FIELDS = ["key", "description", "env", "enabled", "rollout", "changed_by"]


@on_reset
def reset():
    FLAGS.clear()
    for f in copy.deepcopy(START):
        f["changed_by"] = None
        FLAGS[f["key"]] = f


reset()


@tool("flags.list_flags", kind="read", returns=FIELDS, inputs={"env": ["prod", "staging", "any"]},
      description="Flags and their current state.")
def list_flags(args, ctx):
    return [f for f in FLAGS.values() if args["env"] in ("any", f["env"])]


@tool("flags.set_flag", kind="write", returns=FIELDS, inputs={"key": "str", "enabled": "bool", "rollout": "int?"},
      description="Turn a flag on or off and optionally set its rollout percentage (0-100).")
def set_flag(args, ctx):
    flag = FLAGS.get(args["key"])
    if not flag:
        raise ToolError(f"No flag {args['key']}")
    rollout = args.get("rollout", flag["rollout"])
    if not 0 <= rollout <= 100:
        raise ToolError("rollout must be between 0 and 100")
    flag.update(enabled=args["enabled"], rollout=rollout, changed_by=ctx["user"]["name"])
    return flag
