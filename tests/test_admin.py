def test_admin_page_is_for_platform_admins_only(gateway):
    assert gateway().get("/admin").headers["location"] == "/signin?next=%2Fadmin"
    assert gateway("dana").get("/admin").status_code == 403
    assert "/admin" not in gateway("dana").get("/").text
    assert 'href="/admin"' in gateway("sam").get("/").text


def test_admin_page_shows_apps_connectors_people_and_activity(gateway):
    gateway("dana").post("/api/kyc-demo/kyc.escalate_case", json={"case_id": "KYC-1001", "reason": "PEP match"})
    text = gateway("sam").get("/admin").text
    assert "Published" in text and "Not published" in text and "is Blocked" in text
    assert "<strong>Compliance Officer</strong>: <code>kyc.decide_case</code>" in text
    assert "<strong>gdrive</strong>" in text and "Blocked" in text
    assert "List grants" in text and "kyc_analyst must be a list of tool names" in text
    assert "Priya Shah" in text and "kyc.escalate_case" in text and '<td class="num">1</td>' in text and 'data-dialog="app-kyc-demo"' in text


def test_catalog_lists_roles_connectors_and_tools():
    from gateway.catalog import catalog
    c = catalog()
    assert c["roles"]["kyc_analyst"] == "KYC Analyst" and c["admin_roles"] == ["platform_engineer"]
    assert c["connectors"]["gdrive"] == {"group": "blocked"}
    assert c["tools"]["kyc.decide_case"]["kind"] == "write" and "tax_id" in c["tools"]["kyc.get_case_full"]["returns"]


def test_admins_are_marked_in_sign_in_and_top_bar(gateway):
    signin = gateway().get("/signin").text
    assert "Sam Kim — Platform Engineer · Admin" in signin and "Priya Shah — KYC Analyst</option>" in signin
    assert '<span class="tag">Admin</span>' in gateway("sam").get("/").text
    assert '<span class="tag">Admin</span>' not in gateway("priya").get("/").text


def test_admin_lists_exactly_which_tools_are_audited(gateway):
    text = gateway("sam").get("/admin").text
    assert '<dialog id="app-kyc-demo" class="modal">' in text and "Not set, entries are kept" in text
    assert "<code>kyc.get_case_full</code> <span class=\"note\">read</span>" in text
    assert "<code>kyc.decide_case</code> <span class=\"note\">write</span>" in text
    assert "<code>kyc.get_case</code> <span class=\"note\">" not in text


def test_admin_lists_audited_tools_no_role_is_granted(gateway, tmp_path, monkeypatch):
    from gateway import config
    apps = config.load_apps()
    kyc = apps["kyc-demo"]
    kyc["roles"] = {r: {"tools": ["kyc.list_cases"]} for r in kyc["roles"]}
    monkeypatch.setattr(config, "load_apps", lambda: apps)
    text = gateway("sam").get("/admin").text
    assert "<code>kyc.get_case_full</code> <span class=\"note\">read; no role granted, refusals only" in text


def test_app_modal_shows_that_apps_latest_calls(gateway):
    gateway("dana").post("/api/kyc-demo/kyc.escalate_case", json={"case_id": "KYC-1001", "reason": "PEP match"})
    text = gateway("sam").get("/admin").text
    modal = text[text.index('<dialog id="app-kyc-demo"'):]
    modal = modal[:modal.index("</dialog>")]
    assert "PEP match" in modal and 'href="/audit/kyc-demo">Search all 1 entries' in modal


def test_malformed_audit_viewers_dont_break_the_admin_page(gateway, monkeypatch):
    from gateway import config
    apps = config.load_apps()
    apps["kyc-demo"]["audit_viewers"] = [None, 3]
    monkeypatch.setattr(config, "load_apps", lambda: apps)
    assert gateway("sam").get("/admin").status_code == 200


def test_apps_are_high_risk_unless_listed_in_app_risk_yaml(gateway, monkeypatch):
    from gateway import catalog, config
    assert config.app_risk("kyc-demo") == "high" and catalog.catalog()["app_risk"] == {"default": "high", "low": []}
    assert "Every change needs an engineer" in gateway("sam").get("/admin").text
    monkeypatch.setattr(config, "low_risk_apps", lambda: ["kyc-demo"])
    assert config.app_risk("kyc-demo") == "low" and "Code-only changes publish without review" in gateway("sam").get("/admin").text


def test_malformed_role_and_connector_entries_are_reported_not_crashed_on(gateway, monkeypatch):
    from gateway import config
    assert "Unknown role in access: {'a': 1}" in config.app_problems({"title": "X", "access": [{"a": 1}]})
    assert "Unknown role in audit_viewers: [1]" in config.app_problems(
        {"title": "X", "access": ["kyc_analyst"], "audit_viewers": [[1]]})
    apps = config.load_apps()
    apps["kyc-demo"]["connectors"] = [123]
    monkeypatch.setattr(config, "load_apps", lambda: apps)
    assert gateway("sam").get("/admin").status_code == 200


def test_admin_activity_applies_each_apps_retention(gateway, monkeypatch):
    from datetime import timedelta
    from gateway import audit, config
    real = audit.now
    monkeypatch.setattr(audit, "now", lambda: real() - timedelta(days=40))
    audit.record("kyc-demo", config.users()["dana"], "kyc.escalate_case", "write", {"reason": "Old call"}, "ok")
    monkeypatch.setattr(audit, "now", real)
    apps = config.load_apps()
    apps["kyc-demo"]["audit_retention_days"] = 30
    monkeypatch.setattr(config, "load_apps", lambda: apps)
    assert "Old call" not in gateway("sam").get("/admin").text and audit.counts().get("kyc-demo", 0) == 0


def test_people_table_marks_apps_that_are_turned_off(gateway, monkeypatch):
    from gateway import switches
    monkeypatch.setattr(switches, "off", lambda kind: {"kyc-demo": "Paused"} if kind == "app" else {})
    text = gateway("sam").get("/admin").text
    assert " (turned off)" in text[text.index("Dana Ortiz"):]
