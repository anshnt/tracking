"""FastAPI app. Run: uv run uvicorn portal.main:app"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from portal import auth
from portal.audit import RequestIdMiddleware
from portal.config import get_settings
from portal.connectors import registry
from portal.db import get_db
from portal.routers import (
    admin,
    cases,
    devices,
    exports,
    me,
    offboarding,
    operations,
    overview,
    policies,
    work_updates,
    workspaces,
)

WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"

# default-src 'self' and nothing third-party (no CDNs, no external fonts)
CSP = "default-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
SECURITY_HEADERS = {
    "content-security-policy": CSP,
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "permissions-policy": "camera=(), microphone=(), geolocation=()",
}


class SecurityHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        api = scope["path"].startswith("/api")

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                for k, v in SECURITY_HEADERS.items():
                    headers.append((k.encode(), v.encode()))
                if api:
                    headers.append((b"cache-control", b"no-store"))
            await send(message)

        await self.app(scope, receive, send_with_headers)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # the offboarding flow reads REVOCATION_ADAPTERS in this process, so build them from env here too
    registry.register_configured()
    yield


def create_app() -> FastAPI:
    # csrf_protect guards every unsafe method on every route (see portal/auth.py)
    # the API map (every admin/cases/offboarding route) is not served to anonymous callers in production
    docs_off = {"docs_url": None, "redoc_url": None, "openapi_url": None}
    app = FastAPI(
        title="Work and Security Portal",
        dependencies=[Depends(auth.csrf_protect)],
        lifespan=lifespan,
        **(docs_off if get_settings().is_production else {}),
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestIdMiddleware)  # outermost: request id is set for everything

    @app.get("/api/health", include_in_schema=False)
    def health(db: Session = Depends(get_db)):
        try:
            db.execute(text("select 1"))
        except Exception:  # noqa: BLE001
            return JSONResponse({"status": "degraded", "db": False}, status_code=503)
        return {"status": "ok", "db": True}

    app.include_router(auth.router, prefix="/api")
    for module in (
        me,
        policies,
        workspaces,
        devices,
        work_updates,
        overview,
        exports,
        cases,
        offboarding,
        operations,
        admin,
    ):
        app.include_router(module.router, prefix="/api/v1")

    if WEB_DIST.is_dir():
        index = WEB_DIST / "index.html"

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path == "api" or path.startswith("api/"):
                raise HTTPException(404)
            candidate = (WEB_DIST / path).resolve()
            if candidate.is_file() and candidate.is_relative_to(WEB_DIST.resolve()):
                return FileResponse(candidate)
            return FileResponse(index)  # SPA fallback

    return app


app = create_app()
