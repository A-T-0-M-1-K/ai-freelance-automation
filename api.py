# AI_FREELANCE_AUTOMATION/api.py
"""
REST API server for AI Freelance Automation System.
Exposes endpoints to monitor, control, and interact with the autonomous freelancer.
Secure, versioned, and compliant with internal architecture.
"""

import os
import logging
from typing import Dict, Any

from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Internal imports (aligned with project structure)
from core.config.unified_config_manager import UnifiedConfigManager
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.dependency.service_locator import ServiceLocator
from services.service_registry import ServiceRegistry

# Initialize components
config = UnifiedConfigManager()
crypto = AdvancedCryptoSystem()
service_locator = ServiceLocator(config, crypto)
registry = ServiceRegistry(service_locator)

# Logging
logger = logging.getLogger("API")
logging.basicConfig(
    level=getattr(logging, config.get("logging.level", "INFO").upper()),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

# Security
API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)
expected_api_key = config.get("security.api_key")
if not expected_api_key:
    logger.warning("⚠️  No API key configured! Running in open mode (not recommended for production).")

# Rate limiting
limiter = Limiter(key_func=get_remote_address)
app = FastAPI(
    title="AI Freelance Automation API",
    description="Control and monitor your autonomous AI freelancer.",
    version="1.0.0",
    docs_url="/docs",  # Swagger UI
    redoc_url="/redoc",  # ReDoc
    openapi_url="/openapi.json"
)

# Middleware
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS (adjust origins in config)
origins = config.get("api.cors_origins", ["http://localhost", "http://localhost:8080"])
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth dependency
async def verify_api_key(api_key: str = Depends(api_key_header)):
    if expected_api_key and api_key != expected_api_key:
        logger.warning("Unauthorized API access attempt.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing API key"
        )
    return api_key

# Logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info(f"📥 {request.method} {request.url.path} from {request.client.host}")
    response = await call_next(request)
    logger.info(f"📤 {response.status_code} for {request.method} {request.url.path}")
    return response

# --- Endpoints ---

@app.get("/health", tags=["System"])
@limiter.limit("10/minute")
async def health_check(request: Request):
    """Return system health status."""
    try:
        health_service = service_locator.get("health_monitor")
        status_info = await health_service.get_status()
        return {"status": "healthy", "details": status_info}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {"status": "degraded", "error": str(e)}

@app.get("/jobs/active", tags=["Jobs"])
@limiter.limit("20/minute")
async def list_active_jobs(request: Request, api_key: str = Depends(verify_api_key)):
    """List all currently active jobs."""
    job_service = registry.get_service("job_service")
    return await job_service.list_active()

@app.post("/jobs/{job_id}/pause", tags=["Jobs"])
@limiter.limit("5/minute")
async def pause_job(job_id: str, request: Request, api_key: str = Depends(verify_api_key)):
    """Pause a specific job."""
    orchestrator = service_locator.get("workflow_orchestrator")
    await orchestrator.pause_job(job_id)
    return {"status": "paused", "job_id": job_id}

@app.post("/jobs/{job_id}/resume", tags=["Jobs"])
@limiter.limit("5/minute")
async def resume_job(job_id: str, request: Request, api_key: str = Depends(verify_api_key)):
    """Resume a paused job."""
    orchestrator = service_locator.get("workflow_orchestrator")
    await orchestrator.resume_job(job_id)
    return {"status": "resumed", "job_id": job_id}

@app.get("/analytics/performance", tags=["Analytics"])
@limiter.limit("10/minute")
async def get_performance_metrics(request: Request, api_key: str = Depends(verify_api_key)):
    """Get AI and business performance metrics."""
    analytics = registry.get_service("analytics_service")
    return await analytics.get_performance_report()

@app.post("/emergency/recover", tags=["System"])
@limiter.limit("2/hour")  # Rare operation
async def trigger_emergency_recovery(request: Request, api_key: str = Depends(verify_api_key)):
    """Manually trigger emergency recovery procedure."""
    recovery = service_locator.get("emergency_recovery")
    result = await recovery.execute_full_recovery()
    return {"recovery_result": result}

@app.get("/config", tags=["Configuration"])
@limiter.limit("5/minute")
async def get_current_config(request: Request, api_key: str = Depends(verify_api_key)):
    """Get current effective configuration (sensitive fields masked)."""
    safe_config = config.get_safe_snapshot()
    return safe_config

# --- Startup / Shutdown ---

@app.on_event("startup")
async def startup_event():
    logger.info("🚀 Starting AI Freelance Automation API server...")
    # Optional: connect to DB, load models, etc.
    pass

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("🛑 Shutting down API server gracefully...")
    # Optional: cleanup resources
    pass

# Entry point for direct run (e.g., uvicorn api:app)
if __name__ == "__main__":
    import uvicorn
    host = config.get("api.host", "127.0.0.1")
    port = config.get("api.port", 8000)
    workers = config.get("api.workers", 1)
    logger.info(f"📡 Starting API server on http://{host}:{port}")
    uvicorn.run("api:app", host=host, port=port, workers=workers, reload=False)