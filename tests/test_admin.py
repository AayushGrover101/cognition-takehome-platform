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
