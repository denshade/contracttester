from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import LoginRequired
from app.models import Company, User

bearer_scheme = HTTPBearer(auto_error=False)


def get_db(request: Request):
    db = request.app.state.SessionLocal()
    try:
        yield db
    finally:
        db.close()


Db = Annotated[Session, Depends(get_db)]


def _user_from_session(request: Request, db: Session) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.get(User, user_id)


def current_user(request: Request, db: Db) -> User | None:
    return _user_from_session(request, db)


def require_user(request: Request, db: Db) -> User:
    user = _user_from_session(request, db)
    if user is None:
        path = request.url.path
        if request.url.query:
            path = f"{path}?{request.url.query}"
        raise LoginRequired(path)
    return user


def require_company(
    db: Db,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> Company:
    token = credentials.credentials.strip() if credentials and credentials.credentials else ""
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Access token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    company = db.scalar(select(Company).where(Company.access_token == token))
    if company is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid access token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return company


CurrentCompany = Annotated[Company, Depends(require_company)]
CurrentUser = Annotated[User, Depends(require_user)]
