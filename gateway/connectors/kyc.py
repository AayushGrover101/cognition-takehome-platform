"""KYC review system (made-up data standing in for the compliance database)."""
import copy
import time

from . import ToolError, on_reset, tool

START = [
    {"id": "KYC-1001", "customer": "Ada Okafor", "country": "NG", "risk": "high", "status": "new", "tax_id": "529-41-2151"},
    {"id": "KYC-1002", "customer": "Lukas Meyer", "country": "DE", "risk": "low", "status": "new", "tax_id": "DE81 4417 0093"},
    {"id": "KYC-1003", "customer": "Mei Tanaka", "country": "JP", "risk": "medium", "status": "escalated", "tax_id": "4471-2209-6618"},
    {"id": "KYC-1004", "customer": "Carlos Ruiz", "country": "MX", "risk": "high", "status": "new", "tax_id": "RUIC800101HDF"},
    {"id": "KYC-1005", "customer": "Grace Liu", "country": "US", "risk": "low", "status": "approved", "tax_id": "318-60-7742"},
]
CASES = {}

SUMMARY = ["id", "customer", "country", "risk", "status"]
DETAIL = SUMMARY + ["tax_id_last4", "decided_by", "decision_reason"]


@on_reset
def reset():
    CASES.clear()
    for case in copy.deepcopy(START):
        case.update(decided_by=None, decision_reason=None, decided_at=None)
        CASES[case["id"]] = case


reset()


def find(case_id):
    if case_id not in CASES:
        raise ToolError(f"No case {case_id}")
    return CASES[case_id]


def last4(value):
    digits = [c for c in value if c.isalnum()]
    return "•••• " + "".join(digits[-4:])


@tool("kyc.list_cases", kind="read", returns=SUMMARY, inputs={"status": ["new", "escalated", "approved", "rejected", "any"]},
      description="Cases in the review queue, filtered by status.")
def list_cases(args, ctx):
    return [c for c in CASES.values() if args["status"] in ("any", c["status"])]


@tool("kyc.get_case", kind="read", returns=DETAIL, inputs={"case_id": "str"},
      description="One case, with only the last four characters of the tax ID.")
def get_case(args, ctx):
    case = find(args["case_id"])
    return {**case, "tax_id_last4": last4(case["tax_id"])}


@tool("kyc.get_case_full", kind="read", returns=DETAIL + ["tax_id"], inputs={"case_id": "str"},
      description="One case, including the full tax ID.")
def get_case_full(args, ctx):
    case = find(args["case_id"])
    return {**case, "tax_id_last4": last4(case["tax_id"])}


@tool("kyc.decide_case", kind="write", returns=DETAIL,
      inputs={"case_id": "str", "decision": ["approve", "reject"], "reason": "str"},
      description="Approve or reject a case. Refused if the case is already decided.")
def decide_case(args, ctx):
    case = find(args["case_id"])
    if case["status"] in ("approved", "rejected"):
        raise ToolError(f"{case['id']} is already {case['status']}")
    case.update(status="approved" if args["decision"] == "approve" else "rejected",
                decided_by=ctx["user"]["name"], decision_reason=args["reason"], decided_at=int(time.time()))
    return {**case, "tax_id_last4": last4(case["tax_id"])}


@tool("kyc.escalate_case", kind="write", returns=DETAIL, inputs={"case_id": "str", "reason": "str"},
      description="Send a new case to senior review.")
def escalate_case(args, ctx):
    case = find(args["case_id"])
    if case["status"] != "new":
        raise ToolError(f"Only new cases can be escalated; {case['id']} is {case['status']}")
    case.update(status="escalated", decision_reason=args["reason"])
    return {**case, "tax_id_last4": last4(case["tax_id"])}
