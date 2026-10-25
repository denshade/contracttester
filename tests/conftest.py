import re

import pytest
from fastapi.testclient import TestClient

from app.factory import create_app


@pytest.fixture
def app(tmp_path):
    database = tmp_path / "test.db"
    return create_app(f"sqlite:///{database.as_posix()}")


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_client(client):
    response = client.post(
        "/login",
        data={"username": "admin", "password": "admin", "next": "/contracts"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return client


@pytest.fixture
def api(auth_client):
    page = auth_client.post("/organization/token", follow_redirects=True)
    assert page.status_code == 200
    match = re.search(r'id="access-token">([^<]+)', page.text)
    assert match, page.text
    auth_client.headers["Authorization"] = f"Bearer {match.group(1)}"
    return auth_client
