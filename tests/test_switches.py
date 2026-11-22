import shutil

import pytest
import yaml

from gateway import audit, config, connectors, switches


@pytest.fixture()
def turn_off(tmp_path, monkeypatch):
    def write(**sections):
        f = tmp_path / "switches.yaml"
        f.write_text(yaml.safe_dump(sections))
        monkeypatch.setenv("SWITCHES_FILE", str(f))
    return write


def escalate(client):
    return client.post("/api/kyc-demo/kyc.escalate_case", json={"case_id": "KYC-1001", "reason": "PEP"})


def test_a_turned_off_app_is_blocked_everywhere(gateway, turn_off):
    turn_off(apps={"kyc-demo": "Incident INC-142"})
    dana = gateway("dana")
    assert dana.get("/apps/kyc-demo/").status_code == 503
    assert "Turned off" in dana.get("/").text and 'href="/apps/kyc-demo/"' not in dana.get("/").text
    r = escalate(dana)
    assert r.status_code == 503 and "Incident INC-142" in r.json()["error"]
    assert audit.entries("kyc-demo")[0]["outcome"] == "refused"
    assert "Incident INC-142" in gateway("sam").get("/admin").text
    turn_off()
    assert dana.get("/apps/kyc-demo/").status_code == 200 and escalate(dana).status_code == 200


def test_a_turned_off_connector_or_tool_refuses_calls(gateway, turn_off):
    dana = gateway("dana")
    turn_off(connectors={"kyc": "Vendor outage"})
    r = escalate(dana)
    assert r.status_code == 503 and "The kyc connector is turned off: Vendor outage" in r.json()["error"]
    assert dana.get("/apps/kyc-demo/").status_code == 200
    turn_off(tools={"kyc.escalate_case": "Escalation queue migration"})
    assert escalate(dana).status_code == 503
    assert dana.post("/api/kyc-demo/kyc.get_case", json={"case_id": "KYC-1001"}).status_code == 200
    assert "Escalation queue migration" in gateway("sam").get("/admin").text


def test_the_admin_page_has_no_switch_buttons(gateway):
    assert "<form" not in gateway("sam").get("/admin").text
    assert gateway("sam").post("/admin/switch", data={"kind": "app", "name": "kyc-demo"}).status_code in (404, 405)


@pytest.mark.parametrize("data", [["kyc"], {"apps": ["kyc-demo"]}, {"apps": {"kyc-demo": ""}}, {"connectors": {"kyc": None}},
                                  {"widgets": {}},
                                  False, [], {"apps": False}, {"apps": []}, {"tools": 0}])
def test_a_malformed_file_fails_closed(gateway, tmp_path, monkeypatch, data):
    (tmp_path / "bad.yaml").write_text(yaml.safe_dump(data))
    monkeypatch.setenv("SWITCHES_FILE", str(tmp_path / "bad.yaml"))
    with pytest.raises(ValueError):
        switches.load()


def test_the_repos_switches_file_is_valid_and_names_real_connectors_and_tools(monkeypatch):
    monkeypatch.delenv("SWITCHES_FILE", raising=False)
    data = switches.load()
    assert set(data["connectors"]) <= set(connectors.connectors())
    assert set(data["tools"]) <= set(connectors.TOOLS)


def test_invalid_folder_names_are_not_apps(tmp_path, monkeypatch):
    shutil.copytree(config.APPS_DIR, tmp_path / "repo")
    shutil.copytree(tmp_path / "repo" / "apps" / "kyc-demo", tmp_path / "repo" / "apps" / "_hidden")
    monkeypatch.setattr(config, "APPS_DIR", tmp_path / "repo")
    assert "_hidden" not in config.load_apps() and "kyc-demo" in config.load_apps()
