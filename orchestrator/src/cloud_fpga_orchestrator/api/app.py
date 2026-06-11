from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI

from .deps import close_pool, init_pool
from .routers import fpga_router, health_router, jobs_router, session_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize resources on startup and clean up on shutdown."""
    init_pool()
    yield
    await close_pool()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Cloud FPGA Orchestrator",
        description="REST API for submitting HDL designs and running jobs on remote FPGAs.",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.include_router(health_router)
    app.include_router(fpga_router)
    app.include_router(jobs_router)
    app.include_router(session_router)

    return app


app = create_app()
