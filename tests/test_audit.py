import sqlite3

from gateway import audit


def call(client, tool, inputs=None, app="kyc-demo"):
    return client.post(f"/api/{app}/{tool}", json=inputs or {})


def test_reads_are_not_audited_unless_the_app_opts_in(gateway):
    priya = gateway("priya")
    call(priya, "kyc.list_cases", {"status": "any"})
    call(priya, "kyc.get_case", {"case_id": "KYC-1001"})
    assert audit.entries("kyc-demo") == []
    call(gateway("dana"), "kyc.get_case_full", {"case_id": "KYC-1001"})
    [row] = audit.entries("kyc-demo")
    assert (row["user_name"], row["tool"], row["kind"], row["outcome"]) == ("Dana Ortiz", "kyc.get_case_full", "read", "ok")


def test_writes_are_always_audited_including_refusals(gateway):
    dana, priya = gateway("dana"), gateway("priya")
    call(dana, "kyc.decide_case", {"case_id": "KYC-1001", "decision": "approve", "reason": "Docs verified"})
    call(dana, "kyc.decide_case", {"case_id": "KYC-1001", "decision": "reject", "reason": "Changed my mind"})
    call(priya, "kyc.decide_case", {"case_id": "KYC-1002", "decision": "approve", "reason": "x"})
    rows = audit.entries("kyc-demo")
    assert [(r["user_id"], r["outcome"]) for r in reversed(rows)] == [("dana", "ok"), ("dana", "refused"), ("priya", "refused")]
    assert rows[0]["detail"] == "Your role (KYC Analyst) can't use kyc.decide_case in this app"
    assert rows[1]["detail"] == "KYC-1001 is already approved"
    assert rows[2]["inputs"] == {"case_id": "KYC-1001", "decision": "approve", "reason": "Docs verified"}


def test_the_browser_cannot_switch_auditing_off(gateway):
    r = call(gateway("dana"), "kyc.escalate_case", {"case_id": "KYC-1001", "reason": "PEP match", "audit": False})
    assert r.status_code == 400
    call(gateway("dana"), "kyc.escalate_case", {"case_id": "KYC-1001", "reason": "PEP match"})
    assert len(audit.entries("kyc-demo")) == 1


def test_each_app_has_its_own_trail(gateway):
    call(gateway("dana"), "kyc.escalate_case", {"case_id": "KYC-1001", "reason": "PEP match"})
    call(gateway("lena"), "slack.post_message", {"channel": "#support", "text": "Fixed"}, app="notifier")
    assert [r["tool"] for r in audit.entries("kyc-demo")] == ["kyc.escalate_case"]
    assert [r["tool"] for r in audit.entries("notifier")] == ["slack.post_message"]
    assert audit.entries("kyc-demo")[0]["seq"] == audit.entries("notifier")[0]["seq"] == 1


def test_tampering_breaks_the_chain(gateway, tmp_path):
    dana = gateway("dana")
    for case in ["KYC-1001", "KYC-1002", "KYC-1004"]:
        call(dana, "kyc.escalate_case", {"case_id": case, "reason": "check"})
    assert audit.verify("kyc-demo") == (True, None)
    with sqlite3.connect(tmp_path / "audit.db") as conn:
        conn.execute("UPDATE audit SET user_name = 'Someone else' WHERE app = 'kyc-demo' AND seq = 2")
    assert audit.verify("kyc-demo") == (False, 2)
    assert "Chain broken at entry 2" in gateway("sam").get("/audit/kyc-demo").text


def test_audit_page_is_for_audit_viewers_and_admins_only(gateway):
    call(gateway("dana"), "kyc.escalate_case", {"case_id": "KYC-1001", "reason": "PEP match"})
    for user in ["dana", "sam"]:
        r = gateway(user).get("/audit/kyc-demo")
        assert r.status_code == 200 and "kyc.escalate_case" in r.text and "Chain intact" in r.text
    assert gateway("priya").get("/audit/kyc-demo").status_code == 403
    assert gateway().get("/audit/kyc-demo").headers["location"] == "/signin?next=%2Faudit%2Fkyc-demo"


def test_audit_settings_are_checked(gateway):
    text = gateway("priya").get("/apps/bad-grants/").text
    assert "audit_reads: unknown tool kyc.nope" in text and "Unknown role in audit_viewers: wizard" in text


def test_entries_across_apps_are_newest_first(gateway):
    call(gateway("dana"), "kyc.escalate_case", {"case_id": "KYC-1001", "reason": "PEP match"})
    call(gateway("lena"), "slack.post_message", {"channel": "#support", "text": "a"}, app="notifier")
    call(gateway("dana"), "kyc.escalate_case", {"case_id": "KYC-1002", "reason": "PEP match"})
    assert [(r["app"], r["seq"]) for r in audit.entries()] == [("kyc-demo", 2), ("notifier", 1), ("kyc-demo", 1)]
