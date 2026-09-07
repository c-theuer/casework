from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.routes.cases import router as cases_router
from app.api.v1.routes.checkout import router as checkout_router
from app.config import get_settings
from app.infrastructure.db.session import close_engine, open_engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    await open_engine()
    yield
    await close_engine()


app = FastAPI(title="Casework", lifespan=lifespan)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(checkout_router)
app.include_router(cases_router)


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}
