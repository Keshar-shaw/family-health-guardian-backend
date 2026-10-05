from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.api.router import api_router

app = FastAPI(
    title=settings.APP_NAME,
    description="Family Health Guardian - Backend API (Phase 1)",
    version="1.0.0",
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# Set up CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
