from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, Contract, Publisher, Statement, User, Verifier, VerifierTest

COMPANY_NAME = "Harbor & Co."
ACTIVE_CONTRACT = "Bill of Lading"
INACTIVE_CONTRACT = "Dock Appointment"
BILL_GET = "GET /bills/{id}"
BILL_GET_STATE = "200 OK"
BILL_POST = "POST /bills"
BILL_POST_STATE = "201 Created"
BILL_POST_PAYLOAD = '{"shipper":"Harbor"}'
DOCK_POST = "POST /docks"
DOCK_STATE = "202 Accepted"
DOCK_PAYLOAD = '{"dock":"B"}'
ACTIVE_VERIFIER = "Schema shape"
LEGACY_VERIFIER = "Legacy checksum"
DOCK_VERIFIER = "Window check"
ACTIVE_VERIFIED_AT = datetime(2026, 10, 20, 15, 30, tzinfo=timezone.utc)
LEGACY_VERIFIED_AT = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)
SCHEMA_TEST = "status is present"
LEGACY_TEST = "checksum matches"
DOCK_TEST = "slot is in the future"


def seed_if_empty(db: Session) -> None:
    if db.scalar(select(Company.id).limit(1)) is not None:
        return

    company = Company(name=COMPANY_NAME)
    User(
        company=company,
        name="Admin",
        email="admin@harbor.test",
        username="admin",
        password="admin",  # temporary sign-in; this credential will be replaced later
    )
    _contract(
        company,
        ACTIVE_CONTRACT,
        1,
        [
            _statement(
                BILL_GET,
                BILL_GET_STATE,
                "",
                [_verifier(LEGACY_VERIFIER, 1, False, LEGACY_VERIFIED_AT, [LEGACY_TEST])],
            )
        ],
    )
    _contract(
        company,
        ACTIVE_CONTRACT,
        2,
        [
            _statement(
                BILL_GET,
                BILL_GET_STATE,
                "",
                [_verifier(ACTIVE_VERIFIER, 1, True, ACTIVE_VERIFIED_AT, [SCHEMA_TEST])],
            ),
            _statement(BILL_POST, BILL_POST_STATE, BILL_POST_PAYLOAD, []),
        ],
    )
    _contract(
        company,
        INACTIVE_CONTRACT,
        1,
        [
            _statement(
                DOCK_POST,
                DOCK_STATE,
                DOCK_PAYLOAD,
                [_verifier(DOCK_VERIFIER, 3, False, None, [DOCK_TEST])],
            )
        ],
    )
    db.add(company)
    db.commit()


def _verifier(name: str, version: int, active: bool, last_verified_at: datetime | None, tests: list[str]) -> Verifier:
    verifier = Verifier(name=name, version=version, active=active, last_verified_at=last_verified_at)
    for test_name in tests:
        VerifierTest(verifier=verifier, name=test_name)
    return verifier


def _statement(trigger: str, expected_state: str, payload: str, verifiers: list[Verifier]) -> Statement:
    statement = Statement(trigger=trigger, expected_state=expected_state, payload=payload)
    for verifier in verifiers:
        verifier.statement = statement
    return statement


def _contract(company: Company, name: str, version: int, statements: list[Statement]) -> Contract:
    contract = Contract(company=company, name=name, version=version)
    Publisher(contract=contract)
    for statement in statements:
        statement.contract = contract
    return contract
