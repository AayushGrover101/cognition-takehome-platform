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


def test_admins_are_marked_in_sign_in_and_top_bar(gateway):
    signin = gateway().get("/signin").text
    assert "Sam Kim — Platform Engineer · Admin" in signin and "Priya Shah — KYC Analyst</option>" in signin
    assert '<span class="tag">Admin</span>' in gateway("sam").get("/").text
    assert '<span class="tag">Admin</span>' not in gateway("priya").get("/").text
