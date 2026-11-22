def call(client, tool, inputs=None, app="kyc-demo"):
    return client.post(f"/api/{app}/{tool}", json=inputs or {})


def test_granted_tools_run_and_return_only_declared_fields(gateway):
    r = call(gateway("priya"), "kyc.list_cases", {"status": "new"})
    assert r.status_code == 200 and r.json()["ok"]
    cases = r.json()["data"]
    assert [c["id"] for c in cases] == ["KYC-1001", "KYC-1002", "KYC-1004"]
    assert set(cases[0]) == {"id", "customer", "country", "risk", "status"}
    case = call(gateway("priya"), "kyc.get_case", {"case_id": "KYC-1001"}).json()["data"]
    assert case["tax_id_last4"] == "•••• 2151" and "tax_id" not in case


def test_tools_are_denied_unless_granted_to_the_role(gateway):
    r = call(gateway("priya"), "kyc.get_case_full", {"case_id": "KYC-1001"})
    assert r.status_code == 403 and r.json()["error"] == "Your role (KYC Analyst) can't use kyc.get_case_full in this app"
    assert call(gateway("priya"), "kyc.decide_case",
                {"case_id": "KYC-1001", "decision": "approve", "reason": "ok"}).status_code == 403


def test_wildcard_grants_every_tool_of_the_connector(gateway):
    dana = gateway("dana")
    assert call(dana, "kyc.get_case_full", {"case_id": "KYC-1001"}).json()["data"]["tax_id"] == "529-41-2151"
    r = call(dana, "kyc.decide_case", {"case_id": "KYC-1001", "decision": "approve", "reason": "Docs verified"})
    assert r.json()["data"]["status"] == "approved" and r.json()["data"]["decided_by"] == "Dana Ortiz"


def test_tools_outside_the_apps_connectors_do_not_exist_for_it(gateway):
    r = call(gateway("dana"), "refunds.list_refunds", {"status": "any"})
    assert r.status_code == 404 and "no tool called refunds.list_refunds" in r.json()["error"]
    assert call(gateway("dana"), "kyc.nope").status_code == 404


def test_people_who_cannot_open_the_app_cannot_call_its_tools(gateway):
    assert call(gateway(), "kyc.list_cases", {"status": "any"}).status_code == 401
    assert call(gateway("marcus"), "kyc.list_cases", {"status": "any"}).status_code == 403
    assert call(gateway("sam"), "kyc.list_cases", {"status": "any"}, app="mixed").status_code == 403


def test_inputs_are_checked_before_the_tool_runs(gateway):
    dana = gateway("dana")
    cases = [({}, "Missing input: case_id"),
             ({"case_id": "KYC-1001", "decision": "maybe", "reason": "x"}, "decision must be one of approve, reject"),
             ({"case_id": "KYC-1001", "decision": "approve", "reason": "  "}, "reason must be text"),
             ({"case_id": "KYC-1001", "decision": "approve", "reason": "x", "force": True}, "Unknown input: force")]
    for inputs, error in cases:
        r = call(dana, "kyc.decide_case", inputs)
        assert r.status_code == 400 and r.json()["error"] == error
    assert dana.post("/api/kyc-demo/kyc.get_case", json=["KYC-1001"]).json()["error"] == "Inputs must be a JSON object"
    assert dana.post("/api/kyc-demo/kyc.get_case", content="{", headers={"content-type": "application/json"}).status_code == 400
    assert dana.post("/api/kyc-demo/kyc.get_case", data={"case_id": "KYC-1001"}).status_code == 415
    assert dana.get("/api/kyc-demo/kyc.get_case").status_code == 405


def test_business_rules_in_the_system_refuse_with_a_reason(gateway):
    dana = gateway("dana")
    r = call(dana, "kyc.decide_case", {"case_id": "KYC-1005", "decision": "reject", "reason": "x"})
    assert r.status_code == 409 and r.json() == {"ok": False, "error": "KYC-1005 is already approved"}


def test_external_app_works_for_granted_roles_only(gateway):
    r = call(gateway("lena"), "slack.post_message", {"channel": "#support", "text": "Outage resolved"}, app="notifier")
    assert r.status_code == 200 and set(r.json()["data"]) == {"channel", "text", "sent_at"}
    assert call(gateway("marcus"), "slack.post_message", {"channel": "#support", "text": "hi"}, app="notifier").status_code == 403


def test_connector_policy_is_enforced_when_the_app_is_loaded(gateway):
    sam = gateway("sam")
    mixed = sam.get("/apps/mixed/")
    assert mixed.status_code == 403 and "combine Internal (kyc) and External (slack)" in mixed.text
    assert "Connector gdrive is Blocked" in sam.get("/apps/drive-backup/").text
    bad = gateway("priya").get("/apps/bad-grants/").text
    for problem in ["kyc_analyst: unknown tool kyc.delete_everything", "kyc_analyst: refunds.* needs refunds in connectors",
                    "kyc_analyst: refunds.issue_refund needs refunds in connectors", "Role platform_engineer has tools but is not in access"]:
        assert problem in bad


def test_me_lists_the_roles_tools_for_this_app(gateway):
    assert gateway("priya").get("/api/kyc-demo/_me").json()["data"]["tools"] == [
        "kyc.escalate_case", "kyc.get_case", "kyc.list_cases"]
    assert gateway("marcus").get("/api/notifier/_me").json()["data"]["tools"] == []
