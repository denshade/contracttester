from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.http_methods import HTTP_VERBS

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
templates.env.globals["http_verbs"] = HTTP_VERBS
