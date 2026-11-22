import os
import tempfile
from pathlib import Path

os.environ["PLATFORM_DB"] = str(Path(tempfile.mkdtemp()) / "test.db")
os.environ["APPS_DIR"] = str(Path(__file__).parent / "fixtures" / "apps_repo")

import pytest
from starlette.testclient import TestClient

from gateway import config, handlers
from gateway.main import create_app


@pytest.fixture()
def gateway():
    config.close_db()
    Path(os.environ["PLATFORM_DB"]).unlink(missing_ok=True)
    handlers.reset_data()
    app = create_app()

    def as_user(user_id=None):
        client = TestClient(app, follow_redirects=False)
        if user_id:
            client.cookies.set("gw_user", user_id)
        return client

    return as_user
