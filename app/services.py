"""Contract versioning and persistence.

Adding or removing a statement forks a new numeric version of that contract.
The previous version stays as it was. Name and version together are unique.
A contract version always has one publisher.
"""

import re
import secrets
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.errors import DomainError
from app.formatting import format_timestamp
from app.models import Company, Contract, Publisher, Statement, User, Verifier, VerifierTest
from app.triggers import clean_http_url, clean_token, dump_headers, format_headers, load_headers, parse_header_block

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class ContractSummary:
    id: int
    name: str
    version: int
    publisher_name: str
    has_active_verifiers: bool


@dataclass(frozen=True)
class VerifierView:
    id: int
    name: str
    version: int
    statement_trigger: str
    last_verified_label: str


@dataclass(frozen=True)
class VerifierSummary:
    id: int
    name: str
    version: int
    active: bool
    verification_trigger: str
    verification_token: str
    headers_text: str


@dataclass(frozen=True)
class VerifierDetail:
    id: int
    name: str
    version: int
    active: bool
    verification_trigger: str
    verification_token: str
    headers_text: str
    contract_id: int
    contract_name: str
    contract_version: int
    statement_trigger: str
    last_verified_label: str


@dataclass(frozen=True)
class StatementView:
    trigger: str
    expected_state: str
    payload: str
    verifiers: list[VerifierView]


@dataclass(frozen=True)
class VersionView:
    id: int
    version: int
    has_active_verifiers: bool
    current: bool


@dataclass(frozen=True)
class ContractDetail:
    id: int
    name: str
    version: int
    publisher_name: str
    versions: list[VersionView]
    active_verifiers: list[VerifierView]
    statements: list[StatementView]


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DomainError(409, "That record conflicts with an existing one") from exc


def _clean_name(value: str, label: str = "Name", max_length: int = 200) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise DomainError(400, f"{label} is required")
    if len(cleaned) > max_length:
        raise DomainError(400, f"{label} must be at most {max_length} characters")
    return cleaned


def _checked(func, *args):
    try:
        return func(*args)
    except ValueError as exc:
        raise DomainError(400, str(exc)) from exc


def _headers_json_from_text(value: str) -> str:
    return dump_headers(_checked(parse_header_block, value))


def _headers_json_from_pairs(headers: list) -> str:
    return dump_headers([(item.name, item.value) for item in headers])


def _headers_text(verifier: Verifier) -> str:
    return format_headers(load_headers(verifier.verification_headers_json))


def _clean_email(value: str) -> str:
    cleaned = value.strip()
    if len(cleaned) > 200 or not _EMAIL.fullmatch(cleaned):
        raise DomainError(400, "Email must be a valid email address")
    return cleaned


def _clean_statement(trigger: str, expected_state: str, payload: str) -> tuple[str, str, str]:
    trigger = trigger.strip()
    expected_state = expected_state.strip()
    if not trigger:
        raise DomainError(400, "Trigger endpoint is required")
    if len(trigger) > 500:
        raise DomainError(400, "Trigger endpoint must be at most 500 characters")
    if not expected_state:
        raise DomainError(400, "Expected state is required")
    if len(expected_state) > 2000:
        raise DomainError(400, "Expected state must be at most 2000 characters")
    if payload is None:
        payload = ""
    if len(payload) > 20000:
        raise DomainError(400, "Payload must be at most 20000 characters")
    return trigger, expected_state, payload


def authenticate(db: Session, username: str, password: str) -> User | None:
    username = username.strip()
    if not username:
        return None
    user = db.scalar(select(User).where(User.username == username))
    if user is None or not user.password:
        return None
    if not secrets.compare_digest(user.password, password):
        return None
    return user


def issue_access_token(db: Session, company: Company) -> str:
    company.access_token = secrets.token_urlsafe(32)
    _commit(db)
    db.refresh(company)
    return company.access_token


def update_company(db: Session, company: Company, name: str) -> Company:
    company.name = _clean_name(name, "Organization name")
    _commit(db)
    db.refresh(company)
    return company


def create_company(db: Session, name: str) -> Company:
    if db.scalar(select(Company.id).limit(1)) is not None:
        raise DomainError(409, "An organization already exists")
    company = Company(name=_clean_name(name, "Organization name"))
    db.add(company)
    _commit(db)
    db.refresh(company)
    return company


def delete_company(db: Session, company: Company) -> None:
    db.delete(company)
    _commit(db)


def list_users(db: Session, company_id: int) -> list[User]:
    return list(db.scalars(select(User).where(User.company_id == company_id).order_by(User.id)).all())


def get_user(db: Session, company_id: int, user_id: int) -> User:
    user = db.scalar(select(User).where(User.id == user_id, User.company_id == company_id))
    if user is None:
        raise DomainError(404, "User not found")
    return user


def create_user(db: Session, company_id: int, name: str, email: str) -> User:
    user = User(company_id=company_id, name=_clean_name(name, "Name"), email=_clean_email(email))
    db.add(user)
    _commit(db)
    db.refresh(user)
    return user


def update_user(db: Session, user: User, name: str, email: str) -> User:
    user.name = _clean_name(name, "Name")
    user.email = _clean_email(email)
    _commit(db)
    db.refresh(user)
    return user


def delete_user(db: Session, user: User) -> None:
    db.delete(user)
    _commit(db)


def list_contracts(db: Session, company_id: int) -> list[Contract]:
    return list(
        db.scalars(
            select(Contract)
            .where(Contract.company_id == company_id)
            .options(joinedload(Contract.publisher))
            .order_by(Contract.name, Contract.version)
        )
        .unique()
        .all()
    )


def get_contract(db: Session, company_id: int, contract_id: int) -> Contract:
    contract = db.scalar(select(Contract).where(Contract.id == contract_id, Contract.company_id == company_id))
    if contract is None:
        raise DomainError(404, "Contract not found")
    return contract


def create_contract(db: Session, company_id: int, name: str, publisher_name: str, statements: list) -> Contract:
    name = _clean_name(name, "Name")
    publisher_name = _clean_name(publisher_name, "Publisher name")
    if db.scalar(select(Contract.id).where(Contract.name == name).limit(1)) is not None:
        raise DomainError(409, "A contract with this name already exists")
    contract = Contract(company_id=company_id, name=name, version=1)
    db.add(contract)
    db.flush()
    db.add(Publisher(contract=contract, name=publisher_name))
    for item in statements:
        trigger, expected_state, payload = _clean_statement(item.trigger, item.expected_state, item.payload)
        db.add(
            Statement(
                contract=contract,
                trigger=trigger,
                expected_state=expected_state,
                payload=payload,
            )
        )
    _commit(db)
    db.refresh(contract)
    return contract


def update_contract_fields(db: Session, contract: Contract, name: str, publisher_name: str) -> Contract:
    name = _clean_name(name, "Name")
    publisher_name = _clean_name(publisher_name, "Publisher name")
    if name != contract.name:
        if db.scalar(select(Contract.id).where(Contract.name == name).limit(1)) is not None:
            raise DomainError(409, "A contract with this name already exists")
        members = db.scalars(
            select(Contract).where(Contract.company_id == contract.company_id, Contract.name == contract.name)
        ).all()
        for member in members:
            member.name = name
    publisher = contract.publisher
    if publisher is None:
        db.add(Publisher(contract=contract, name=publisher_name))
    else:
        publisher.name = publisher_name
    _commit(db)
    db.refresh(contract)
    return contract


def update_contract_name(db: Session, contract: Contract, name: str) -> Contract:
    name = _clean_name(name, "Name")
    if name == contract.name:
        return contract
    if db.scalar(select(Contract.id).where(Contract.name == name).limit(1)) is not None:
        raise DomainError(409, "A contract with this name already exists")
    members = db.scalars(
        select(Contract).where(Contract.company_id == contract.company_id, Contract.name == contract.name)
    ).all()
    for member in members:
        member.name = name
    _commit(db)
    db.refresh(contract)
    return contract


def delete_contract_version(db: Session, contract: Contract) -> None:
    db.delete(contract)
    _commit(db)


def delete_contract_family(db: Session, contract: Contract) -> None:
    members = list(
        db.scalars(
            select(Contract).where(Contract.company_id == contract.company_id, Contract.name == contract.name)
        ).all()
    )
    for member in members:
        db.delete(member)
    _commit(db)


def list_statements(db: Session, company_id: int) -> list[Statement]:
    return list(
        db.scalars(
            select(Statement)
            .join(Contract)
            .where(Contract.company_id == company_id)
            .options(joinedload(Statement.contract))
            .order_by(Statement.id)
        )
        .unique()
        .all()
    )


def get_statement(db: Session, company_id: int, statement_id: int) -> Statement:
    statement = db.scalar(
        select(Statement)
        .join(Contract)
        .where(Statement.id == statement_id, Contract.company_id == company_id)
        .options(joinedload(Statement.contract))
    )
    if statement is None:
        raise DomainError(404, "Statement not found")
    return statement


def create_statement(
    db: Session,
    company_id: int,
    contract_id: int,
    trigger: str,
    expected_state: str,
    payload: str,
) -> Statement:
    source = get_contract(db, company_id, contract_id)
    trigger, expected_state, payload = _clean_statement(trigger, expected_state, payload)
    forked = _fork(db, source)
    created = Statement(contract=forked, trigger=trigger, expected_state=expected_state, payload=payload)
    db.add(created)
    _commit(db)
    db.refresh(created)
    return created


def update_statement(
    db: Session,
    statement: Statement,
    trigger: str,
    expected_state: str,
    payload: str,
) -> Statement:
    trigger, expected_state, payload = _clean_statement(trigger, expected_state, payload)
    statement.trigger = trigger
    statement.expected_state = expected_state
    statement.payload = payload
    _commit(db)
    db.refresh(statement)
    return statement


def remove_statement(db: Session, statement: Statement) -> Contract:
    forked = _fork(db, statement.contract, exclude_statement_id=statement.id)
    _commit(db)
    db.refresh(forked)
    return forked


def list_verifiers(db: Session, company_id: int) -> list[Verifier]:
    return list(
        db.scalars(
            select(Verifier)
            .join(Statement)
            .join(Contract)
            .where(Contract.company_id == company_id)
            .order_by(Verifier.id)
        ).all()
    )


def get_verifier(db: Session, company_id: int, verifier_id: int) -> Verifier:
    verifier = db.scalar(
        select(Verifier)
        .join(Statement)
        .join(Contract)
        .where(Verifier.id == verifier_id, Contract.company_id == company_id)
    )
    if verifier is None:
        raise DomainError(404, "Verifier not found")
    return verifier


def verifier_catalog(db: Session, company_id: int) -> list[VerifierSummary]:
    verifiers = list(
        db.scalars(
            select(Verifier)
            .join(Statement)
            .join(Contract)
            .where(Contract.company_id == company_id)
            .order_by(Verifier.name, Verifier.version, Verifier.id)
        ).all()
    )
    return [
        VerifierSummary(
            id=verifier.id,
            name=verifier.name,
            version=verifier.version,
            active=verifier.active,
            verification_trigger=verifier.verification_trigger,
            verification_token=verifier.verification_token,
            headers_text=_headers_text(verifier),
        )
        for verifier in verifiers
    ]


def verifier_page(db: Session, company_id: int, verifier_id: int) -> VerifierDetail:
    verifier = get_verifier(db, company_id, verifier_id)
    statement = verifier.statement
    contract = statement.contract
    return VerifierDetail(
        id=verifier.id,
        name=verifier.name,
        version=verifier.version,
        active=verifier.active,
        verification_trigger=verifier.verification_trigger,
        verification_token=verifier.verification_token,
        headers_text=_headers_text(verifier),
        contract_id=contract.id,
        contract_name=contract.name,
        contract_version=contract.version,
        statement_trigger=statement.trigger,
        last_verified_label=format_timestamp(verifier.last_verified_at),
    )


def update_verifier_attributes(
    db: Session,
    verifier: Verifier,
    name: str,
    version: str,
    active: bool,
    verification_trigger: str,
    verification_token: str,
    verification_headers: str,
) -> Verifier:
    try:
        parsed_version = int(version)
    except (TypeError, ValueError):
        raise DomainError(400, "Version must be a whole number") from None
    verifier.name = _clean_name(name, "Verifier name")
    verifier.version = parsed_version
    verifier.active = active
    verifier.verification_trigger = _checked(clean_http_url, verification_trigger)
    verifier.verification_token = _checked(clean_token, verification_token)
    verifier.verification_headers_json = _headers_json_from_text(verification_headers)
    _commit(db)
    db.refresh(verifier)
    return verifier


def create_verifier(
    db: Session,
    company_id: int,
    statement_id: int,
    name: str,
    version: int,
    active: bool,
    verification_trigger: str,
    verification_token: str,
    verification_headers: list,
    last_verified_at,
) -> Verifier:
    statement = get_statement(db, company_id, statement_id)
    verifier = Verifier(
        statement=statement,
        name=_clean_name(name, "Verifier name"),
        version=version,
        active=active,
        verification_trigger=_checked(clean_http_url, verification_trigger),
        verification_token=_checked(clean_token, verification_token),
        verification_headers_json=_headers_json_from_pairs(verification_headers),
        last_verified_at=last_verified_at,
    )
    db.add(verifier)
    _commit(db)
    db.refresh(verifier)
    return verifier


def update_verifier(
    db: Session,
    company_id: int,
    verifier: Verifier,
    statement_id: int,
    name: str,
    version: int,
    active: bool,
    verification_trigger: str,
    verification_token: str,
    verification_headers: list,
    last_verified_at,
) -> Verifier:
    statement = get_statement(db, company_id, statement_id)
    verifier.statement = statement
    verifier.name = _clean_name(name, "Verifier name")
    verifier.version = version
    verifier.active = active
    verifier.verification_trigger = _checked(clean_http_url, verification_trigger)
    verifier.verification_token = _checked(clean_token, verification_token)
    verifier.verification_headers_json = _headers_json_from_pairs(verification_headers)
    verifier.last_verified_at = last_verified_at
    _commit(db)
    db.refresh(verifier)
    return verifier


def delete_verifier(db: Session, verifier: Verifier) -> None:
    db.delete(verifier)
    _commit(db)


def list_tests(db: Session, company_id: int) -> list[VerifierTest]:
    return list(
        db.scalars(
            select(VerifierTest)
            .join(Verifier)
            .join(Statement)
            .join(Contract)
            .where(Contract.company_id == company_id)
            .order_by(VerifierTest.id)
        ).all()
    )


def get_test(db: Session, company_id: int, test_id: int) -> VerifierTest:
    test = db.scalar(
        select(VerifierTest)
        .join(Verifier)
        .join(Statement)
        .join(Contract)
        .where(VerifierTest.id == test_id, Contract.company_id == company_id)
    )
    if test is None:
        raise DomainError(404, "Test not found")
    return test


def create_test(db: Session, company_id: int, verifier_id: int, name: str) -> VerifierTest:
    verifier = get_verifier(db, company_id, verifier_id)
    test = VerifierTest(verifier=verifier, name=_clean_name(name, "Test name"))
    db.add(test)
    _commit(db)
    db.refresh(test)
    return test


def update_test(db: Session, company_id: int, test: VerifierTest, verifier_id: int, name: str) -> VerifierTest:
    verifier = get_verifier(db, company_id, verifier_id)
    test.verifier = verifier
    test.name = _clean_name(name, "Test name")
    _commit(db)
    db.refresh(test)
    return test


def delete_test(db: Session, test: VerifierTest) -> None:
    db.delete(test)
    _commit(db)


def list_publishers(db: Session, company_id: int) -> list[Publisher]:
    return list(
        db.scalars(
            select(Publisher).join(Contract).where(Contract.company_id == company_id).order_by(Publisher.id)
        ).all()
    )


def get_publisher(db: Session, company_id: int, publisher_id: int) -> Publisher:
    publisher = db.scalar(
        select(Publisher)
        .join(Contract)
        .where(Publisher.id == publisher_id, Contract.company_id == company_id)
    )
    if publisher is None:
        raise DomainError(404, "Publisher not found")
    return publisher


def create_publisher(db: Session, company_id: int, contract_id: int, name: str) -> Publisher:
    contract = get_contract(db, company_id, contract_id)
    if contract.publisher is not None:
        raise DomainError(409, "This contract already has a publisher")
    publisher = Publisher(contract=contract, name=_clean_name(name, "Publisher name"))
    db.add(publisher)
    _commit(db)
    db.refresh(publisher)
    return publisher


def update_publisher(db: Session, company_id: int, publisher: Publisher, contract_id: int, name: str) -> Publisher:
    if contract_id != publisher.contract_id:
        raise DomainError(409, "A publisher cannot be moved to another contract")
    get_contract(db, company_id, contract_id)
    publisher.name = _clean_name(name, "Publisher name")
    _commit(db)
    db.refresh(publisher)
    return publisher


def update_publisher_name(db: Session, contract: Contract, name: str) -> Publisher:
    name = _clean_name(name, "Publisher name")
    publisher = contract.publisher
    if publisher is None:
        publisher = Publisher(contract=contract, name=name)
        db.add(publisher)
    else:
        publisher.name = name
    _commit(db)
    db.refresh(publisher)
    return publisher


def delete_publisher(publisher: Publisher) -> None:
    raise DomainError(409, "A contract must keep its publisher")


def has_active_verifiers(db: Session, contract_id: int) -> bool:
    found = db.scalar(
        select(Verifier.id)
        .join(Statement)
        .where(Statement.contract_id == contract_id, Verifier.active.is_(True))
        .limit(1)
    )
    return found is not None


def contract_overview(db: Session, company_id: int) -> list[ContractSummary]:
    contracts = list(
        db.scalars(
            select(Contract)
            .where(Contract.company_id == company_id)
            .options(joinedload(Contract.publisher))
            .order_by(Contract.name, Contract.version)
        )
        .unique()
        .all()
    )
    latest: dict[str, Contract] = {}
    for contract in contracts:
        latest[contract.name] = contract
    rows = [
        ContractSummary(
            id=contract.id,
            name=contract.name,
            version=contract.version,
            publisher_name=contract.publisher_name,
            has_active_verifiers=has_active_verifiers(db, contract.id),
        )
        for contract in latest.values()
    ]
    rows.sort(key=lambda row: row.name.casefold())
    return rows


def contract_detail(db: Session, company_id: int, contract_id: int) -> ContractDetail:
    contract = get_contract(db, company_id, contract_id)
    family = list(
        db.scalars(
            select(Contract)
            .where(Contract.company_id == company_id, Contract.name == contract.name)
            .order_by(Contract.version)
        ).all()
    )
    active_rows = list(
        db.scalars(
            select(Verifier)
            .join(Statement)
            .where(Statement.contract_id == contract.id, Verifier.active.is_(True))
            .options(joinedload(Verifier.statement))
            .order_by(Verifier.name, Verifier.id)
        )
        .unique()
        .all()
    )
    statements = list(
        db.scalars(
            select(Statement)
            .where(Statement.contract_id == contract.id)
            .options(selectinload(Statement.verifiers))
            .order_by(Statement.id)
        ).all()
    )
    return ContractDetail(
        id=contract.id,
        name=contract.name,
        version=contract.version,
        publisher_name=contract.publisher_name,
        versions=[
            VersionView(
                id=item.id,
                version=item.version,
                has_active_verifiers=has_active_verifiers(db, item.id),
                current=item.id == contract.id,
            )
            for item in family
        ],
        active_verifiers=[_verifier_view(item) for item in active_rows],
        statements=[
            StatementView(
                trigger=statement.trigger,
                expected_state=statement.expected_state,
                payload=statement.payload,
                verifiers=[
                    _verifier_view(verifier, statement.trigger)
                    for verifier in sorted(statement.verifiers, key=lambda item: (item.name.casefold(), item.id))
                ],
            )
            for statement in statements
        ],
    )


def _verifier_view(verifier: Verifier, trigger: str | None = None) -> VerifierView:
    statement_trigger = trigger if trigger is not None else verifier.statement.trigger
    return VerifierView(
        id=verifier.id,
        name=verifier.name,
        version=verifier.version,
        statement_trigger=statement_trigger,
        last_verified_label=format_timestamp(verifier.last_verified_at),
    )


def _latest_version(db: Session, contract: Contract) -> int:
    latest = db.scalar(
        select(func.max(Contract.version)).where(
            Contract.company_id == contract.company_id,
            Contract.name == contract.name,
        )
    )
    if latest is None:
        raise DomainError(404, "Contract not found")
    return latest


def _fork(db: Session, source: Contract, exclude_statement_id: int | None = None) -> Contract:
    latest = _latest_version(db, source)
    if source.version != latest:
        raise DomainError(409, "Statements can only be added or removed on the latest version of a contract")
    forked = Contract(company_id=source.company_id, name=source.name, version=latest + 1)
    db.add(forked)
    db.flush()
    publisher_name = source.publisher.name if source.publisher is not None else ""
    db.add(Publisher(contract=forked, name=publisher_name))
    statements = db.scalars(
        select(Statement)
        .where(Statement.contract_id == source.id)
        .options(selectinload(Statement.verifiers).selectinload(Verifier.tests))
        .order_by(Statement.id)
    ).all()
    for statement in statements:
        if statement.id == exclude_statement_id:
            continue
        _copy_statement(db, statement, forked)
    return forked


def _copy_statement(db: Session, source: Statement, target: Contract) -> None:
    copy = Statement(
        contract=target,
        trigger=source.trigger,
        expected_state=source.expected_state,
        payload=source.payload,
    )
    db.add(copy)
    for verifier in source.verifiers:
        verifier_copy = Verifier(
            statement=copy,
            name=verifier.name,
            version=verifier.version,
            active=verifier.active,
            verification_trigger=verifier.verification_trigger,
            verification_token=verifier.verification_token,
            verification_headers_json=verifier.verification_headers_json,
            last_verified_at=verifier.last_verified_at,
        )
        db.add(verifier_copy)
        for test in verifier.tests:
            db.add(VerifierTest(verifier=verifier_copy, name=test.name))
