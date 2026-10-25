import re

import pytest
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError

from app.models import Company, Contract, Publisher, Statement, User, Verifier, VerifierTest
from app.seed import ACTIVE_CONTRACT, ACTIVE_VERIFIER, DOCK_VERIFIER, LEGACY_VERIFIER, SCHEMA_TEST


def _versions(api, name):
    return sorted(
        (item for item in api.get("/api/contracts").json() if item["name"] == name),
        key=lambda item: item["version"],
    )


def _statements(api, contract_id):
    return [item for item in api.get("/api/statements").json() if item["contract_id"] == contract_id]


def _verifiers(api, statement_id):
    return [item for item in api.get("/api/verifiers").json() if item["statement_id"] == statement_id]


def test_api_requires_access_token(client):
    missing = client.get("/api/contracts")
    assert missing.status_code == 401
    rejected = client.get("/api/contracts", headers={"Authorization": "Bearer nope"})
    assert rejected.status_code == 401


def test_seed_relationships(api):
    contracts = api.get("/api/contracts").json()
    publishers = api.get("/api/publishers").json()
    users = api.get("/api/users").json()
    assert sorted(item["contract_id"] for item in publishers) == sorted(item["id"] for item in contracts)
    assert {item["name"] for item in contracts} == {ACTIVE_CONTRACT, "Dock Appointment"}
    assert sorted(item["version"] for item in contracts if item["name"] == ACTIVE_CONTRACT) == [1, 2]
    assert set(users[0]) == {"id", "name", "email", "company_id"}
    verifier_names = {item["name"] for item in api.get("/api/verifiers").json()}
    assert verifier_names == {ACTIVE_VERIFIER, LEGACY_VERIFIER, DOCK_VERIFIER}
    test_names = {item["name"] for item in api.get("/api/tests").json()}
    assert SCHEMA_TEST in test_names
    assert len(publishers) == len(contracts)


def test_contract_name_and_version_are_unique(app):
    inspector = inspect(app.state.engine)
    constraints = inspector.get_unique_constraints("contracts")
    assert any(item["column_names"] == ["name", "version"] for item in constraints)

    with app.state.SessionLocal() as db:
        company = db.scalar(select(Company))
        db.add(Contract(company_id=company.id, name="Dup", version=1))
        db.commit()
        db.add(Contract(company_id=company.id, name="Dup", version=1))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        db.add(Contract(company_id=company.id, name="Dup", version=2))
        db.commit()

        contract = db.scalar(select(Contract).where(Contract.name == "Dup", Contract.version == 1))
        db.add(Publisher(contract_id=contract.id))
        db.commit()
        db.add(Publisher(contract_id=contract.id))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_adding_or_removing_a_statement_creates_a_new_version(api):
    created = api.post(
        "/api/contracts",
        json={
            "name": "Orders",
            "statements": [{"trigger": "GET /orders", "expected_state": "200 OK", "payload": ""}],
        },
    )
    assert created.status_code == 201
    first = created.json()
    assert first["version"] == 1
    assert isinstance(first["version"], int)
    assert api.post("/api/contracts", json={"name": "Orders"}).status_code == 409
    assert api.post("/api/contracts", json={"name": "  "}).status_code == 422

    original = _statements(api, first["id"])[0]
    verifier = api.post(
        "/api/verifiers",
        json={
            "statement_id": original["id"],
            "name": "Shape",
            "version": 1,
            "active": True,
            "last_verified_at": "2026-10-20T15:30:00Z",
        },
    )
    assert verifier.status_code == 201
    test = api.post("/api/tests", json={"verifier_id": verifier.json()["id"], "name": "has id"})
    assert test.status_code == 201

    added = api.post(
        "/api/statements",
        json={
            "contract_id": first["id"],
            "trigger": "POST /orders",
            "expected_state": "201 Created",
            "payload": '{"a": 1}',
        },
    )
    assert added.status_code == 201
    created_statement = added.json()
    assert created_statement["contract_version"] == 2
    assert created_statement["contract_id"] != first["id"]

    assert [item["version"] for item in _versions(api, "Orders")] == [1, 2]
    assert [item["trigger"] for item in _statements(api, first["id"])] == ["GET /orders"]
    assert _verifiers(api, original["id"])[0]["id"] == verifier.json()["id"]

    second_id = created_statement["contract_id"]
    copied = next(item for item in _statements(api, second_id) if item["trigger"] == "GET /orders")
    fresh = next(item for item in _statements(api, second_id) if item["trigger"] == "POST /orders")
    copied_verifier = _verifiers(api, copied["id"])[0]
    assert copied_verifier["id"] != verifier.json()["id"]
    assert copied_verifier["name"] == "Shape"
    assert copied_verifier["active"] is True
    assert copied_verifier["last_verified_at"].startswith("2026-10-20T15:30:00")
    assert _verifiers(api, fresh["id"]) == []
    copied_tests = [item for item in api.get("/api/tests").json() if item["verifier_id"] == copied_verifier["id"]]
    assert copied_tests[0]["name"] == "has id"
    assert copied_tests[0]["id"] != test.json()["id"]

    updated = api.put(
        f"/api/statements/{original['id']}",
        json={"trigger": "GET /orders", "expected_state": "200 OK", "payload": '{"changed":true}'},
    )
    assert updated.status_code == 200
    assert [item["version"] for item in _versions(api, "Orders")] == [1, 2]
    assert _statements(api, first["id"])[0]["payload"] == '{"changed":true}'
    assert next(item for item in _statements(api, second_id) if item["trigger"] == "GET /orders")["payload"] == ""

    removed = api.delete(f"/api/statements/{fresh['id']}")
    assert removed.status_code == 200
    body = removed.json()
    assert body["statement_id"] == fresh["id"]
    assert body["contract"]["version"] == 3
    assert api.get(f"/api/statements/{fresh['id']}").status_code == 200
    third_id = body["contract"]["id"]
    assert all(item["trigger"] != "POST /orders" for item in _statements(api, third_id))
    assert any(item["trigger"] == "POST /orders" for item in _statements(api, second_id))

    rejected_add = api.post(
        "/api/statements",
        json={
            "contract_id": first["id"],
            "trigger": "DELETE /orders",
            "expected_state": "204 No Content",
            "payload": "",
        },
    )
    assert rejected_add.status_code == 409
    rejected_remove = api.delete(f"/api/statements/{original['id']}")
    assert rejected_remove.status_code == 409
    assert [item["version"] for item in _versions(api, "Orders")] == [1, 2, 3]

    contracts = api.get("/api/contracts").json()
    publishers = api.get("/api/publishers").json()
    assert sorted(item["contract_id"] for item in publishers) == sorted(item["id"] for item in contracts)


def test_rename_keeps_the_version_family_together(api):
    created = api.post(
        "/api/contracts",
        json={"name": "Parcel", "statements": [{"trigger": "GET /parcels", "expected_state": "200 OK", "payload": ""}]},
    ).json()
    api.post(
        "/api/statements",
        json={"contract_id": created["id"], "trigger": "POST /parcels", "expected_state": "201 Created", "payload": "{}"},
    )
    renamed = api.put(f"/api/contracts/{created['id']}", json={"name": "Parcel API"})
    assert renamed.status_code == 200
    assert [item["version"] for item in _versions(api, "Parcel API")] == [1, 2]
    assert _versions(api, "Parcel") == []


def test_delete_one_version_keeps_the_others(api):
    created = api.post(
        "/api/contracts",
        json={"name": "Crates", "statements": [{"trigger": "GET /crates", "expected_state": "200 OK", "payload": ""}]},
    ).json()
    added = api.post(
        "/api/statements",
        json={"contract_id": created["id"], "trigger": "POST /crates", "expected_state": "201 Created", "payload": "{}"},
    ).json()
    assert api.delete(f"/api/contracts/{created['id']}").status_code == 204
    assert api.get(f"/api/contracts/{created['id']}").status_code == 404
    remaining = api.get(f"/api/contracts/{added['contract_id']}")
    assert remaining.status_code == 200
    assert remaining.json()["version"] == 2
    assert all(item["contract_id"] != created["id"] for item in api.get("/api/statements").json())


def test_verifier_and_test_crud_and_overview_flag(api):
    created = api.post(
        "/api/contracts",
        json={"name": "Yard Check", "statements": [{"trigger": "GET /yard", "expected_state": "200 OK", "payload": "{}"}]},
    ).json()
    statement = _statements(api, created["id"])[0]
    verifier = api.post(
        "/api/verifiers",
        json={"statement_id": statement["id"], "name": "Yard schema", "version": 4, "active": True},
    )
    assert verifier.status_code == 201
    verifier_id = verifier.json()["id"]
    page = api.get("/contracts")
    assert re_active(page.text, "Yard Check") == "yes"

    updated = api.put(
        f"/api/verifiers/{verifier_id}",
        json={
            "statement_id": statement["id"],
            "name": "Yard schema",
            "version": 5,
            "active": False,
            "last_verified_at": None,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 5
    assert updated.json()["active"] is False
    assert re_active(api.get("/contracts").text, "Yard Check") == "no"

    created_test = api.post("/api/tests", json={"verifier_id": verifier_id, "name": "slot exists"})
    assert created_test.status_code == 201
    test_id = created_test.json()["id"]
    renamed = api.put(f"/api/tests/{test_id}", json={"verifier_id": verifier_id, "name": "slot is open"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "slot is open"
    assert api.delete(f"/api/tests/{test_id}").status_code == 204
    assert api.get(f"/api/tests/{test_id}").status_code == 404
    assert api.delete(f"/api/verifiers/{verifier_id}").status_code == 204
    assert api.get(f"/api/verifiers/{verifier_id}").status_code == 404


def test_publisher_stays_one_to_one(api):
    publishers = api.get("/api/publishers").json()
    publisher = publishers[0]
    assert api.delete(f"/api/publishers/{publisher['id']}").status_code == 409
    moved = api.put(
        f"/api/publishers/{publisher['id']}",
        json={"contract_id": publishers[1]["contract_id"]},
    )
    assert moved.status_code == 409
    kept = api.put(
        f"/api/publishers/{publisher['id']}",
        json={"contract_id": publisher["contract_id"]},
    )
    assert kept.status_code == 200
    assert kept.json()["id"] == publisher["id"]
    assert api.post("/api/publishers", json={"contract_id": publisher["contract_id"]}).status_code == 409


def test_user_and_company_crud(api, app):
    created = api.post("/api/users", json={"name": "Ada Lovelace", "email": "ada@example.com"})
    assert created.status_code == 201
    body = created.json()
    assert "password" not in body
    updated = api.put(f"/api/users/{body['id']}", json={"name": "Ada", "email": "ada@harbor.test"})
    assert updated.status_code == 200
    assert updated.json()["email"] == "ada@harbor.test"
    assert api.post("/api/users", json={"name": "Ada", "email": "not-an-email"}).status_code == 422
    assert api.delete(f"/api/users/{body['id']}").status_code == 204
    assert api.get(f"/api/users/{body['id']}").status_code == 404

    company = api.get("/api/companies").json()[0]
    renamed = api.put(f"/api/companies/{company['id']}", json={"name": "South Pier"})
    assert renamed.status_code == 200
    assert renamed.json() == {"id": company["id"], "name": "South Pier"}
    assert api.post("/api/companies", json={"name": "Other"}).status_code == 409
    assert api.get("/api/companies/99999").status_code == 404

    assert api.delete(f"/api/companies/{company['id']}").status_code == 204
    assert api.get("/api/companies").status_code == 401
    with app.state.SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Company)) == 0
        assert db.scalar(select(func.count()).select_from(User)) == 0
        assert db.scalar(select(func.count()).select_from(Contract)) == 0
        assert db.scalar(select(func.count()).select_from(Publisher)) == 0
        assert db.scalar(select(func.count()).select_from(Statement)) == 0
        assert db.scalar(select(func.count()).select_from(Verifier)) == 0
        assert db.scalar(select(func.count()).select_from(VerifierTest)) == 0


def re_active(html: str, name: str) -> str:
    match = re.search(rf'data-contract-name="{name}" data-contract-id="\d+" data-active="([^"]+)"', html)
    assert match, html
    return match.group(1)
