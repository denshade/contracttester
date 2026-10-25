import re

from markupsafe import escape

from app.formatting import format_timestamp
from app.seed import (
    ACTIVE_CONTRACT,
    ACTIVE_VERIFIED_AT,
    ACTIVE_VERIFIER,
    BILL_GET,
    BILL_GET_HEADER_LINES,
    BILL_GET_OUTCOME,
    BILL_POST,
    BILL_POST_HEADER_LINES,
    BILL_POST_OUTCOME,
    BILL_PUBLISHER,
    BILL_POST_PAYLOAD,
    BILL_POST_STATE,
    DOCK_OUTCOME,
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
    SCHEMA_HEADER_LINES,
    SCHEMA_TOKEN,
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


def test_contracts_can_be_created_edited_and_deleted(auth_client):
    listing = auth_client.get("/contracts")
    assert 'id="new-contract"' in listing.text
    bill = re.search(
        rf'data-contract-name="{ACTIVE_CONTRACT}" data-contract-id="(\d+)" data-active="yes"',
        listing.text,
    )
    assert bill
    assert f'href="/contracts/{bill.group(1)}"' in listing.text
    assert f'href="/contracts/{bill.group(1)}/edit"' in listing.text
    assert f'href="/contracts/{bill.group(1)}/remove"' in listing.text

    invalid = auth_client.post(
        "/contracts",
        data={"name": "   ", "publisher_name": "Desk"},
        follow_redirects=False,
    )
    assert invalid.status_code == 400
    assert "Name is required" in invalid.text

    created = auth_client.post(
        "/contracts",
        data={"name": "Parcel", "publisher_name": "Desk"},
        follow_redirects=True,
    )
    assert "Contract created." in created.text
    parcel = re.search(r'data-contract-name="Parcel" data-contract-id="(\d+)" data-active="no"', created.text)
    assert parcel
    assert 'data-publisher="Desk"' in created.text

    duplicate = auth_client.post(
        "/contracts",
        data={"name": "Parcel", "publisher_name": "Other"},
        follow_redirects=False,
    )
    assert duplicate.status_code == 409
    assert "A contract with this name already exists" in duplicate.text

    detail = auth_client.get(f"/contracts/{parcel.group(1)}")
    assert detail.status_code == 200
    assert "Version 1" in detail.text
    assert "This version has no statements." in detail.text

    clash = auth_client.post(
        f"/contracts/{parcel.group(1)}/edit",
        data={"name": ACTIVE_CONTRACT, "publisher_name": "Desk"},
        follow_redirects=False,
    )
    assert clash.status_code == 409

    edited = auth_client.post(
        f"/contracts/{parcel.group(1)}/edit",
        data={"name": "Parcel API", "publisher_name": "Pier Office"},
        follow_redirects=True,
    )
    assert "Contract saved." in edited.text
    assert 'data-contract-name="Parcel API"' in edited.text
    assert 'data-publisher="Pier Office"' in edited.text
    assert 'data-contract-name="Parcel"' not in edited.text

    deleted = auth_client.post(f"/contracts/{parcel.group(1)}/remove", follow_redirects=True)
    assert "Contract deleted." in deleted.text
    assert 'data-contract-name="Parcel API"' not in deleted.text
    assert f'data-contract-name="{ACTIVE_CONTRACT}"' in deleted.text

    renamed = auth_client.post(
        f"/contracts/{bill.group(1)}/edit",
        data={"name": "Bills", "publisher_name": "Pier Office"},
        follow_redirects=True,
    )
    assert 'data-contract-name="Bills"' in renamed.text
    assert 'data-publisher="Pier Office"' in renamed.text
    current = auth_client.get(f"/contracts/{bill.group(1)}")
    assert "<h1>Bills</h1>" in current.text
    assert 'value="Pier Office"' in current.text
    version_one = re.search(r'data-version="1".*?href="(/contracts/\d+)"', current.text, re.S)
    assert version_one
    older = auth_client.get(version_one.group(1))
    assert "<h1>Bills</h1>" in older.text
    assert f'value="{BILL_PUBLISHER}"' in older.text


def test_adding_a_statement_creates_the_next_version(auth_client):
    overview = auth_client.get("/contracts")
    bill = re.search(rf'data-contract-name="{ACTIVE_CONTRACT}" data-contract-id="(\d+)"', overview.text)
    assert bill
    detail = auth_client.get(f"/contracts/{bill.group(1)}")
    assert 'id="add-statement"' in detail.text
    version_one = re.search(r'data-version="1".*?href="(/contracts/\d+)"', detail.text, re.S)
    assert version_one
    older = auth_client.get(version_one.group(1))
    assert 'id="add-statement"' not in older.text
    assert 'id="statements-latest-only"' in older.text

    missing = auth_client.post(
        f"/contracts/{bill.group(1)}/statements",
        data={
            "verb": "GET",
            "trigger": "   ",
            "state": "200 OK",
            "payload": "",
            "expected_outcome": "Returned",
            "expected_headers": "",
        },
        follow_redirects=False,
    )
    assert missing.status_code == 400
    assert "Trigger endpoint is required" in missing.text

    rejected = auth_client.post(
        f"{version_one.group(1)}/statements",
        data={
            "verb": "DELETE",
            "trigger": "/bills/{id}",
            "state": "204 No Content",
            "payload": "",
            "expected_outcome": "The bill is removed",
            "expected_headers": "",
        },
        follow_redirects=False,
    )
    assert rejected.status_code == 409
    assert "latest version" in rejected.text

    added = auth_client.post(
        f"/contracts/{bill.group(1)}/statements",
        data={
            "verb": "POST",
            "trigger": "/receipts",
            "state": "202 Accepted",
            "payload": '{"ok":true}',
            "expected_outcome": "The receipt is stored",
            "expected_headers": "Location: /receipts/1",
        },
        follow_redirects=True,
    )
    assert added.status_code == 200
    assert "Statement added." in added.text
    assert 'data-version="3"' in added.text
    assert 'data-current="true"' in added.text
    assert 'data-verb="POST" data-trigger="/receipts"' in added.text
    assert "202 Accepted" in added.text
    assert "The receipt is stored" in added.text
    assert "Location: /receipts/1" in added.text
    assert escape('{"ok":true}') in added.text
    assert 'data-verb="POST" data-trigger="/bills"' in added.text
    previous = re.search(r'data-version="2".*?href="(/contracts/\d+)"', added.text, re.S)
    assert previous
    unchanged = auth_client.get(previous.group(1))
    assert 'data-trigger="/receipts"' not in unchanged.text
    assert 'data-verb="POST" data-trigger="/bills"' in unchanged.text
    assert 'data-version="2" data-active="yes" data-current="true"' in unchanged.text


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
    assert f'data-verb="GET" data-trigger="{BILL_GET}"' in detail.text
    assert f'data-verb="POST" data-trigger="{BILL_POST}"' in detail.text
    assert BILL_GET_OUTCOME in detail.text
    assert BILL_GET_HEADER_LINES in detail.text
    assert BILL_POST_STATE in detail.text
    assert BILL_POST_OUTCOME in detail.text
    assert BILL_POST_HEADER_LINES in detail.text
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
    assert f'data-verb="POST" data-trigger="{DOCK_POST}"' in dock_page.text
    assert DOCK_STATE in dock_page.text
    assert DOCK_OUTCOME in dock_page.text
    assert escape(DOCK_PAYLOAD) in dock_page.text
    assert f'data-verifier="{DOCK_VERIFIER}"' in dock_page.text
    assert 'data-verified="Not verified"' in dock_page.text

    confirm = auth_client.get(f"/contracts/{bill.group(1)}/remove")
    assert confirm.status_code == 200
    assert f"Are you sure you want to delete {ACTIVE_CONTRACT}?" in confirm.text
    assert auth_client.get("/contracts").text.count(f'data-contract-name="{ACTIVE_CONTRACT}"') == 1

    removed = auth_client.post(f"/contracts/{bill.group(1)}/remove", follow_redirects=True)
    assert removed.status_code == 200
    assert "Contract deleted." in removed.text
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
    assert f'value="{SCHEMA_TOKEN}"' in detail.text
    assert SCHEMA_HEADER_LINES in detail.text

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

    rejected = auth_client.post(
        f"/verifiers/{schema.group(1)}",
        data={
            "name": "Payload schema",
            "version": "4",
            "active": "false",
            "verification_trigger": "gitlab:payload-schema",
            "verification_token": "payload-token",
            "verification_headers": "Accept: application/json",
        },
        follow_redirects=False,
    )
    assert rejected.status_code == 400
    assert "http or https URL" in rejected.text

    broken_header = auth_client.post(
        f"/verifiers/{schema.group(1)}",
        data={
            "name": ACTIVE_VERIFIER,
            "version": "1",
            "active": "true",
            "verification_trigger": SCHEMA_TRIGGER,
            "verification_token": SCHEMA_TOKEN,
            "verification_headers": "Not a header",
        },
        follow_redirects=False,
    )
    assert broken_header.status_code == 400
    assert "Each header must look like Name: Value" in broken_header.text

    saved = auth_client.post(
        f"/verifiers/{schema.group(1)}",
        data={
            "name": "Payload schema",
            "version": "4",
            "active": "false",
            "verification_trigger": "https://ci.example/jobs/payload-schema",
            "verification_token": "payload-token",
            "verification_headers": "Accept: application/json\nX-Job: payload",
        },
        follow_redirects=True,
    )
    assert "Verifier saved." in saved.text
    assert 'value="Payload schema"' in saved.text
    assert 'value="4"' in saved.text
    assert 'value="false" selected' in saved.text
    assert 'value="https://ci.example/jobs/payload-schema"' in saved.text
    assert 'value="payload-token"' in saved.text
    assert "X-Job: payload" in saved.text

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
