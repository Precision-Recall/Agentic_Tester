"""
FastAPI application with lifespan management for Firebase initialization.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import get_settings
from src.storage.firebase_client import FirebaseClient
from src.api.routes.execution import router as execution_router

logger = logging.getLogger(__name__)

# Shared state for app-wide resources
app_state = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """App lifespan: initialize Firebase on startup, cleanup on shutdown."""
    settings = get_settings()

    # Initialize Firebase
    firebase = FirebaseClient(
        credentials_path=settings.FIREBASE_CREDENTIALS_PATH,
        project_id=settings.FIREBASE_PROJECT_ID,
    )
    app_state["firebase"] = firebase
    app_state["settings"] = settings

    if firebase.is_connected:
        logger.info("Firebase connected successfully")
    else:
        logger.warning("Firebase not connected — using local storage fallback")

    yield

    # Cleanup
    app_state.clear()
    logger.info("App shutdown complete")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Agentic Tester - Executor API",
        description="AI-driven automated E2E test execution platform",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routes
    app.include_router(execution_router, prefix="/api")

    return app


# App instance for uvicorn
app = create_app()
