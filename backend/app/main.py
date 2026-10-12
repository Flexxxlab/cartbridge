import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from . import api, web
from .config import get_settings
from .db import Base, engine
from .stores import close_providers

logging.basicConfig(level=logging.INFO)
settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.secret_key == "dev-only-change-me" and settings.base_url.startswith("https"):
        raise RuntimeError("Set SECRET_KEY before running in production")
    Base.metadata.create_all(engine)
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

app.include_router(api.router)
app.include_router(web.router)


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True}
