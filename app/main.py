"""FastAPI application. Run:  python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

Lifespan: open the store, load models (in a worker thread), attach bus subscribers (stress engine), and start
LIVE ingestion only when APP_MODE=LIVE (loading the capture script's per-source state first).
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api import routes_demo, routes_health, routes_portfolio, routes_signals, routes_watchlist
from app.config import STRESS_DISCLAIMER, Settings, get_settings
from app.runtime import Runtime
from portfolio.stress_engine import attach_stress_engine
from risk_engine.logging_setup import get_logger, setup_logging

log = get_logger(__name__)
VERSION = "0.4.0"

DESCRIPTION = f"""
AI/NLP financial risk signals from news + social text, with downstream portfolio stress testing.

* Every signal carries **provenance** (LIVE / CACHED_REAL / SYNTHETIC).
* Impact score weights are expert-set priors, not calibrated.
* Stress testing: *{STRESS_DISCLAIMER}*
* Decision-support prototype, not investment advice.
"""


def attach_modules(rt: Runtime) -> None:
    """Attach downstream bus subscribers: Module B stress engine (subscribes to signal.created)."""
    try:
        attach_stress_engine(rt)
    except Exception:  # a broken portfolio file must not take the NLP API down; /health shows portfolio=None
        log.exception("stress engine could not be attached")


def create_app(settings: Settings | None = None, runtime: Runtime | None = None, warm: bool = True) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        rt = runtime or Runtime(settings)
        app.state.runtime = rt
        attach_modules(rt)
        await rt.startup(warm=warm)
        log.info("API ready: mode=%s db=%s", rt.mode.value, settings.db_file)
        yield
        await rt.shutdown()

    app = FastAPI(title="Risk Signal Engine API", version=VERSION, description=DESCRIPTION, lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):
        errors = [{"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": "invalid request", "errors": errors})

    app.include_router(routes_health.router)
    app.include_router(routes_signals.router)
    app.include_router(routes_demo.router)
    app.include_router(routes_portfolio.router)
    app.include_router(routes_watchlist.router)
    return app


app = create_app()
