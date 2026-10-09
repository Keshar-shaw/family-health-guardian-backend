from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging

from app.config import settings
from app.api.router import api_router
from app.services.ml_service import ml_service
from app.services.hypertension_service import hypertension_ml_service

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup & shutdown lifecycle: warm up cached ML models once."""
    try:
        ml_service.load_model()
        logger.info("Diabetes ML model loaded and cached on startup.")
    except Exception as e:
        logger.warning("Diabetes ML model not pre-cached on startup: %s", e)

    try:
        hypertension_ml_service.load_model()
        logger.info("Hypertension ML model loaded and cached on startup.")
    except Exception as e:
        logger.warning("Hypertension ML model not pre-cached on startup: %s", e)

    yield


app = FastAPI(
    title=settings.APP_NAME,
    description="Family Health Guardian - Backend API (Phase 1)",
    version="1.0.0",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan
)

# Set up CORS middleware
origins = [
    "https://welltree-trail.vercel.app",
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "*",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Root health check endpoint
@app.get("/", tags=["Health"])
def root():
    return {
        "title": settings.APP_NAME,
        "status": "running",
        "health_check": "/health",
        "docs": "/docs"
    }

# Include API Router
app.include_router(api_router, prefix=settings.API_V1_STR)
app.include_router(api_router)  # Also expose /health at root level
