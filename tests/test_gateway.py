def test_signed_out_people_are_sent_to_sign_in(gateway):
    assert gateway().get("/").headers["location"] == "/signin"
    r = gateway().get("/apps/kyc-demo/")
    assert r.status_code == 303 and r.headers["location"] == "/signin?next=%2Fapps%2Fkyc-demo%2F"
    assert gateway().get("/api/kyc-demo/_me").status_code == 401


def test_sign_in_sets_cookie_and_redirects_safely(gateway):
    r = gateway().post("/signin", data={"user": "priya", "next": "/apps/kyc-demo/"})
    assert r.status_code == 303 and r.headers["location"] == "/apps/kyc-demo/"
    assert "gw_user=priya" in r.headers["set-cookie"] and "httponly" in r.headers["set-cookie"].lower()
    for bad in ["https://evil.example", "//evil.example", "/\\evil"]:
        assert gateway().post("/signin", data={"user": "priya", "next": bad}).headers["location"] == "/"
    assert gateway().post("/signin", data={"user": "nobody"}).headers["location"] == "/signin"


def test_portal_lists_only_apps_the_role_can_open(gateway):
    assert "KYC demo" in gateway("priya").get("/").text
    assert "KYC demo" not in gateway("marcus").get("/").text
    assert "Broken" not in gateway("sam").get("/").text


def test_app_access_is_checked_on_every_file(gateway):
    assert gateway("priya").get("/apps/kyc-demo/").status_code == 200
    assert gateway("priya").get("/apps/kyc-demo/app.js").status_code == 200
    for path in ["/apps/kyc-demo/", "/apps/kyc-demo/app.js"]:
        r = gateway("marcus").get(path)
        assert r.status_code == 403 and "have access to this app" in r.text


def test_invalid_app_is_not_served(gateway):
    r = gateway("sam").get("/apps/broken/")
    assert r.status_code == 403 and "Unknown role in access: wizard" in r.text
    assert gateway("priya").get("/apps/nope/").status_code == 404


def test_only_static_files_inside_the_app_folder(gateway):
    client = gateway("priya")
    assert client.get("/apps/kyc-demo/notes.txt").status_code == 404
    assert client.get("/apps/kyc-demo/app.yaml").status_code == 404
    assert client.get("/apps/kyc-demo/..%2F..%2Fshared%2Fui.css").status_code == 404


def test_app_pages_carry_the_browser_lockdown(gateway):
    r = gateway("priya").get("/apps/kyc-demo/")
    csp = r.headers["content-security-policy"]
    assert "connect-src 'self';" in csp and r.headers["referrer-policy"] == "same-origin"
    assert "default-src 'none'" in csp and "form-action 'none'" in csp
    assert r.headers["cache-control"] == "no-store"


def test_shared_files(gateway):
    r = gateway("priya").get("/shared/ui.css")
    assert r.status_code == 200 and "sandbox" in r.headers["content-security-policy"]
    assert gateway("priya").get("/shared/page.html").status_code == 404


def test_me_returns_user_and_app_only_to_people_with_access(gateway):
    data = gateway("dana").get("/api/kyc-demo/_me").json()["data"]
    assert data == {"user": {"name": "Dana Ortiz", "role": "compliance_officer", "title": "Compliance Officer",
                                 "admin": False},
                    "app": {"name": "kyc-demo", "title": "KYC demo"},
                    "tools": ["kyc.decide_case", "kyc.escalate_case", "kyc.get_case", "kyc.get_case_full",
                              "kyc.list_cases"],
                    "audit_trail": "/audit/kyc-demo"}
    assert gateway("marcus").get("/api/kyc-demo/_me").status_code == 403


def test_unreadable_manifest_only_breaks_that_app(gateway):
    assert gateway("priya").get("/").status_code == 200
    assert gateway("priya").get("/apps/kyc-demo/").status_code == 200
    assert gateway("priya").get("/apps/bad-encoding/").status_code == 403


def test_sign_in_keeps_the_page_you_asked_for(gateway):
    r = gateway().get("/apps/kyc-demo/app.js?case=KYC-1004")
    assert r.headers["location"] == "/signin?next=%2Fapps%2Fkyc-demo%2Fapp.js%3Fcase%3DKYC-1004"


def test_sign_in_page_offers_a_dropdown_of_accounts(gateway):
    text = gateway().get("/signin?next=/apps/kyc-demo/").text
    assert 'name="user" required>' in text and 'value="/apps/kyc-demo/"' in text
    assert '<option value="priya">Priya Shah \u2014 KYC Analyst</option>' in text
    assert '<option value="dana" selected>' in gateway("dana").get("/signin").text


def test_sign_out_clears_the_cookie(gateway):
    r = gateway("priya").post("/signout")
    assert r.status_code == 303 and r.headers["location"] == "/signin"
    assert 'gw_user=""' in r.headers["set-cookie"] or "Max-Age=0" in r.headers["set-cookie"]


def test_app_pages_get_the_gateway_top_bar_and_can_sign_out(gateway):
    assert gateway("priya").get("/web/topbar.js").status_code == 200
    r = gateway("priya").get("/signout?next=/apps/kyc-demo/")
    assert r.status_code == 303 and r.headers["location"] == "/signin?next=%2Fapps%2Fkyc-demo%2F"
    assert gateway("priya").get("/signout?next=//evil.test").headers["location"] == "/signin"


def test_sign_in_names_the_app_you_are_going_to(gateway):
    assert "Continue to KYC demo with your company account." in gateway().get("/signin?next=/apps/kyc-demo/").text
    assert "Use your company account to continue." in gateway().get("/signin?next=/apps/nope/").text
