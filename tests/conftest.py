import os
from pathlib import Path

os.environ["APPS_DIR"] = str(Path(__file__).parent / "fixtures" / "apps_repo")

import pytest
from starlette.testclient import TestClient

from gateway import audit, connectors
from gateway.main import create_app


@pytest.fixture(autouse=True)
def fresh_data(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_DB", str(tmp_path / "audit.db"))
    connectors.reset()


@pytest.fixture()
def gateway():
    app = create_app()

    def as_user(user_id=None):
        client = TestClient(app, follow_redirects=False)
        if user_id:
            client.cookies.set("gw_user", user_id)
        return client

    return as_user
