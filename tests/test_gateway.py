import sqlite3

import pytest

from gateway import audit, config


def call(client, app, operation, **params):
    return client.post(f"/api/{app}/{operation}", json=params)


def high_risk_case(client):
    return next(c["id"] for c in call(client, "kyc-demo", "kyc.list_cases").json()["data"]
                if c["risk"] == "high" and c["status"] != "escalated")


def low_risk_case(client):
    return next(c["id"] for c in call(client, "kyc-demo", "kyc.list_cases").json()["data"]
                if c["risk"] == "low" and c["status"] != "escalated")


def test_must_be_signed_in(gateway):
    r = call(gateway(), "kyc-demo", "kyc.list_cases")
    assert r.status_code == 401
    assert gateway().get("/apps/kyc-demo/").status_code == 303


def test_masking_depends_on_the_users_role(gateway):
    analyst = call(gateway("priya"), "kyc-demo", "kyc.list_cases").json()["data"][0]
    senior = call(gateway("dana"), "kyc-demo", "kyc.list_cases").json()["data"][0]
    assert analyst["tax_id"].startswith("••••") and analyst["date_of_birth"].endswith("-••-••")
    assert "•" not in senior["tax_id"] and "•" not in senior["date_of_birth"]
    assert analyst["tax_id"][-4:] == senior["tax_id"][-4:]


def test_role_without_access_is_refused(gateway):
    r = call(gateway("marcus"), "kyc-demo", "kyc.list_cases")
    assert r.status_code == 403 and "may not use this app" in r.json()["error"]
    assert gateway("marcus").get("/apps/kyc-demo/").status_code == 403


def test_operation_not_on_the_apps_list_is_refused(gateway):
    r = call(gateway("priya"), "kyc-demo", "kyc.escalate_case", case_id="KYC-1001")
    assert r.status_code == 403 and "approved list" in r.json()["error"]
    r = call(gateway("marcus"), "rates", "refunds.list_refunds")
    assert r.status_code == 403


def test_business_rule_is_enforced_in_the_gateway(gateway):
    case_id = high_risk_case(gateway("priya"))
    r = call(gateway("priya"), "kyc-demo", "kyc.decide_case", case_id=case_id, decision="approve")
    assert r.status_code == 403 and "senior reviewer" in r.json()["error"]
    r = call(gateway("dana"), "kyc-demo", "kyc.decide_case", case_id=case_id, decision="approve")
    assert r.json()["data"]["status"] == "approved"
    r = call(gateway("priya"), "kyc-demo", "kyc.decide_case", case_id=low_risk_case(gateway("priya")),
             decision="reject", reason="Blurry document")
    assert r.status_code == 200


def test_inputs_are_validated(gateway):
    r = call(gateway("priya"), "kyc-demo", "kyc.list_cases", status="anything")
    assert r.status_code == 400
    r = call(gateway("priya"), "kyc-demo", "kyc.list_cases", sql="SELECT * FROM customers")
    assert r.status_code == 400 and "Unknown input" in r.json()["error"]


def test_app_cannot_combine_internal_and_external(gateway):
    r = call(gateway("priya"), "mixed", "kyc.list_cases")
    assert r.status_code == 403 and "combines Internal connectors" in r.json()["error"]
    assert gateway("priya").get("/apps/mixed/").status_code == 403
    # An admin moves Slack into the Internal group, as a Power Apps admin can.
    r = gateway("sam").post("/admin/api/connector-group", json={"connector": "slack", "group": "internal"})
    assert r.json()["ok"]
    assert call(gateway("priya"), "mixed", "kyc.list_cases").status_code == 200
    assert call(gateway("priya"), "mixed", "slack.post_message", channel="compliance", text="hi").status_code == 200
    outbox = gateway("sam").get("/admin/api/outbox").json()["rows"]
    assert outbox[0]["destination"] == "#compliance" and outbox[0]["app"] == "mixed"


def test_blocked_connector_and_blocked_operation(gateway):
    r = call(gateway("priya"), "mailer", "email.send_email", to="x@evil.example", subject="s", body="b")
    assert r.status_code == 403 and "Blocked" in r.json()["error"]
    gateway("sam").post("/admin/api/operation-block", json={"operation": "kyc.get_case", "blocked": True})
    r = call(gateway("priya"), "kyc-demo", "kyc.get_case", case_id="KYC-1001")
    assert r.status_code == 403 and "blocked by an admin" in r.json()["error"]


def test_every_call_is_recorded_including_refusals(gateway):
    case_id = high_risk_case(gateway("priya"))
    call(gateway("priya"), "kyc-demo", "kyc.decide_case", case_id=case_id, decision="approve", reason="looks fine")
    call(gateway("dana"), "kyc-demo", "kyc.decide_case", case_id=case_id, decision="approve", reason="verified")
    rows = gateway("sam").get("/admin/api/audit", params={"operation": "kyc.decide_case", "record": case_id}).json()["rows"]
    assert [(r["user_name"], r["outcome"]) for r in rows] == [("Dana Ortiz", "allowed"), ("Priya Shah", "refused")]
    assert rows[0]["inputs"] == {"case_id": case_id, "decision": "approve", "reason": "•••"}  # app asked to hide it
    assert rows[0]["retention_days"] == 3650 and rows[1]["retention_days"] == 2555


def test_audit_can_be_switched_off_only_where_allowed(gateway):
    assert call(gateway("priya"), "rates", "exchange_rates.get_rate", currency="EUR").status_code == 200
    assert gateway("sam").get("/admin/api/audit", params={"app": "rates"}).json()["rows"] == []
    # Refusals are recorded even when auditing is off.
    call(gateway("dana"), "rates", "exchange_rates.get_rate", currency="EUR")
    assert len(gateway("sam").get("/admin/api/audit", params={"app": "rates"}).json()["rows"]) == 1
    # An app may not switch off auditing, or shorten retention, on sensitive operations.
    sneaky = next(a for a in gateway("sam").get("/admin/api/state").json()["apps"] if a["name"] == "sneaky")
    assert sneaky["status"] == "blocked" and len(sneaky["problems"]) == 2


def test_audit_log_cannot_be_edited_or_deleted(gateway):
    call(gateway("priya"), "kyc-demo", "kyc.list_cases")
    db = config.db()
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        db.execute("UPDATE audit SET user_name = 'Someone else'")
    with pytest.raises(sqlite3.DatabaseError, match="retention"):
        db.execute("DELETE FROM audit")
    assert audit.verify()["ok"]


def test_tampering_is_detected(gateway):
    for _ in range(3):
        call(gateway("priya"), "kyc-demo", "kyc.list_cases")
    db = config.db()
    db.execute("DROP TRIGGER audit_no_update")
    db.execute("UPDATE audit SET user_name = 'Someone else' WHERE id = 2")
    assert audit.verify() == {"ok": False, "rows": 1, "broken_at": 2}


def test_expired_rows_are_removed_by_retention(gateway):
    for days in (30, -1, 30, -1):
        audit.record(None, "x", "kyc.list_cases", {}, "allowed", retention_days=days)
    assert audit.purge_expired() == 2
    assert audit.verify() == {"ok": True, "rows": 2, "broken_at": None}
    audit.record(None, "x", "kyc.list_cases", {}, "allowed", retention_days=30)
    assert audit.verify() == {"ok": True, "rows": 3, "broken_at": None}
    # A row removed any other way is still detected.
    db = config.db()
    db.execute("DROP TRIGGER audit_no_early_delete")
    db.execute("DELETE FROM audit WHERE id = 3")
    assert audit.verify()["ok"] is False


def test_malformed_requests_and_manifests(gateway, tmp_path, monkeypatch):
    r = gateway("priya").post("/api/kyc-demo/kyc.list_cases", content="[1, 2]")
    assert r.status_code == 400 and "JSON object" in r.json()["error"]
    assert gateway("priya").post("/api/kyc-demo/kyc.list_cases", content="not json").status_code == 400
    assert gateway().get("/signin", params={"next": "/\\evil.example/"}).text.count('value="/"') == 1
    assert gateway("priya").post("/csp-report", json={"csp-report": {"document-uri": "http://x/apps/kyc-demo/"}}).status_code == 204
    for i, text in enumerate(["- just\n- a list\n", "operations: kyc.list_cases\n", "audit: {kyc.list_cases: true}\n"]):
        (tmp_path / "apps" / f"broken-{i}").mkdir(parents=True)
        (tmp_path / "apps" / f"broken-{i}" / "app.yaml").write_text(text)
    monkeypatch.setattr(config, "APPS_DIR", tmp_path)
    apps = {a["name"]: a for a in gateway("sam").get("/admin/api/state").json()["apps"]}
    assert len(apps) == 3 and all(a["status"] == "blocked" for a in apps.values())
    assert call(gateway("priya"), "broken-1", "kyc.list_cases").status_code == 403


def test_apps_are_served_with_the_browser_rule(gateway):
    r = gateway("priya").get("/apps/kyc-demo/")
    csp = r.headers["content-security-policy"]
    assert "connect-src http://testserver/api/kyc-demo/;" in csp and "default-src 'none'" in csp
    assert gateway("priya").get("/apps/kyc-demo/notes.txt").status_code == 404
    assert gateway("priya").get("/apps/kyc-demo/..%2f..%2f..%2f..%2fpolicy.yaml").status_code == 404
    assert gateway("priya").get("/apps/kyc-demo/app.yaml").status_code == 404


def test_only_admins_can_use_the_admin_api(gateway):
    assert gateway("priya").get("/admin/api/state").status_code == 403
    r = gateway("priya").post("/admin/api/user-role", json={"user": "priya", "role": "admin"})
    assert r.status_code == 403
    assert gateway("sam").post("/admin/api/user-role", json={"user": "marcus", "role": "analyst"}).json()["ok"]
    assert call(gateway("marcus"), "kyc-demo", "kyc.list_cases").status_code == 200
