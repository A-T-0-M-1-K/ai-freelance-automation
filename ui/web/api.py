# ui/web/api.py
"""
REST API for the Web UI of AI Freelance Automation System.
Provides endpoints for dashboard, jobs, clients, finances, monitoring, and settings.
Fully integrated with core services, security, and dependency injection.
"""

import logging
from typing import Any, Dict
from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Core imports (relative to project root)
from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.dependency.service_locator import ServiceLocator
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from services.service_registry import ServiceRegistry

# Services
from services.ai_services.transcription_service import TranscriptionService
from services.ai_services.translation_service import TranslationService
from services.ai_services.copywriting_service import CopywritingService

# Platform & Business
from platforms.platform_factory import PlatformFactory
from services.storage.database_service import DatabaseService

# Logging setup
logger = logging.getLogger("WebAPI")
security = HTTPBearer()

# Initialize FastAPI app
app = FastAPI(
    title="AI Freelance Automation API",
    description="REST API for autonomous freelance operations management",
    version="1.0.0",
    docs_url="/docs",  # Swagger UI
    redoc_url="/redoc",  # ReDoc
)


# CORS middleware (configurable via config)
def setup_cors(app: FastAPI, config: UnifiedConfigManager):
    cors_config = config.get("ui.web.cors", {})
    origins = cors_config.get("origins", ["http://localhost:3000"])
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=cors_config.get("allow_credentials", True),
        allow_methods=cors_config.get("methods", ["*"]),
        allow_headers=cors_config.get("headers", ["*"]),
    )


# Dependency: get current user (placeholder – real auth via JWT/OAuth2 later)
async def get_current_user(token: str = Depends(security)) -> str:
    # In production: validate JWT, check scopes, etc.
    # For now: assume valid if token exists
    if not token or not token.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return "authenticated_user"


# Health check endpoint
@app.get("/health", tags=["System"])
async def health_check():
    """Return system health status."""
    try:
        monitor: IntelligentMonitoringSystem = ServiceLocator.get("monitoring")
        health = await monitor.get_system_health()
        return {"status": "healthy", "details": health}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unhealthy", "error": str(e)}
        )


# Jobs endpoints
class JobRequest(BaseModel):
    platform: str
    job_id: str


@app.post("/jobs/accept", tags=["Jobs"])
async def accept_job(request: JobRequest, user: str = Depends(get_current_user)):
    """Accept a job on a specified platform."""
    try:
        platform_client = PlatformFactory.get_platform(request.platform)
        result = await platform_client.accept_job(request.job_id)
        logger.info(f"Job {request.job_id} accepted on {request.platform}")
        return {"success": True, "result": result}
    except Exception as e:
        logger.error(f"Failed to accept job {request.job_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/jobs/active", tags=["Jobs"])
async def get_active_jobs(user: str = Depends(get_current_user)):
    """Get list of active jobs."""
    db: DatabaseService = ServiceLocator.get("database")
    jobs = await db.query("SELECT * FROM jobs WHERE status = 'active'")
    return {"jobs": jobs}


# AI Services
@app.post("/ai/transcribe", tags=["AI Services"])
async def transcribe_audio(url: str, user: str = Depends(get_current_user)):
    service: TranscriptionService = ServiceLocator.get("transcription")
    try:
        result = await service.transcribe(url)
        return {"transcript": result}
    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        raise HTTPException(status_code=500, detail="Transcription error")


@app.post("/ai/translate", tags=["AI Services"])
async def translate_text(text: str, src_lang: str, tgt_lang: str, user: str = Depends(get_current_user)):
    service: TranslationService = ServiceLocator.get("translation")
    try:
        result = await service.translate(text, src_lang, tgt_lang)
        return {"translation": result}
    except Exception as e:
        logger.error(f"Translation failed: {e}")
        raise HTTPException(status_code=500, detail="Translation error")


@app.post("/ai/copywrite", tags=["AI Services"])
async def generate_copy(prompt: str, style: str = "professional", user: str = Depends(get_current_user)):
    service: CopywritingService = ServiceLocator.get("copywriting")
    try:
        result = await service.generate(prompt, style=style)
        return {"content": result}
    except Exception as e:
        logger.error(f"Copywriting failed: {e}")
        raise HTTPException(status_code=500, detail="Copywriting error")


# Finances
@app.get("/finances/summary", tags=["Finances"])
async def get_financial_summary(user: str = Depends(get_current_user)):
    db: DatabaseService = ServiceLocator.get("database")
    summary = await db.query_one("""
        SELECT 
            SUM(amount) FILTER (WHERE type = 'income') AS income,
            SUM(amount) FILTER (WHERE type = 'expense') AS expenses
        FROM transactions
    """)
    return summary or {"income": 0, "expenses": 0}


# Settings
@app.get("/settings", tags=["Settings"])
async def get_settings(user: str = Depends(get_current_user)):
    config = UnifiedConfigManager()
    return config.get_all()


@app.post("/settings", tags=["Settings"])
async def update_settings(updates: Dict[str, Any], user: str = Depends(get_current_user)):
    config = UnifiedConfigManager()
    try:
        config.update(updates)
        return {"status": "updated"}
    except Exception as e:
        logger.error(f"Failed to update settings: {e}")
        raise HTTPException(status_code=400, detail="Invalid configuration")


# Startup event
@app.on_event("startup")
async def startup_event():
    """Initialize services on startup."""
    logger.info("🚀 Starting Web API...")

    # Load config
    config = UnifiedConfigManager()

    # Setup CORS
    setup_cors(app, config)

    # Register services in locator (if not done elsewhere)
    ServiceLocator.register("database", DatabaseService(config))
    ServiceLocator.register("monitoring", IntelligentMonitoringSystem(config))
    ServiceLocator.register("transcription", TranscriptionService(config))
    ServiceLocator.register("translation", TranslationService(config))
    ServiceLocator.register("copywriting", CopywritingService(config))

    logger.info("✅ Web API ready.")


# Shutdown event
@app.on_event("shutdown")
async def shutdown_event():
    logger.info("🛑 Shutting down Web API...")


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled exception in {request.url}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )