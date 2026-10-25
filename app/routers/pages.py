from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import RedirectResponse

from app import services
from app.deps import CurrentUser, Db, current_user
from app.errors import DomainError
from app.models import User
from app.templating import templates

router = APIRouter()


def safe_next(value: str | None) -> str:
    if not value or not value.startswith("/") or value.startswith("//") or value.startswith("/\\"):
        return "/contracts"
    if "://" in value:
        return "/contracts"
    return value


def render(request: Request, template: str, user: User | None, *, status_code: int = 200, **context):
    organization_name = user.company.name if user is not None else None
    user_name = user.name if user is not None else None
    return templates.TemplateResponse(
        request,
        template,
        {
            "flash": request.session.pop("flash", None),
            "organization_name": organization_name,
            "user_name": user_name,
            **context,
        },
        status_code=status_code,
    )


@router.get("/")
def home() -> RedirectResponse:
    return RedirectResponse("/contracts", status_code=303)


@router.get("/login")
def login_form(
    request: Request,
    db: Db,
    next_path: str = Query(default="/contracts", alias="next"),
):
    destination = safe_next(next_path)
    if current_user(request, db) is not None:
        return RedirectResponse(destination, status_code=303)
    return render(request, "login.html", None, next_url=destination, error=None)


@router.post("/login")
def login(
    request: Request,
    db: Db,
    username: str = Form(),
    password: str = Form(),
    next_path: str = Form(default="/contracts", alias="next"),
):
    destination = safe_next(next_path)
    user = services.authenticate(db, username, password)
    if user is None:
        return render(
            request,
            "login.html",
            None,
            status_code=401,
            next_url=destination,
            error="Incorrect username or password.",
        )
    request.session["user_id"] = user.id
    return RedirectResponse(destination, status_code=303)


@router.post("/logout")
def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@router.get("/organization")
def organization(request: Request, user: CurrentUser):
    response = render(
        request,
        "organization.html",
        user,
        section="organization",
        token=user.company.access_token,
        name_value=user.company.name,
        error=None,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/organization")
def update_organization(
    request: Request,
    db: Db,
    user: CurrentUser,
    name: str = Form(),
):
    try:
        services.update_company(db, user.company, name)
    except DomainError as exc:
        db.rollback()
        response = render(
            request,
            "organization.html",
            user,
            status_code=exc.status_code,
            section="organization",
            token=user.company.access_token,
            name_value=name,
            error=exc.detail,
        )
        response.headers["Cache-Control"] = "no-store"
        return response
    request.session["flash"] = "Organization name saved."
    return RedirectResponse("/organization", status_code=303)


@router.post("/organization/token")
def request_token(request: Request, db: Db, user: CurrentUser) -> RedirectResponse:
    services.issue_access_token(db, user.company)
    request.session["flash"] = "New access token issued."
    return RedirectResponse("/organization", status_code=303)


@router.get("/contracts")
def contracts(request: Request, db: Db, user: CurrentUser):
    rows = services.contract_overview(db, user.company_id)
    return render(request, "contracts.html", user, section="contracts", contracts=rows)


@router.get("/contracts/{contract_id}")
def contract_detail(contract_id: int, request: Request, db: Db, user: CurrentUser):
    try:
        detail = services.contract_detail(db, user.company_id, contract_id)
    except DomainError as exc:
        if exc.status_code != 404:
            raise
        return render(request, "not_found.html", user, status_code=404, section="contracts")
    return render(request, "contract_detail.html", user, section="contracts", contract=detail)


@router.get("/contracts/{contract_id}/remove")
def confirm_remove(contract_id: int, request: Request, db: Db, user: CurrentUser):
    try:
        contract = services.get_contract(db, user.company_id, contract_id)
    except DomainError as exc:
        if exc.status_code != 404:
            raise
        return render(request, "not_found.html", user, status_code=404, section="contracts")
    return render(
        request,
        "contract_remove.html",
        user,
        section="contracts",
        contract_id=contract.id,
        contract_name=contract.name,
    )


@router.post("/contracts/{contract_id}/remove")
def remove_contract(contract_id: int, request: Request, db: Db, user: CurrentUser):
    try:
        contract = services.get_contract(db, user.company_id, contract_id)
        services.delete_contract_family(db, contract)
    except DomainError as exc:
        if exc.status_code != 404:
            raise
        return render(request, "not_found.html", user, status_code=404, section="contracts")
    request.session["flash"] = "Contract removed."
    return RedirectResponse("/contracts", status_code=303)
