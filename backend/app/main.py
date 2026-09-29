import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.routes.cases import router as cases_router
from app.api.v1.routes.checkout import router as checkout_router
from app.config import get_settings
from app.infrastructure.db.session import close_engine, open_engine
from app.logging_config import configure_logging

settings = get_settings()
configure_logging(settings.log_level)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await open_engine()
    yield
    await close_engine()


app = FastAPI(title="Casework", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    start = time.monotonic()
    logger.info("request started", extra={"method": request.method, "path": request.url.path})
    try:
        response = await call_next(request)
    except Exception:
        # Currently a real gap without this: an exception escaping a route
        # handler becomes a 500 with zero server-side trace anywhere.
        logger.exception(
            "request failed with an unhandled exception",
            extra={"method": request.method, "path": request.url.path},
        )
        raise
    elapsed_ms = (time.monotonic() - start) * 1000
    logger.info(
        "request finished",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "elapsed_ms": round(elapsed_ms, 1),
        },
    )
    return response


app.include_router(checkout_router, prefix="/v1")
app.include_router(cases_router, prefix="/v1")


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}
