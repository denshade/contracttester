from fastapi import APIRouter, Depends, Response

from app import services
from app.deps import CurrentCompany, Db, require_company
from app.errors import DomainError
from app.schemas import (
    CompanyCreate,
    CompanyOut,
    CompanyUpdate,
    ContractCreate,
    ContractOut,
    ContractUpdate,
    PublisherOut,
    PublisherWrite,
    StatementCreate,
    StatementOut,
    StatementRemoval,
    StatementWrite,
    TestOut,
    TestWrite,
    UserOut,
    UserWrite,
    VerifierOut,
    VerifierWrite,
)

router = APIRouter(prefix="/api", dependencies=[Depends(require_company)])


@router.get("/companies", response_model=list[CompanyOut], tags=["companies"])
def list_companies(company: CurrentCompany) -> list:
    return [company]


@router.post("/companies", response_model=CompanyOut, status_code=201, tags=["companies"])
def create_company(body: CompanyCreate, db: Db, company: CurrentCompany) -> object:
    """This product has one organization, so creating another is rejected."""
    return services.create_company(db, body.name)


@router.get("/companies/{company_id}", response_model=CompanyOut, tags=["companies"])
def get_company(company_id: int, company: CurrentCompany) -> object:
    if company.id != company_id:
        raise DomainError(404, "Organization not found")
    return company


@router.put("/companies/{company_id}", response_model=CompanyOut, tags=["companies"])
def update_company(company_id: int, body: CompanyUpdate, db: Db, company: CurrentCompany) -> object:
    if company.id != company_id:
        raise DomainError(404, "Organization not found")
    return services.update_company(db, company, body.name)


@router.delete("/companies/{company_id}", status_code=204, tags=["companies"])
def delete_company(company_id: int, db: Db, company: CurrentCompany) -> Response:
    if company.id != company_id:
        raise DomainError(404, "Organization not found")
    services.delete_company(db, company)
    return Response(status_code=204)


@router.get("/users", response_model=list[UserOut], tags=["users"])
def list_users(db: Db, company: CurrentCompany) -> list:
    return services.list_users(db, company.id)


@router.post("/users", response_model=UserOut, status_code=201, tags=["users"])
def create_user(body: UserWrite, db: Db, company: CurrentCompany) -> object:
    return services.create_user(db, company.id, body.name, body.email)


@router.get("/users/{user_id}", response_model=UserOut, tags=["users"])
def get_user(user_id: int, db: Db, company: CurrentCompany) -> object:
    return services.get_user(db, company.id, user_id)


@router.put("/users/{user_id}", response_model=UserOut, tags=["users"])
def update_user(user_id: int, body: UserWrite, db: Db, company: CurrentCompany) -> object:
    user = services.get_user(db, company.id, user_id)
    return services.update_user(db, user, body.name, body.email)


@router.delete("/users/{user_id}", status_code=204, tags=["users"])
def delete_user(user_id: int, db: Db, company: CurrentCompany) -> Response:
    user = services.get_user(db, company.id, user_id)
    services.delete_user(db, user)
    return Response(status_code=204)


@router.get("/contracts", response_model=list[ContractOut], tags=["contracts"])
def list_contracts(db: Db, company: CurrentCompany) -> list:
    return services.list_contracts(db, company.id)


@router.post("/contracts", response_model=ContractOut, status_code=201, tags=["contracts"])
def create_contract(body: ContractCreate, db: Db, company: CurrentCompany) -> object:
    """Creates version 1. Later statement adds and removals create the next versions."""
    return services.create_contract(db, company.id, body.name, body.publisher_name, body.statements)


@router.get("/contracts/{contract_id}", response_model=ContractOut, tags=["contracts"])
def get_contract(contract_id: int, db: Db, company: CurrentCompany) -> object:
    return services.get_contract(db, company.id, contract_id)


@router.put("/contracts/{contract_id}", response_model=ContractOut, tags=["contracts"])
def update_contract(contract_id: int, body: ContractUpdate, db: Db, company: CurrentCompany) -> object:
    """Renames every version of the contract. The version number stays the same."""
    contract = services.get_contract(db, company.id, contract_id)
    return services.update_contract_name(db, contract, body.name)


@router.delete("/contracts/{contract_id}", status_code=204, tags=["contracts"])
def delete_contract(contract_id: int, db: Db, company: CurrentCompany) -> Response:
    """Deletes one version. Other versions of the same name stay."""
    contract = services.get_contract(db, company.id, contract_id)
    services.delete_contract_version(db, contract)
    return Response(status_code=204)


@router.get("/statements", response_model=list[StatementOut], tags=["statements"])
def list_statements(db: Db, company: CurrentCompany) -> list:
    return services.list_statements(db, company.id)


@router.post("/statements", response_model=StatementOut, status_code=201, tags=["statements"])
def create_statement(body: StatementCreate, db: Db, company: CurrentCompany) -> object:
    """Adds a statement by creating the next contract version. The previous version is unchanged."""
    return services.create_statement(
        db,
        company.id,
        body.contract_id,
        body.verb,
        body.trigger,
        body.state,
        body.payload,
        body.expected_outcome,
        [(header.name, header.value) for header in body.expected_headers],
    )


@router.get("/statements/{statement_id}", response_model=StatementOut, tags=["statements"])
def get_statement(statement_id: int, db: Db, company: CurrentCompany) -> object:
    return services.get_statement(db, company.id, statement_id)


@router.put("/statements/{statement_id}", response_model=StatementOut, tags=["statements"])
def update_statement(statement_id: int, body: StatementWrite, db: Db, company: CurrentCompany) -> object:
    """Updates this statement on its current version only."""
    statement = services.get_statement(db, company.id, statement_id)
    return services.update_statement(
        db,
        statement,
        body.verb,
        body.trigger,
        body.state,
        body.payload,
        body.expected_outcome,
        [(header.name, header.value) for header in body.expected_headers],
    )


@router.delete("/statements/{statement_id}", response_model=StatementRemoval, tags=["statements"])
def delete_statement(statement_id: int, db: Db, company: CurrentCompany) -> StatementRemoval:
    """Removes a statement by creating the next contract version. The previous version still has it."""
    statement = services.get_statement(db, company.id, statement_id)
    contract = services.remove_statement(db, statement)
    return StatementRemoval(statement_id=statement_id, contract=ContractOut.model_validate(contract))


@router.get("/verifiers", response_model=list[VerifierOut], tags=["verifiers"])
def list_verifiers(db: Db, company: CurrentCompany) -> list:
    return services.list_verifiers(db, company.id)


@router.post("/verifiers", response_model=VerifierOut, status_code=201, tags=["verifiers"])
def create_verifier(body: VerifierWrite, db: Db, company: CurrentCompany) -> object:
    return services.create_verifier(
        db,
        company.id,
        body.statement_id,
        body.name,
        body.version,
        body.active,
        body.verification_trigger,
        body.verification_token,
        body.verification_headers,
        body.last_verified_at,
    )


@router.get("/verifiers/{verifier_id}", response_model=VerifierOut, tags=["verifiers"])
def get_verifier(verifier_id: int, db: Db, company: CurrentCompany) -> object:
    return services.get_verifier(db, company.id, verifier_id)


@router.put("/verifiers/{verifier_id}", response_model=VerifierOut, tags=["verifiers"])
def update_verifier(verifier_id: int, body: VerifierWrite, db: Db, company: CurrentCompany) -> object:
    verifier = services.get_verifier(db, company.id, verifier_id)
    return services.update_verifier(
        db,
        company.id,
        verifier,
        body.statement_id,
        body.name,
        body.version,
        body.active,
        body.verification_trigger,
        body.verification_token,
        body.verification_headers,
        body.last_verified_at,
    )


@router.delete("/verifiers/{verifier_id}", status_code=204, tags=["verifiers"])
def delete_verifier(verifier_id: int, db: Db, company: CurrentCompany) -> Response:
    verifier = services.get_verifier(db, company.id, verifier_id)
    services.delete_verifier(db, verifier)
    return Response(status_code=204)


@router.get("/tests", response_model=list[TestOut], tags=["tests"])
def list_tests(db: Db, company: CurrentCompany) -> list:
    return services.list_tests(db, company.id)


@router.post("/tests", response_model=TestOut, status_code=201, tags=["tests"])
def create_test(body: TestWrite, db: Db, company: CurrentCompany) -> object:
    return services.create_test(db, company.id, body.verifier_id, body.name)


@router.get("/tests/{test_id}", response_model=TestOut, tags=["tests"])
def get_test(test_id: int, db: Db, company: CurrentCompany) -> object:
    return services.get_test(db, company.id, test_id)


@router.put("/tests/{test_id}", response_model=TestOut, tags=["tests"])
def update_test(test_id: int, body: TestWrite, db: Db, company: CurrentCompany) -> object:
    test = services.get_test(db, company.id, test_id)
    return services.update_test(db, company.id, test, body.verifier_id, body.name)


@router.delete("/tests/{test_id}", status_code=204, tags=["tests"])
def delete_test(test_id: int, db: Db, company: CurrentCompany) -> Response:
    test = services.get_test(db, company.id, test_id)
    services.delete_test(db, test)
    return Response(status_code=204)


@router.get("/publishers", response_model=list[PublisherOut], tags=["publishers"])
def list_publishers(db: Db, company: CurrentCompany) -> list:
    return services.list_publishers(db, company.id)


@router.post("/publishers", response_model=PublisherOut, status_code=201, tags=["publishers"])
def create_publisher(body: PublisherWrite, db: Db, company: CurrentCompany) -> object:
    return services.create_publisher(db, company.id, body.contract_id, body.name)


@router.get("/publishers/{publisher_id}", response_model=PublisherOut, tags=["publishers"])
def get_publisher(publisher_id: int, db: Db, company: CurrentCompany) -> object:
    return services.get_publisher(db, company.id, publisher_id)


@router.put("/publishers/{publisher_id}", response_model=PublisherOut, tags=["publishers"])
def update_publisher(publisher_id: int, body: PublisherWrite, db: Db, company: CurrentCompany) -> object:
    publisher = services.get_publisher(db, company.id, publisher_id)
    return services.update_publisher(db, company.id, publisher, body.contract_id, body.name)


@router.delete("/publishers/{publisher_id}", tags=["publishers"])
def delete_publisher(publisher_id: int, db: Db, company: CurrentCompany) -> Response:
    publisher = services.get_publisher(db, company.id, publisher_id)
    services.delete_publisher(publisher)
    return Response(status_code=204)
