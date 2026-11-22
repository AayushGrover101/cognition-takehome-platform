import os
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


def test_filters_and_search(gateway):
    dana, priya = gateway("dana"), gateway("priya")
    call(dana, "kyc.escalate_case", {"case_id": "KYC-1001", "reason": "PEP match"})
    call(priya, "kyc.escalate_case", {"case_id": "KYC-1002", "reason": "Address mismatch"})
    call(dana, "kyc.get_case_full", {"case_id": "KYC-1002"})
    assert [r["user_id"] for r in audit.entries("kyc-demo", user="priya")] == ["priya"]
    assert [r["tool"] for r in audit.entries("kyc-demo", kind="read")] == ["kyc.get_case_full"]
    assert {r["inputs"]["case_id"] for r in audit.entries("kyc-demo", q="KYC-1002")} == {"KYC-1002"}
    assert [r["user_id"] for r in audit.entries("kyc-demo", q="pep")] == ["dana"]
    assert audit.entries("kyc-demo", q="100%") == []
    page = gateway("sam").get("/audit/kyc-demo", params={"q": "mismatch"}).text
    assert "1 matching" in page and "Address mismatch" in page and "PEP match" not in page
    assert '<option value="priya">Priya Shah</option>' in page


def test_retention_deletes_old_entries_and_the_chain_still_checks(gateway, monkeypatch):
    from datetime import timedelta
    real = audit.now
    user = {"id": "dana", "name": "Dana Ortiz", "role": "compliance_officer"}
    for days_ago in (400, 300, 10):
        monkeypatch.setattr(audit, "now", lambda d=days_ago: real() - timedelta(days=d))
        audit.record("x", user, "kyc.escalate_case", "write", {"n": days_ago}, "ok")
    monkeypatch.setattr(audit, "now", real)
    audit.record("x", user, "kyc.escalate_case", "write", {"n": 0}, "ok", retention_days=365)
    assert [r["inputs"]["n"] for r in audit.entries("x")] == [0, 10, 300]
    assert audit.verify("x") == (True, None)
    with sqlite3.connect(os.environ["AUDIT_DB"]) as conn:
        conn.execute("DELETE FROM audit WHERE app = 'x' AND seq = 2")
    assert audit.verify("x") == (False, 3)


def test_chain_continues_after_everything_is_pruned(gateway, monkeypatch):
    from datetime import timedelta
    real = audit.now
    user = {"id": "dana", "name": "Dana Ortiz", "role": "compliance_officer"}
    monkeypatch.setattr(audit, "now", lambda: real() - timedelta(days=50))
    audit.record("x", user, "kyc.escalate_case", "write", {}, "ok")
    monkeypatch.setattr(audit, "now", real)
    audit.prune("x", 30)
    assert audit.entries("x") == []
    audit.record("x", user, "kyc.escalate_case", "write", {}, "ok")
    assert [r["seq"] for r in audit.entries("x")] == [2] and audit.verify("x") == (True, None)


def test_retention_is_validated_against_the_company_minimum():
    from gateway import config
    assert config.app_problems({"title": "t", "access": ["engineer"], "audit_retention_days": 30}) == [
        "audit_retention_days must be a whole number of days, at least 1825"]
    assert config.app_problems({"title": "t", "access": ["engineer"], "audit_retention_days": 3650}) == []
    assert config.load_apps()["kyc-demo"]["audit_retention_days"] == 2555


def test_prune_keeps_unexpired_entries_even_if_clocks_went_backwards(gateway, monkeypatch):
    from datetime import timedelta
    real = audit.now
    user = {"id": "dana", "name": "Dana Ortiz", "role": "compliance_officer"}
    for days_ago in (400, 10, 400):
        monkeypatch.setattr(audit, "now", lambda d=days_ago: real() - timedelta(days=d))
        audit.record("x", user, "kyc.escalate_case", "write", {"n": days_ago}, "ok")
    monkeypatch.setattr(audit, "now", real)
    audit.prune("x", 365)
    assert [r["seq"] for r in audit.entries("x")] == [3, 2] and audit.verify("x") == (True, None)


def test_search_matches_non_ascii_inputs(gateway):
    user = {"id": "dana", "name": "Dana Ortiz", "role": "compliance_officer"}
    audit.record("x", user, "kyc.escalate_case", "write", {"reason": "José Núñez"}, "ok")
    assert len(audit.entries("x", q="José")) == 1 and audit.verify("x") == (True, None)
