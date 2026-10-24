"""
FastAPI Web Interface for Deep Research System

This module provides a web interface for the Deep Research system,
enabling users to conduct research through a clean web UI with real-time progress tracking.
"""

import sys
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse

# Add the parent directory to Python path to import deep research modules
sys.path.append(str(Path(__file__).parent.parent.parent))

from app.api import research, websocket
from app.core.research_manager import ResearchManager
from app.models.requests import ErrorResponse

# Global research manager instance
research_manager: ResearchManager = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan - startup and shutdown events"""
    global research_manager
    
    # Startup
    print("🚀 Starting Deep Research Web Interface...")
    research_manager = ResearchManager()
    
    # Validate API keys on startup
    try:
        from src.deep_research import validate_api_keys
        validate_api_keys()
        print("✅ API keys validated successfully")
    except Exception as e:
        print(f"❌ API key validation failed: {e}")
        print("Please ensure TOGETHER_API_KEY, VOYAGE_API_KEY, and TAVILY_API_KEY are set in .env file")
    
    yield
    
    # Shutdown
    print("🛑 Shutting down Deep Research Web Interface...")
    if research_manager:
        await research_manager.cleanup_all_sessions()

# Create FastAPI application
app = FastAPI(
    title="Deep Research Web Interface",
    description="AI-powered deep research tool with web interface",
    version="1.0.0",
    lifespan=lifespan
)

# No CORS middleware: the UI is served from this same origin.

# Exception handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions with proper error response format"""
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error="HTTP_ERROR",
            message=exc.detail
        ).model_dump()
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle general exceptions with proper error response format"""
    import logging
    logger = logging.getLogger(__name__)
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="INTERNAL_ERROR",
            message="An unexpected error occurred"
        ).model_dump()
    )

# Include API routes
app.include_router(research.router, prefix="/api")
app.include_router(websocket.router)

# Mount static files
static_path = Path(__file__).parent.parent / "static"
app.mount("/static", StaticFiles(directory=static_path), name="static")

@app.get("/", response_class=HTMLResponse)
async def read_root():
    """Serve the main HTML page"""
    html_file = static_path / "index.html"
    if html_file.exists():
        return HTMLResponse(content=html_file.read_text(), status_code=200)
    else:
        return HTMLResponse(
            content="<h1>Deep Research Web Interface</h1><p>Frontend not found. Please check static files.</p>",
            status_code=404
        )

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "Deep Research Web Interface",
        "version": "1.0.0"
    }

# Make research manager available to other modules
def get_research_manager() -> ResearchManager:
    """Get the global research manager instance"""
    return research_manager
