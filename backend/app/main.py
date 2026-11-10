import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from . import api, pages, web
from .config import get_settings
from .db import engine
from .emailer import mask_tokens
from .migrate import migrate
from .stores import close_providers

logging.basicConfig(level=logging.INFO)
settings = get_settings()


class _RedactTokens(logging.Filter):
    """Keeps one-time email tokens out of uvicorn's access log (GET /verify?token=..., /reset?token=...)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(mask_tokens(a) if isinstance(a, str) else a for a in record.args)
        return True


logging.getLogger("uvicorn.access").addFilter(_RedactTokens())


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.secret_key == "dev-only-change-me" and settings.base_url.startswith("https"):
        raise RuntimeError("Set SECRET_KEY before running in production")
    migrate(engine)
    yield
    await close_providers()


app = FastAPI(title=f"{settings.app_name} API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="cb_session",
    same_site="lax",
    https_only=settings.base_url.startswith("https"),
    max_age=60 * 60 * 24 * 7,
)
# API is key-authenticated (no cookies), so any origin may call it (e.g. Flutter web).
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"],
                   allow_headers=["Authorization", "X-API-Key", "Content-Type"])

# Landing-page promo video and its player (backend/app/static).
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
app.include_router(api.router)
app.include_router(pages.router)
app.include_router(web.router)


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True}
