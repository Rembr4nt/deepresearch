"""
Research API endpoints for Deep Research Web Interface

This module provides REST API endpoints for managing research sessions,
including starting, monitoring, and cancelling research operations.
"""

import logging
from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends

from app.models.requests import (
    ResearchRequest, ResearchConfig, SessionStatus,
    CancellationResponse, ResearchStatus, ResearchStartResponse
)
from app.core.research_manager import ResearchManager

# Create router
router = APIRouter(tags=["research"])

# Logger
logger = logging.getLogger(__name__)

# Dependency to get research manager
def get_research_manager() -> ResearchManager:
    """Dependency to get the research manager instance"""
    from app.main import get_research_manager
    manager = get_research_manager()
    if not manager:
        raise HTTPException(
            status_code=500, 
            detail="Research manager not initialized"
        )
    return manager


@router.post("/research/start", response_model=ResearchStartResponse)
async def start_research(
    request: ResearchRequest,
    background_tasks: BackgroundTasks,
    manager: ResearchManager = Depends(get_research_manager)
):
    """
    Start a new research session.
    
    Creates a new research session and starts the research process in the background.
    Only one research session can be active at a time.
    """
    try:
        # Validate topic using the existing validation from deep research
        import sys
        from pathlib import Path
        sys.path.append(str(Path(__file__).parent.parent.parent))
        from src.deep_research import validate_research_topic
        
        validated_topic = validate_research_topic(request.topic)
        
        # Use provided config or defaults
        config = request.config or ResearchConfig()
        
        # Create session
        session = await manager.create_session(validated_topic, config)
        
        # Start research in background
        background_tasks.add_task(manager.start_research, session.session_id)
        
        logger.info(f"Started research session {session.session_id} for topic: {validated_topic[:50]}...")
        
        return ResearchStartResponse(
            session_id=session.session_id,
            status=session.status,
            topic=session.topic,
            config=session.config,
            message=f"Research started for topic: {validated_topic[:100]}...",
            websocket_url=f"/ws/{session.session_id}"
        )
        
    except ValueError as e:
        # Validation error
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        # Another session already active - provide detailed information
        active_session = manager.get_active_session()
        if active_session:
            detail_msg = (
                f"Another research session is already active. "
                f"Active session: {active_session.session_id} "
                f"(Status: {active_session.status.value}, "
                f"Topic: '{active_session.topic[:50]}{'...' if len(active_session.topic) > 50 else ''}') "
                f"Please cancel the existing session or wait for it to complete before starting a new one."
            )
        else:
            detail_msg = str(e)
        
        raise HTTPException(
            status_code=409, 
            detail=detail_msg,
            headers={
                "X-Active-Session-Id": active_session.session_id if active_session else "",
                "X-Active-Session-Status": active_session.status.value if active_session else ""
            }
        )
    except Exception as e:
        logger.error(f"Error starting research: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/research/start-force", response_model=ResearchStartResponse)
async def start_research_force(
    request: ResearchRequest,
    background_tasks: BackgroundTasks,
    manager: ResearchManager = Depends(get_research_manager)
):
    """
    Force start a new research session, cancelling any active session.
    
    Creates a new research session after cancelling any currently active session.
    This endpoint allows overriding the single-session limitation.
    """
    try:
        # Cancel any active session first
        active_session = manager.get_active_session()
        if active_session and active_session.status in [ResearchStatus.PENDING, ResearchStatus.RUNNING]:
            await manager.cancel_session(active_session.session_id)
            logger.info(f"Cancelled active session {active_session.session_id} to start new research")
        
        # Validate topic using the existing validation from deep research
        import sys
        from pathlib import Path
        sys.path.append(str(Path(__file__).parent.parent.parent))
        from src.deep_research import validate_research_topic
        
        validated_topic = validate_research_topic(request.topic)
        
        # Use provided config or defaults
        config = request.config or ResearchConfig()
        
        # Create session
        session = await manager.create_session(validated_topic, config)
        
        # Start research in background
        background_tasks.add_task(manager.start_research, session.session_id)
        
        logger.info(f"Force started research session {session.session_id} for topic: {validated_topic[:50]}...")
        
        return ResearchStartResponse(
            session_id=session.session_id,
            status=session.status,
            topic=session.topic,
            config=session.config,
            message=f"Research force started for topic: {validated_topic[:100]}...",
            websocket_url=f"/ws/{session.session_id}"
        )
        
    except ValueError as e:
        # Validation error
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error force starting research: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/research/{session_id}", response_model=SessionStatus)
async def get_session_status(
    session_id: str,
    manager: ResearchManager = Depends(get_research_manager)
):
    """
    Get the status of a research session.
    
    Returns detailed information about the session including progress,
    current stage, and results (if completed).
    """
    session = manager.get_session(session_id)
    
    if not session:
        raise HTTPException(
            status_code=404, 
            detail=f"Session {session_id} not found"
        )
    
    return manager.to_session_status(session)


@router.delete("/research/{session_id}", response_model=CancellationResponse)
async def cancel_research(
    session_id: str,
    manager: ResearchManager = Depends(get_research_manager)
):
    """
    Cancel an active research session.
    
    Cancels the research process and updates the session status.
    Only pending or running sessions can be cancelled.
    """
    logger.debug(f"Cancel request received for session {session_id}")
    
    session = manager.get_session(session_id)
    
    if not session:
        logger.warning(f"Session {session_id} not found for cancellation")
        raise HTTPException(
            status_code=404, 
            detail=f"Session {session_id} not found"
        )
    
    logger.debug(f"Session {session_id} found, current status: {session.status}")
    
    if session.status not in [ResearchStatus.PENDING, ResearchStatus.RUNNING]:
        logger.warning(f"Session {session_id} cannot be cancelled, status: {session.status}")
        raise HTTPException(
            status_code=400,
            detail=f"Session {session_id} cannot be cancelled (status: {session.status})"
        )
    
    logger.debug(f"Attempting to cancel session {session_id}")
    success = await manager.cancel_session(session_id)
    
    if not success:
        logger.error(f"Failed to cancel session {session_id}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to cancel session {session_id}"
        )
    
    logger.debug(f"Successfully cancelled research session {session_id}")
    
    return CancellationResponse(
        session_id=session_id,
        status=ResearchStatus.CANCELLED,
        message=f"Research session {session_id} has been cancelled"
    )


@router.get("/research/active/status")
async def get_active_session_status(
    manager: ResearchManager = Depends(get_research_manager)
):
    """
    Get the status of the currently active research session.
    
    Returns the active session status or null if no session is active.
    """
    active_session = manager.get_active_session()
    
    if not active_session:
        return {"active_session": None}
    
    return {
        "active_session": manager.to_session_status(active_session)
    }


@router.post("/research/validate-topic")
async def validate_topic(request: dict):
    """
    Validate a research topic without starting research.
    
    Useful for frontend validation before submitting a research request.
    """
    topic = request.get("topic", "")
    
    if not topic:
        raise HTTPException(status_code=400, detail="Topic is required")
    
    try:
        # Import validation function
        import sys
        from pathlib import Path
        sys.path.append(str(Path(__file__).parent.parent.parent))
        from src.deep_research import validate_research_topic
        
        validated_topic = validate_research_topic(topic)
        
        return {
            "valid": True,
            "topic": validated_topic,
            "message": "Topic is valid"
        }
        
    except Exception as e:
        return {
            "valid": False,
            "topic": topic,
            "message": str(e)
        }


@router.get("/research/config/defaults")
async def get_default_config():
    """
    Get default configuration values for research parameters.
    
    Returns the default values that will be used if no custom configuration
    is provided when starting a research session.
    """
    return ResearchConfig().model_dump()

@router.post("/research/cleanup")
async def cleanup_completed_sessions(
    manager: ResearchManager = Depends(get_research_manager)
):
    """
    Clean up completed, failed, or cancelled research sessions.
    
    Removes sessions that have been in a terminal state for more than 1 hour.
    This helps manage memory usage and session storage.
    """
    try:
        cleaned_count = await manager.cleanup_completed_sessions()
        
        return {
            "success": True,
            "cleaned_sessions": cleaned_count,
            "message": f"Cleaned up {cleaned_count} completed sessions"
        }
        
    except Exception as e:
        logger.error(f"Error cleaning up sessions: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# Note: Exception handlers are added to the main FastAPI app, not the router