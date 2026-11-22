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
    assert "Priya Shah" in text and "kyc.escalate_case" in text and "1 entries" in text


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
    assert "tools audited</summary>" in text
    assert "<code>kyc.get_case_full</code> <span class=\"note\">read, opted in</span>" in text
    assert "<code>kyc.decide_case</code> <span class=\"note\">write, always</span>" in text
    assert "<code>kyc.get_case</code> <span class=\"note\">" not in text


def test_admin_lists_audited_tools_no_role_is_granted(gateway, tmp_path, monkeypatch):
    from gateway import config
    apps = config.load_apps()
    kyc = apps["kyc-demo"]
    kyc["roles"] = {r: {"tools": ["kyc.list_cases"]} for r in kyc["roles"]}
    monkeypatch.setattr(config, "load_apps", lambda: apps)
    text = gateway("sam").get("/admin").text
    assert "<code>kyc.get_case_full</code> <span class=\"note\">read, opted in; no role granted, refusals only" in text
