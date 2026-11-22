"""Payments service refunds (made-up data)."""
import copy

from . import ToolError, on_reset, tool

START = [
    {"id": "RF-2001", "customer": "Jordan Blake", "amount": 42.50, "currency": "USD", "reason": "Duplicate charge", "status": "pending"},
    {"id": "RF-2002", "customer": "Priyanka Rao", "amount": 1250.00, "currency": "USD", "reason": "Service outage", "status": "pending"},
    {"id": "RF-2003", "customer": "Tom Becker", "amount": 18.00, "currency": "EUR", "reason": "Cancelled order", "status": "issued"},
]
REFUNDS = {}
FIELDS = ["id", "customer", "amount", "currency", "reason", "status", "handled_by", "note"]


@on_reset
def reset():
    REFUNDS.clear()
    for r in copy.deepcopy(START):
        r.update(handled_by=None, note=None)
        REFUNDS[r["id"]] = r


reset()


def pending(refund_id):
    refund = REFUNDS.get(refund_id)
    if not refund:
        raise ToolError(f"No refund {refund_id}")
    if refund["status"] != "pending":
        raise ToolError(f"{refund_id} is already {refund['status']}")
    return refund


@tool("refunds.list_refunds", kind="read", returns=FIELDS, inputs={"status": ["pending", "issued", "declined", "any"]},
      description="Refund requests, filtered by status.")
def list_refunds(args, ctx):
    return [r for r in REFUNDS.values() if args["status"] in ("any", r["status"])]


@tool("refunds.issue_refund", kind="write", returns=FIELDS, inputs={"refund_id": "str", "note": "str?"},
      description="Send the money back. Refused over 1,000 in any currency (needs a second approver).")
def issue_refund(args, ctx):
    refund = pending(args["refund_id"])
    if refund["amount"] > 1000:
        raise ToolError("Refunds over 1,000 need a second approver")
    refund.update(status="issued", handled_by=ctx["user"]["name"], note=args.get("note"))
    return refund


@tool("refunds.decline_refund", kind="write", returns=FIELDS, inputs={"refund_id": "str", "note": "str"},
      description="Decline a refund request with a reason.")
def decline_refund(args, ctx):
    refund = pending(args["refund_id"])
    refund.update(status="declined", handled_by=ctx["user"]["name"], note=args["note"])
    return refund
