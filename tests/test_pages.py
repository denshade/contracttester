import re

from markupsafe import escape

from app.formatting import format_timestamp
from app.seed import (
    ACTIVE_CONTRACT,
    ACTIVE_VERIFIED_AT,
    ACTIVE_VERIFIER,
    BILL_GET,
    BILL_POST,
    BILL_POST_PAYLOAD,
    BILL_POST_STATE,
    DOCK_PAYLOAD,
    DOCK_POST,
    DOCK_STATE,
    DOCK_VERIFIER,
    INACTIVE_CONTRACT,
    LEGACY_VERIFIED_AT,
    LEGACY_VERIFIER,
)


def test_timestamp_format():
    assert format_timestamp(ACTIVE_VERIFIED_AT) == "20 Oct 2026, 15:30 UTC"
    assert format_timestamp(LEGACY_VERIFIED_AT) == "1 Aug 2026, 09:00 UTC"
    assert format_timestamp(None) == "Not verified"


def test_login_and_logout(client):
    blocked = client.get("/contracts", follow_redirects=False)
    assert blocked.status_code == 303
    assert blocked.headers["location"].startswith("/login")

    bad = client.post(
        "/login",
        data={"username": "admin", "password": "wrong", "next": "/organization"},
        follow_redirects=False,
    )
    assert bad.status_code == 401
    assert "Incorrect username or password." in bad.text

    still_blocked = client.get("/organization", follow_redirects=False)
    assert still_blocked.status_code == 303

    good = client.post(
        "/login",
        data={"username": "admin", "password": "admin", "next": "/organization"},
        follow_redirects=False,
    )
    assert good.status_code == 303
    assert good.headers["location"] == "/organization"

    page = client.get("/organization")
    assert page.status_code == 200
    assert "Harbor" in page.text
    assert "No access token yet." in page.text

    client.post("/logout", follow_redirects=False)
    after = client.get("/organization", follow_redirects=False)
    assert after.status_code == 303
    assert after.headers["location"].startswith("/login")


def test_contracts_overview_shows_active_verifier_state(auth_client):
    page = auth_client.get("/contracts")
    assert page.status_code == 200
    assert "Active verifiers reflects the latest version" in page.text
    assert (
        f'data-contract-name="{ACTIVE_CONTRACT}"' in page.text
        and 'data-contract-name="Bill of Lading" data-contract-id="' in page.text
    )
    bill = re.search(
        rf'data-contract-name="{ACTIVE_CONTRACT}" data-contract-id="(\d+)" data-active="yes"',
        page.text,
    )
    dock = re.search(
        rf'data-contract-name="{INACTIVE_CONTRACT}" data-contract-id="(\d+)" data-active="no"',
        page.text,
    )
    assert bill and dock


def test_contract_details_versions_statements_and_removal(auth_client):
    overview = auth_client.get("/contracts")
    bill = re.search(
        rf'data-contract-name="{ACTIVE_CONTRACT}" data-contract-id="(\d+)" data-active="yes"',
        overview.text,
    )
    dock = re.search(
        rf'data-contract-name="{INACTIVE_CONTRACT}" data-contract-id="(\d+)" data-active="no"',
        overview.text,
    )
    assert bill and dock

    detail = auth_client.get(f"/contracts/{bill.group(1)}")
    assert detail.status_code == 200
    assert 'data-version="1" data-active="no"' in detail.text
    assert 'data-version="2" data-active="yes" data-current="true"' in detail.text
    assert f'data-verifier="{ACTIVE_VERIFIER}"' in detail.text
    assert format_timestamp(ACTIVE_VERIFIED_AT) in detail.text
    assert f'data-trigger="{BILL_GET}"' in detail.text
    assert f'data-trigger="{BILL_POST}"' in detail.text
    assert BILL_POST_STATE in detail.text
    assert escape(BILL_POST_PAYLOAD) in detail.text
    assert 'id="active-verifiers"' in detail.text

    version_one = re.search(
        r'data-version="1" data-active="no" data-current="false".*?href="(/contracts/\d+)"',
        detail.text,
        re.S,
    )
    assert version_one
    older = auth_client.get(version_one.group(1))
    assert "This version has no active verifiers." in older.text
    assert f'data-verifier="{LEGACY_VERIFIER}"' in older.text
    assert f'data-verified="{format_timestamp(LEGACY_VERIFIED_AT)}"' in older.text
    assert ACTIVE_VERIFIER not in older.text

    dock_page = auth_client.get(f"/contracts/{dock.group(1)}")
    assert "This version has no active verifiers." in dock_page.text
    assert f'data-trigger="{DOCK_POST}"' in dock_page.text
    assert DOCK_STATE in dock_page.text
    assert escape(DOCK_PAYLOAD) in dock_page.text
    assert f'data-verifier="{DOCK_VERIFIER}"' in dock_page.text
    assert 'data-verified="Not verified"' in dock_page.text

    confirm = auth_client.get(f"/contracts/{bill.group(1)}/remove")
    assert confirm.status_code == 200
    assert f"Are you sure you want to remove {ACTIVE_CONTRACT}?" in confirm.text
    assert auth_client.get("/contracts").text.count(f'data-contract-name="{ACTIVE_CONTRACT}"') == 1

    removed = auth_client.post(f"/contracts/{bill.group(1)}/remove", follow_redirects=True)
    assert removed.status_code == 200
    assert "Contract removed." in removed.text
    assert f'data-contract-name="{ACTIVE_CONTRACT}"' not in removed.text
    assert f'data-contract-name="{INACTIVE_CONTRACT}"' in removed.text
    assert auth_client.get(f"/contracts/{bill.group(1)}").status_code == 404
    assert auth_client.get(version_one.group(1)).status_code == 404


def test_organization_name_and_access_token(auth_client):
    renamed = auth_client.post("/organization", data={"name": "South Pier"}, follow_redirects=True)
    assert renamed.status_code == 200
    assert "Organization name saved." in renamed.text
    assert "South Pier" in renamed.text

    empty = auth_client.post("/organization", data={"name": "   "}, follow_redirects=False)
    assert empty.status_code == 400
    assert "Organization name is required" in empty.text

    issued = auth_client.post("/organization/token", follow_redirects=True)
    first = re.search(r'id="access-token">([^<]+)', issued.text)
    assert first
    assert "New access token issued." in issued.text
    authorized = auth_client.get("/api/contracts", headers={"Authorization": f"Bearer {first.group(1)}"})
    assert authorized.status_code == 200
    assert any(item["name"] == INACTIVE_CONTRACT for item in authorized.json())

    rotated = auth_client.post("/organization/token", follow_redirects=True)
    second = re.search(r'id="access-token">([^<]+)', rotated.text)
    assert second
    assert first.group(1) != second.group(1)
    assert auth_client.get("/api/users", headers={"Authorization": f"Bearer {first.group(1)}"}).status_code == 401
    assert auth_client.get("/api/users", headers={"Authorization": f"Bearer {second.group(1)}"}).status_code == 200
