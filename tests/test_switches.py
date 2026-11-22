from gateway import audit, switches

ADMIN_FORM = {"sec-fetch-site": "same-origin", "sec-fetch-dest": "document", "referer": "http://testserver/admin"}


def flip(client, kind, name, enabled, reason="", headers=ADMIN_FORM):
    return client.post("/admin/switch", data={"kind": kind, "name": name, "enabled": "1" if enabled else "0",
                                              "reason": reason}, headers=headers)


def escalate(client):
    return client.post("/api/kyc-demo/kyc.escalate_case", json={"case_id": "KYC-1001", "reason": "PEP"})


def test_turning_an_app_off_blocks_it_everywhere_and_is_recorded(gateway):
    sam, dana = gateway("sam"), gateway("dana")
    assert flip(sam, "app", "kyc-demo", False, "Incident INC-142").status_code == 303
    assert dana.get("/apps/kyc-demo/").status_code == 503
    assert "Turned off" in dana.get("/").text and 'href="/apps/kyc-demo/"' not in dana.get("/").text
    r = escalate(dana)
    assert r.status_code == 503 and "Incident INC-142" in r.json()["error"]
    assert audit.entries("kyc-demo")[0]["outcome"] == "refused"
    [change] = audit.entries(switches.PLATFORM_TRAIL)
    assert change["tool"] == "admin.turn_off_app" and change["inputs"] == {"app": "kyc-demo", "reason": "Incident INC-142"}
    assert "Turn back on" in sam.get("/admin").text
    flip(sam, "app", "kyc-demo", True)
    assert dana.get("/apps/kyc-demo/").status_code == 200 and escalate(dana).status_code == 200


def test_turning_a_connector_off_refuses_its_tools(gateway):
    sam, dana = gateway("sam"), gateway("dana")
    flip(sam, "connector", "kyc", False, "Vendor outage")
    r = escalate(dana)
    assert r.status_code == 503 and "The kyc connector is turned off" in r.json()["error"]
    assert dana.get("/apps/kyc-demo/").status_code == 200
    flip(sam, "connector", "kyc", True)
    assert escalate(dana).status_code == 200


def test_only_admins_using_the_admin_page_can_flip_switches(gateway):
    assert flip(gateway("dana"), "app", "kyc-demo", False, "x").status_code == 403
    sam = gateway("sam")
    from_app = {"sec-fetch-site": "same-origin", "sec-fetch-dest": "empty", "referer": "http://testserver/apps/kyc-demo/"}
    assert flip(sam, "app", "kyc-demo", False, "x", headers=from_app).status_code == 403
    assert flip(sam, "app", "kyc-demo", False, "").status_code == 400
    assert flip(sam, "app", "nope", False, "x").status_code == 404
    assert switches.off("app") == {}


def test_reserved_names_are_not_apps(tmp_path, monkeypatch):
    import shutil
    from gateway import config
    shutil.copytree(config.APPS_DIR, tmp_path / "repo")
    shutil.copytree(tmp_path / "repo" / "apps" / "kyc-demo", tmp_path / "repo" / "apps" / switches.PLATFORM_TRAIL)
    monkeypatch.setattr(config, "APPS_DIR", tmp_path / "repo")
    assert switches.PLATFORM_TRAIL not in config.load_apps() and "kyc-demo" in config.load_apps()
