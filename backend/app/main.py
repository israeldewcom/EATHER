from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from contextlib import asynccontextmanager
import logging
import sentry_sdk
import time
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
import json

from app.core.config import settings
from app.api.v1 import auth, transactions, documents, reports, ai, bank, tax, analytics
from app.api.websocket import websocket_manager
from app.database import engine, Base, get_db
from app.core.security import create_default_admin, get_current_user
from app.middleware import RateLimitMiddleware, RequestLoggingMiddleware

# Initialize logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Prometheus metrics
REQUEST_COUNT = Counter('http_requests_total', 'Total HTTP requests', ['method', 'endpoint', 'status'])
REQUEST_LATENCY = Histogram('http_request_duration_seconds', 'HTTP request latency', ['endpoint'])

# Initialize Sentry
if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        traces_sample_rate=1.0,
        profiles_sample_rate=1.0,
        environment=settings.ENVIRONMENT,
    )

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown events"""
    logger.info(f"Starting AETHER AI Accounting Platform - Environment: {settings.ENVIRONMENT}")
    
    # Create database tables
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created/verified")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise
    
    # Create default admin user
    try:
        create_default_admin()
        logger.info("Default admin user verified")
    except Exception as e:
        logger.warning(f"Default admin creation issue: {e}")
    
    # Initialize ML models
    from app.ai.ml_models import ModelManager
    model_manager = ModelManager()
    model_manager.load_all_models()
    
    # Start background services
    from app.workers.document_worker import start_document_workers
    from app.workers.sync_worker import start_sync_workers
    from app.services.email_service import EmailService
    
    email_service = EmailService()
    await email_service.initialize()
    
    # Start WebSocket manager
    websocket_manager.start()
    
    # Initialize external services
    from app.services.plaid_service import PlaidService
    plaid_service = PlaidService()
    await plaid_service.initialize()
    
    logger.info("All services initialized successfully")
    
    yield
    
    logger.info("Shutting down AETHER")
    websocket_manager.stop()
    await email_service.close()

# Create FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url="/api/docs" if settings.DEBUG else None,
    redoc_url="/api/redoc" if settings.DEBUG else None,
    openapi_url="/api/openapi.json" if settings.DEBUG else None,
)

# Add middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])
app.add_middleware(RateLimitMiddleware, limit=100, window=60)  # 100 requests per minute
app.add_middleware(RequestLoggingMiddleware)

# Custom exception handlers
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning(f"Validation error: {exc.errors()}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": exc.errors(), "body": exc.body},
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    if settings.SENTRY_DSN:
        sentry_sdk.capture_exception(exc)
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )

# Include routers with proper dependencies
app.include_router(auth.router, prefix="/api/v1/auth", tags=["authentication"])
app.include_router(transactions.router, prefix="/api/v1/transactions", tags=["transactions"])
app.include_router(documents.router, prefix="/api/v1/documents", tags=["documents"])
app.include_router(reports.router, prefix="/api/v1/reports", tags=["reports"])
app.include_router(ai.router, prefix="/api/v1/ai", tags=["ai"])
app.include_router(bank.router, prefix="/api/v1/bank", tags=["bank"])
app.include_router(tax.router, prefix="/api/v1/tax", tags=["tax"])
app.include_router(analytics.router, prefix="/api/v1/analytics", tags=["analytics"])

# WebSocket endpoints
@app.websocket("/ws")
async def websocket_endpoint(websocket):
    await websocket_manager.connect(websocket)

# Static files
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Metrics endpoint
@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    
    response.headers["X-Process-Time"] = str(process_time)
    
    # Record metrics
    REQUEST_COUNT.labels(
        method=request.method,
        endpoint=request.url.path,
        status=response.status_code
    ).inc()
    
    REQUEST_LATENCY.labels(endpoint=request.url.path).observe(process_time)
    
    return response

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.ENVIRONMENT,
        "status": "running",
        "docs": "/api/docs" if settings.DEBUG else None,
        "uptime": time.time() - app.state.start_time if hasattr(app.state, 'start_time') else 0
    }

@app.get("/health")
async def health_check(db=Depends(get_db)):
    """Comprehensive health check"""
    health_status = {
        "status": "healthy",
        "timestamp": time.time(),
        "services": {}
    }
    
    # Check database
    try:
        db.execute("SELECT 1")
        health_status["services"]["database"] = "connected"
    except Exception as e:
        health_status["services"]["database"] = f"error: {str(e)}"
        health_status["status"] = "degraded"
    
    # Check Redis
    from app.database import redis_client
    try:
        redis_client.ping()
        health_status["services"]["redis"] = "connected"
    except Exception as e:
        health_status["services"]["redis"] = f"error: {str(e)}"
        health_status["status"] = "degraded"
    
    # Check external services
    from app.core.config import settings
    
    if settings.OPENAI_API_KEY:
        health_status["services"]["openai"] = "configured"
    
    if settings.PLAID_CLIENT_ID and settings.PLAID_SECRET:
        health_status["services"]["plaid"] = "configured"
    
    return health_status

@app.get("/config")
async def get_config(current_user=Depends(get_current_user)):
    """Get frontend configuration"""
    return {
        "api_url": "/api/v1",
        "ws_url": f"ws://{settings.BACKEND_CORS_ORIGINS[0].split('://')[1]}/ws",
        "environment": settings.ENVIRONMENT,
        "features": {
            "ai_categorization": True,
            "bank_sync": bool(settings.PLAID_CLIENT_ID),
            "tax_optimization": True,
            "realtime_updates": True,
            "multi_company": True,
            "collaboration": True,
        },
        "limits": {
            "max_upload_size": settings.MAX_UPLOAD_SIZE,
            "max_documents": 1000,
            "max_transactions": 10000,
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
        log_level="info",
        access_log=False,
        proxy_headers=True,
    )
