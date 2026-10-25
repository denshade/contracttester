import re

from markupsafe import escape

from app.formatting import format_timestamp
from app.seed import (
    ACTIVE_CONTRACT,
    ACTIVE_VERIFIED_AT,
    ACTIVE_VERIFIER,
    BILL_GET,
    BILL_POST,
    BILL_PUBLISHER,
    BILL_POST_PAYLOAD,
    BILL_POST_STATE,
    DOCK_PAYLOAD,
    DOCK_PUBLISHER,
    DOCK_POST,
    DOCK_STATE,
    DOCK_TRIGGER,
    DOCK_VERIFIER,
    INACTIVE_CONTRACT,
    LEGACY_TRIGGER,
    LEGACY_VERIFIED_AT,
    LEGACY_VERIFIER,
    SCHEMA_TRIGGER,
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
    assert "Active verifiers and the publisher reflect the latest version" in page.text
    assert f'data-publisher="{BILL_PUBLISHER}"' in page.text
    assert f'data-publisher="{DOCK_PUBLISHER}"' in page.text
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
    assert f'value="{BILL_PUBLISHER}"' in detail.text
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
    assert f'value="{BILL_PUBLISHER}"' in older.text
    assert "This version has no active verifiers." in older.text
    assert f'data-verifier="{LEGACY_VERIFIER}"' in older.text
    assert f'data-verified="{format_timestamp(LEGACY_VERIFIED_AT)}"' in older.text
    assert ACTIVE_VERIFIER not in older.text

    dock_page = auth_client.get(f"/contracts/{dock.group(1)}")
    assert f'value="{DOCK_PUBLISHER}"' in dock_page.text
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


def test_verifier_list_and_editable_details(auth_client):
    listing = auth_client.get("/verifiers")
    assert listing.status_code == 200
    schema = re.search(
        rf'data-verifier-name="{ACTIVE_VERIFIER}" data-verifier-id="(\d+)" data-active="yes"',
        listing.text,
    )
    assert schema
    assert LEGACY_TRIGGER in listing.text
    assert DOCK_TRIGGER in listing.text
    assert f'data-verifier-name="{LEGACY_VERIFIER}"' in listing.text
    assert f'data-verifier-name="{DOCK_VERIFIER}"' in listing.text

    detail = auth_client.get(f"/verifiers/{schema.group(1)}")
    assert detail.status_code == 200
    assert ACTIVE_CONTRACT in detail.text
    assert BILL_GET in detail.text
    assert format_timestamp(ACTIVE_VERIFIED_AT) in detail.text
    assert f'value="{SCHEMA_TRIGGER}"' in detail.text

    invalid = auth_client.post(
        f"/verifiers/{schema.group(1)}",
        data={
            "name": ACTIVE_VERIFIER,
            "version": "nope",
            "active": "true",
            "verification_trigger": SCHEMA_TRIGGER,
        },
        follow_redirects=False,
    )
    assert invalid.status_code == 400
    assert "Version must be a whole number" in invalid.text

    saved = auth_client.post(
        f"/verifiers/{schema.group(1)}",
        data={
            "name": "Payload schema",
            "version": "4",
            "active": "false",
            "verification_trigger": "gitlab:payload-schema",
        },
        follow_redirects=True,
    )
    assert "Verifier saved." in saved.text
    assert 'value="Payload schema"' in saved.text
    assert 'value="4"' in saved.text
    assert 'value="false" selected' in saved.text
    assert 'value="gitlab:payload-schema"' in saved.text

    refreshed = auth_client.get("/verifiers")
    assert 'data-verifier-name="Payload schema" data-verifier-id="' in refreshed.text
    assert re.search(r'data-verifier-name="Payload schema"[^>]*data-active="no"', refreshed.text)
    missing = auth_client.get("/verifiers/99999")
    assert missing.status_code == 404
    assert "That verifier is not in this organization." in missing.text


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
