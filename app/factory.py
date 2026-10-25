import os
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.database import make_engine, make_session_factory
from app.errors import DomainError, LoginRequired
from app.models import Base
from app.routers import api, pages
from app.seed import seed_if_empty

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(database_url: str | None = None, *, seed: bool = True) -> FastAPI:
    if database_url is None:
        data_dir = ROOT / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        database_path = (data_dir / "contracttester.db").resolve()
        database_url = f"sqlite:///{database_path.as_posix()}"

    engine = make_engine(database_url)
    session_factory = make_session_factory(engine)
    Base.metadata.create_all(engine)
    if seed:
        with session_factory() as db:
            seed_if_empty(db)

    app = FastAPI(title="Contract Tester", version="1.0.0")
    app.state.engine = engine
    app.state.SessionLocal = session_factory
    app.add_middleware(
        SessionMiddleware,
        secret_key=os.environ.get("CONTRACTTESTER_SECRET", "dev-contract-tester-secret"),
        same_site="lax",
        https_only=False,
        max_age=14 * 24 * 60 * 60,
    )
    app.add_exception_handler(DomainError, handle_domain_error)
    app.add_exception_handler(LoginRequired, handle_login_required)
    app.include_router(pages.router)
    app.include_router(api.router)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    return app


async def handle_domain_error(_request: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


async def handle_login_required(_request: Request, exc: LoginRequired) -> RedirectResponse:
    destination = quote(exc.next_path, safe="/?=&")
    return RedirectResponse(url=f"/login?next={destination}", status_code=303)
