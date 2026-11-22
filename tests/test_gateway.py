def test_signed_out_people_are_sent_to_sign_in(gateway):
    assert gateway().get("/").headers["location"] == "/signin"
    r = gateway().get("/apps/kyc-demo/")
    assert r.status_code == 303 and r.headers["location"] == "/signin?next=/apps/kyc-demo/"
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
    r = gateway("priya").get("/apps/kyc-demo/", headers={"host": "tools.test"})
    csp = r.headers["content-security-policy"]
    assert "connect-src http://tools.test/api/kyc-demo/;" in csp
    assert "default-src 'none'" in csp and "form-action 'none'" in csp
    assert r.headers["cache-control"] == "no-store"


def test_shared_files(gateway):
    r = gateway("priya").get("/shared/ui.css")
    assert r.status_code == 200 and "sandbox" in r.headers["content-security-policy"]
    assert gateway("priya").get("/shared/page.html").status_code == 404


def test_me_returns_user_and_app_only_to_people_with_access(gateway):
    data = gateway("dana").get("/api/kyc-demo/_me").json()["data"]
    assert data == {"user": {"name": "Dana Ortiz", "role": "senior_reviewer"},
                    "app": {"name": "kyc-demo", "title": "KYC demo"}}
    assert gateway("marcus").get("/api/kyc-demo/_me").status_code == 403
