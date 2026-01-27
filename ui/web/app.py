# AI_FREELANCE_AUTOMATION/ui/web/app.py
"""
Web Application Interface for AI Freelance Automation System.
Provides REST API, real-time WebSocket communication, and admin dashboard access.
Fully integrated with core services and secure by design.
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer

from core.config.unified_config_manager import UnifiedConfigManager
from core.dependency.service_locator import ServiceLocator
from core.security.advanced_crypto_system import AdvancedCryptoSystem
from core.monitoring.intelligent_monitoring_system import IntelligentMonitoringSystem
from services.notification.email_service import EmailService
from platforms.platform_factory import PlatformFactory

# Initialize logger
logger = logging.getLogger("WebApp")

# Load configuration early
try:
    config = UnifiedConfigManager()
    web_config = config.get_section("ui_config").get("web", {})
except Exception as e:
    logger.critical(f"❌ Failed to load web configuration: {e}")
    raise SystemExit("Configuration error — cannot start web interface.")

# Security
security = HTTPBearer()

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent  # project root
STATIC_DIR = BASE_DIR / "ui" / "web" / "static"
TEMPLATE_DIR = BASE_DIR / "ui" / "web" / "templates"

# Ensure directories exist
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(TEMPLATE_DIR, exist_ok=True)

# Initialize FastAPI app
app = FastAPI(
    title="AI Freelance Automation — Web Interface",
    description="Autonomous AI freelancer with full client interaction, job management, and payment handling.",
    version="1.0.0",
    docs_url="/docs" if web_config.get("enable_docs", True) else None,
    redoc_url="/redoc" if web_config.get("enable_redoc", True) else None,
    openapi_url="/openapi.json" if web_config.get("enable_openapi", True) else None,
)

# CORS (adjust in production!)
app.add_middleware(
    CORSMiddleware,
    allow_origins=web_config.get("allowed_origins", ["*"]),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Templates (for admin/dashboard pages)
templates = Jinja mimics standard structure
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

# === DEPENDENCIES ===

def get_config() -> UnifiedConfigManager:
    return config

def get_service_locator() -> ServiceLocator:
    return ServiceLocator.instance()

def get_crypto() -> AdvancedCryptoSystem:
    return AdvancedCryptoSystem()

def require_auth(token: str = Depends(security)) -> bool:
    """Placeholder for real auth — integrate with key_manager or OAuth later."""
    valid = AdvancedCryptoSystem.verify_api_token(token.credentials)
    if not valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return True

# === HEALTH & METRICS ===

@app.get("/health")
async def health_check(request: Request):
    """Public health endpoint for monitoring systems."""
    try:
        monitor: IntelligentMonitoringSystem = ServiceLocator.get("monitoring")
        status_data = await monitor.get_system_status()
        return JSONResponse(content={"status": "healthy", "details": status_data})
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "error": str(e)}
        )

@app.get("/metrics")
async def metrics(authenticated: bool = Depends(require_auth)):
    """Protected metrics endpoint."""
    monitor = ServiceLocator.get("monitoring")
    return await monitor.export_prometheus_metrics()

# === PLATFORM & JOB ENDPOINTS ===

@app.get("/api/v1/platforms")
async def list_platforms(authenticated: bool = Depends(require_auth)):
    factory = PlatformFactory()
    return {"platforms": factory.list_supported_platforms()}

@app.get("/api/v1/jobs/active")
async def get_active_jobs(authenticated: bool = Depends(require_auth)):
    orchestrator = ServiceLocator.get("task_orchestrator")
    return await orchestrator.get_active_jobs_summary()

@app.get("/api/v1/clients/{client_id}/conversations")
async def get_client_conversation(client_id: str, authenticated: bool = Depends(require_auth)):
    comm = ServiceLocator.get("intelligent_communicator")
    return await comm.get_conversation_history(client_id)

# === ADMIN DASHBOARD ===

@app.get("/")
async def dashboard(request: Request, authenticated: bool = Depends(require_auth)):
    return templates.TemplateResponse("dashboard.html", {"request": request})

# === STARTUP / SHUTDOWN EVENTS ===

@app.on_event("startup")
async def startup_event():
    logger.info("🚀 Starting Web Application...")
    try:
        # Initialize critical services if not already done
        ServiceLocator.initialize(config)
        logger.info("✅ Web app services initialized.")
    except Exception as e:
        logger.critical(f"💥 Web app startup failed: {e}", exc_info=True)
        raise

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("🛑 Shutting down Web Application gracefully...")

# === ERROR HANDLERS ===

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception in web layer: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error — system is recovering automatically."}
    )

if __name__ == "__main__":
    import uvicorn
    host = web_config.get("host", "127.0.0.1")
    port = web_config.get("port", 8000)
    reload = web_config.get("debug", False)
    logger.info(f"🌐 Web interface starting on http://{host}:{port}")
    uvicorn.run("ui.web.app:app", host=host, port=port, reload=reload, log_level="info")