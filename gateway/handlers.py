"""What each operation actually does. All data here is made up; in production these call real systems.

Business rules live here, in the gateway, so no app can skip them.
"""
import random
import time

from . import config


class Refused(Exception):
    """A business rule said no."""


DATA = {}


def reset_data():
    rnd = random.Random(7)
    first = ["Amara", "Liam", "Sofia", "Noah", "Yuki", "Elena", "Omar", "Grace", "Mateo", "Ines", "Tariq", "Hana"]
    last = ["Okafor", "Brandt", "Rossi", "Nguyen", "Tanaka", "Petrov", "Haddad", "Mills", "Silva", "Kowalski"]
    countries = ["US", "GB", "DE", "NG", "BR", "JP", "AE", "CA"]
    now = time.time()
    cases = {}
    for i in range(24):
        cid = f"KYC-{1001 + i}"
        risk = rnd.choice(["low", "low", "medium", "medium", "high"])
        cases[cid] = {
            "id": cid,
            "name": f"{rnd.choice(first)} {rnd.choice(last)}",
            "country": rnd.choice(countries),
            "risk": risk,
            "status": rnd.choice(["new", "new", "in_review", "in_review", "escalated"]),
            "tax_id": f"{rnd.randint(100, 899)}-{rnd.randint(10, 99)}-{rnd.randint(1000, 9999)}",
            "date_of_birth": f"{rnd.randint(1955, 2003)}-{rnd.randint(1, 12):02d}-{rnd.randint(1, 28):02d}",
            "submitted_at": now - rnd.randint(1, 72) * 3600,
            "decided_by": None,
            "flags": rnd.sample(["Document mismatch", "Sanctions name match", "High-risk country", "PEP"],
                                k=2 if risk == "high" else rnd.randint(0, 1)),
        }
    refunds = {}
    reasons = ["Duplicate charge", "Item not received", "Cancelled subscription", "Fraud claim", "Goodwill"]
    for i in range(18):
        rid = f"RF-{2001 + i}"
        name = f"{rnd.choice(first)} {rnd.choice(last)}"
        refunds[rid] = {
            "id": rid,
            "customer": name,
            "email": name.lower().replace(" ", ".") + "@example.com",
            "amount": rnd.choice([18, 42, 75, 120, 260, 480, 650, 1200]),
            "currency": rnd.choice(["USD", "USD", "EUR", "GBP"]),
            "reason": rnd.choice(reasons),
            "status": "pending" if i < 14 else rnd.choice(["issued", "declined"]),
            "requested_at": now - rnd.randint(1, 96) * 3600,
            "handled_by": None,
        }
    DATA.clear()
    DATA.update(cases=cases, refunds=refunds, slack={
        "compliance": [{"ts": now - 5400, "author": "Dana Ortiz", "text": "Reminder: escalations need a note."}],
        "support": [{"ts": now - 7200, "author": "Lena Novak", "text": "Refund backlog is under 20 today."}],
        "general": [{"ts": now - 86400, "author": "Sam Kim", "text": "Quarterly access review starts Monday."}],
    })


reset_data()


def _case(params):
    case = DATA["cases"].get(params["case_id"])
    if not case:
        raise Refused(f"No case {params['case_id']}")
    return case


def _refund(params):
    refund = DATA["refunds"].get(params["refund_id"])
    if not refund:
        raise Refused(f"No refund {params['refund_id']}")
    return refund


def kyc_list_cases(params, user, app):
    rows = sorted(DATA["cases"].values(), key=lambda c: c["submitted_at"])
    status = params.get("status")
    return [{k: v for k, v in c.items() if k != "flags"} for c in rows if not status or c["status"] == status]


def kyc_get_case(params, user, app):
    return dict(_case(params))


def kyc_decide_case(params, user, app):
    case = _case(params)
    if case["status"] in ("approved", "rejected"):
        raise Refused("This case has already been decided")
    if (case["risk"] == "high" or case["status"] == "escalated") and user["role"] != "senior_reviewer":
        raise Refused("High-risk and escalated cases can only be decided by a senior reviewer")
    case["status"] = "approved" if params["decision"] == "approve" else "rejected"
    case["decided_by"] = user["name"]
    return {"id": case["id"], "status": case["status"], "decided_by": user["name"]}


def kyc_escalate_case(params, user, app):
    case = _case(params)
    if case["status"] in ("approved", "rejected"):
        raise Refused("This case has already been decided")
    case["status"] = "escalated"
    return {"id": case["id"], "status": "escalated"}


def refunds_list_refunds(params, user, app):
    rows = sorted(DATA["refunds"].values(), key=lambda r: r["requested_at"])
    status = params.get("status")
    return [dict(r) for r in rows if not status or r["status"] == status]


def refunds_issue_refund(params, user, app):
    refund = _refund(params)
    if refund["status"] != "pending":
        raise Refused("Only a pending refund can be issued")
    if refund["amount"] > 500 and user["role"] != "support_lead":
        raise Refused("Refunds over 500 can only be issued by a support lead")
    refund["status"], refund["handled_by"] = "issued", user["name"]
    return {"id": refund["id"], "status": "issued", "handled_by": user["name"]}


def refunds_decline_refund(params, user, app):
    refund = _refund(params)
    if refund["status"] != "pending":
        raise Refused("Only a pending refund can be declined")
    refund["status"], refund["handled_by"] = "declined", user["name"]
    return {"id": refund["id"], "status": "declined", "handled_by": user["name"]}


def _send_outside(service, destination, content, user, app):
    # Nothing is really sent. The admin page shows this table as "what left the company".
    config.db().execute(
        "INSERT INTO outbox (ts, service, destination, content, user_name, app) VALUES (?, ?, ?, ?, ?, ?)",
        (time.time(), service, destination, content, user["name"], app),
    )


def slack_list_messages(params, user, app):
    return list(DATA["slack"][params["channel"]])


def slack_post_message(params, user, app):
    DATA["slack"][params["channel"]].append({"ts": time.time(), "author": user["name"], "text": params["text"]})
    _send_outside("Slack", "#" + params["channel"], params["text"], user, app)
    return {"posted": True}


def exchange_rates_get_rate(params, user, app):
    rates = {"USD": 1.0, "EUR": 1.08, "GBP": 1.27, "CAD": 0.73, "JPY": 0.0066}
    return {"currency": params["currency"], "usd_rate": rates[params["currency"]], "as_of": time.strftime("%Y-%m-%d")}


def email_send_email(params, user, app):
    _send_outside("Email", params["to"], params["subject"] + "\n" + params["body"], user, app)
    return {"sent": True}


def handler_for(operation):
    return globals()[operation.replace(".", "_")]
