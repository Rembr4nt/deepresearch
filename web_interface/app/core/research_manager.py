"""
Research Session Manager for Deep Research Web Interface

This module manages research sessions, handles cancellation, progress tracking,
and coordinates with the core Deep Research system.
"""

import asyncio
import uuid
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Callable, Any
from dataclasses import dataclass, field

from app.models.requests import (
    ResearchConfig, ResearchStatus, ProgressUpdate, 
    SessionStatus, ProgressStage
)

# Import the core research system
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))

from src.deep_research import InteractiveDeepResearch
# Import WebQA handler for interactive web mode
from src.web_qa_handler import create_web_qa_handler

# Import WebSocket connection manager for notifications
def get_connection_manager():
    """Get the WebSocket connection manager - import dynamically to avoid circular imports"""
    from app.api.websocket import connection_manager
    return connection_manager


@dataclass
class ResearchSession:
    """Represents an active research session"""
    session_id: str
    topic: str
    config: ResearchConfig
    status: ResearchStatus
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    progress: float = 0.0
    current_stage: Optional[ProgressStage] = None
    result: Optional[str] = None
    error_message: Optional[str] = None
    task: Optional[asyncio.Task] = None
    progress_callbacks: list = field(default_factory=list)


class ResearchManager:
    """
    Manages research sessions with single-user constraint and cancellation support.
    
    This manager ensures only one research session can run at a time,
    provides progress tracking, and handles proper cleanup and cancellation.
    """
    
    def __init__(self, session_timeout_hours: int = 1):
        self.sessions: Dict[str, ResearchSession] = {}
        self.active_session_id: Optional[str] = None
        self.session_timeout = timedelta(hours=session_timeout_hours)
        self.logger = logging.getLogger(__name__)
        
        # Start cleanup task
        self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
    
    async def create_session(
        self, 
        topic: str, 
        config: ResearchConfig
    ) -> ResearchSession:
        """
        Create a new research session.
        
        Args:
            topic: Research topic
            config: Research configuration
            
        Returns:
            ResearchSession: Created session
            
        Raises:
            RuntimeError: If another session is already active
        """
        # Check if there's already an active session
        if self.active_session_id and self.active_session_id in self.sessions:
            active_session = self.sessions[self.active_session_id]
            if active_session.status in [ResearchStatus.PENDING, ResearchStatus.RUNNING]:
                raise RuntimeError(
                    f"Another research session is already active: {active_session.session_id}"
                )
        
        # Generate unique session ID
        session_id = str(uuid.uuid4())
        
        # Create session
        session = ResearchSession(
            session_id=session_id,
            topic=topic,
            config=config,
            status=ResearchStatus.PENDING,
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        
        # Store session
        self.sessions[session_id] = session
        self.active_session_id = session_id
        
        self.logger.info(f"Created research session {session_id} for topic: {topic[:50]}...")
        return session
    
    async def start_research(self, session_id: str) -> None:
        """
        Start the research process for a given session.
        
        Args:
            session_id: Session identifier
            
        Raises:
            ValueError: If session not found or already running
        """
        if session_id not in self.sessions:
            raise ValueError(f"Session {session_id} not found")
        
        session = self.sessions[session_id]
        
        if session.status != ResearchStatus.PENDING:
            raise ValueError(f"Session {session_id} is not in pending state")
        
        # Update session status
        session.status = ResearchStatus.RUNNING
        session.updated_at = datetime.now()
        session.current_stage = ProgressStage.INITIALIZATION
        
        # Create progress callback for this session
        async def progress_callback(progress_data: Dict[str, Any]):
            await self._update_session_progress(session_id, progress_data)
        
        # Create and start research task
        session.task = asyncio.create_task(
            self._run_research(session, progress_callback)
        )
        
        self.logger.info(f"Started research for session {session_id}")
    
    async def cancel_session(self, session_id: str) -> bool:
        """
        Cancel an active research session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            bool: True if cancelled successfully, False if not found or not active
        """
        self.logger.debug(f"ResearchManager.cancel_session() called for session {session_id}")
        
        if session_id not in self.sessions:
            self.logger.warning(f"Session {session_id} not found in sessions dict")
            return False
        
        session = self.sessions[session_id]
        self.logger.debug(f"Session {session_id} found, current status: {session.status}")
        
        if session.status not in [ResearchStatus.PENDING, ResearchStatus.RUNNING]:
            self.logger.warning(f"Session {session_id} not in cancellable state: {session.status}")
            return False
        
        # Cancel the task if it exists
        if session.task and not session.task.done():
            self.logger.debug(f"Cancelling asyncio task for session {session_id}")
            session.task.cancel()
            try:
                await session.task
                self.logger.debug(f"Asyncio task cancelled successfully for session {session_id}")
            except asyncio.CancelledError:
                self.logger.debug(f"Asyncio task CancelledError caught for session {session_id}")
                pass
        else:
            self.logger.debug(f"No active task to cancel for session {session_id}")
        
        # Update session status
        self.logger.debug(f"Updating session {session_id} status to CANCELLED")
        session.status = ResearchStatus.CANCELLED
        session.updated_at = datetime.now()
        session.completed_at = datetime.now()
        
        # Clear active session if this was it
        if self.active_session_id == session_id:
            self.logger.debug(f"Clearing active session ID (was {session_id})")
            self.active_session_id = None
        else:
            self.logger.debug(f"Session {session_id} was not the active session (active: {self.active_session_id})")
        
        self.logger.debug(f"Successfully cancelled research session {session_id}")
        return True
    
    def get_session(self, session_id: str) -> Optional[ResearchSession]:
        """Get a session by ID"""
        return self.sessions.get(session_id)
    
    def get_active_session(self) -> Optional[ResearchSession]:
        """Get the currently active session"""
        if self.active_session_id:
            return self.sessions.get(self.active_session_id)
        return None
    
    def add_progress_callback(self, session_id: str, callback: Callable):
        """Add a progress callback for a session (for WebSocket updates)"""
        if session_id in self.sessions:
            self.sessions[session_id].progress_callbacks.append(callback)
    
    def remove_progress_callback(self, session_id: str, callback: Callable):
        """Remove a progress callback for a session"""
        if session_id in self.sessions:
            session = self.sessions[session_id]
            if callback in session.progress_callbacks:
                session.progress_callbacks.remove(callback)
    
    async def cleanup_all_sessions(self):
        """Cleanup all sessions (called on shutdown)"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
        
        for session_id in list(self.sessions.keys()):
            await self.cancel_session(session_id)
        
        self.sessions.clear()
        self.active_session_id = None
    
    async def _run_research(
        self, 
        session: ResearchSession, 
        progress_callback: Callable
    ) -> None:
        """
        Execute the research process for a session.
        
        Args:
            session: Research session
            progress_callback: Progress update callback
        """
        try:
            # Web Q&A, only when interactive=True
            web_qa_handler = None
            if session.config.interactive:
                # Create WebSocket callback for Q&A communication
                async def websocket_qa_callback(message):
                    connection_manager = get_connection_manager()
                    
                    # Wait for WebSocket connection to be established
                    max_wait = 10  # seconds
                    wait_interval = 0.1  # seconds
                    waited = 0
                    
                    while session.session_id not in connection_manager.active_connections and waited < max_wait:
                        self.logger.debug(f"Waiting for WebSocket connection for session {session.session_id} (waited {waited:.1f}s)")
                        await asyncio.sleep(wait_interval)
                        waited += wait_interval
                    
                    if session.session_id in connection_manager.active_connections:
                        self.logger.debug(f"WebSocket connection found, sending message: {message['type']}")
                        await connection_manager.send_message_to_session(
                            session.session_id, 
                            message
                        )
                        self.logger.debug(f"Message sent successfully")
                    else:
                        self.logger.error(f"WebSocket connection not available after {max_wait}s, dropping message: {message['type']}")
                
                # Create web Q&A handler
                web_qa_handler = create_web_qa_handler(
                    websocket_callback=websocket_qa_callback,
                    timeout=300  # 5 minutes timeout
                )
                
                # Set up answer reception from WebSocket
                self._setup_qa_handler(session.session_id, web_qa_handler)
            
            # interactive=False: the web UI asks clarifying questions over WebSocket instead of the terminal
            researcher = InteractiveDeepResearch(
                max_queries=session.config.max_queries,
                max_searchs=session.config.max_searchs,
                max_iteration=session.config.max_iteration,
                max_completion_token=session.config.max_completion_token,
                rerank_score_threshold=session.config.rerank_score_threshold,
                remove_thinking_token=session.config.remove_thinking_token,
                interactive=False,
                use_async=session.config.use_async,
                progress_callback=progress_callback
            )
            
            # Run the research (with web Q&A support if interactive)
            if session.config.interactive and web_qa_handler:
                # Use web-compatible interactive research
                result = await self._run_interactive_web_research(
                    researcher, session.topic, web_qa_handler
                )
            else:
                # Non-interactive research
                result = await researcher.async_call(session.topic)
            
            # Update session with results
            session.status = ResearchStatus.COMPLETED
            session.result = result
            session.progress = 1.0
            session.current_stage = ProgressStage.COMPLETE
            session.completed_at = datetime.now()
            session.updated_at = datetime.now()
            
            # Clear active session
            if self.active_session_id == session.session_id:
                self.active_session_id = None
            
            self.logger.info(f"Research completed for session {session.session_id}")
            
            # Notify WebSocket clients of completion
            try:
                connection_manager = get_connection_manager()
                session_status = self.to_session_status(session)
                await connection_manager.send_session_update(
                    session.session_id,
                    {"status": session_status.model_dump()}
                )
                self.logger.info(f"Sent completion notification for session {session.session_id}")
            except Exception as e:
                self.logger.warning(f"Failed to send completion notification for session {session.session_id}: {e}")
            
        except asyncio.CancelledError:
            # Task was cancelled
            self.logger.debug(f"Research task cancelled via asyncio.CancelledError for session {session.session_id}")
            session.status = ResearchStatus.CANCELLED
            session.completed_at = datetime.now()
            session.updated_at = datetime.now()
            self.logger.debug(f"Updated session {session.session_id} status to CANCELLED due to asyncio.CancelledError")
            
            # Notify WebSocket clients of cancellation
            try:
                self.logger.debug(f"Sending cancellation notification via WebSocket for session {session.session_id}")
                connection_manager = get_connection_manager()
                session_status = self.to_session_status(session)
                await connection_manager.send_session_update(
                    session.session_id,
                    {"status": session_status.model_dump()}
                )
                self.logger.debug(f"Successfully sent cancellation notification for session {session.session_id}")
            except Exception as e:
                self.logger.warning(f"Failed to send cancellation notification for session {session.session_id}: {e}")
            
            raise
            
        except Exception as e:
            # Research failed
            session.status = ResearchStatus.FAILED
            session.error_message = str(e)
            session.completed_at = datetime.now()
            session.updated_at = datetime.now()
            
            # Clear active session
            if self.active_session_id == session.session_id:
                self.active_session_id = None
            
            self.logger.error(f"Research failed for session {session.session_id}: {e}")
            
            # Notify WebSocket clients of failure
            try:
                connection_manager = get_connection_manager()
                session_status = self.to_session_status(session)
                await connection_manager.send_session_update(
                    session.session_id,
                    {"status": session_status.model_dump()}
                )
            except Exception as notify_error:
                self.logger.warning(f"Failed to send failure notification for session {session.session_id}: {notify_error}")
        
        finally:
            # Clean up Q&A handler
            if hasattr(self, '_qa_handlers') and session.session_id in self._qa_handlers:
                del self._qa_handlers[session.session_id]
                self.logger.info(f"Cleaned up Q&A handler for session {session.session_id}")
    
    async def _update_session_progress(
        self, 
        session_id: str, 
        progress_data: Dict[str, Any]
    ) -> None:
        """Update session progress and notify callbacks"""
        if session_id not in self.sessions:
            return
        
        session = self.sessions[session_id]
        
        # Update session progress
        session.progress = progress_data.get('progress', session.progress)
        session.current_stage = progress_data.get('stage', session.current_stage)
        session.updated_at = datetime.now()
        
        # Create progress update object
        progress_update = ProgressUpdate(
            session_id=session_id,
            stage=session.current_stage or ProgressStage.INITIALIZATION,
            progress=session.progress,
            message=progress_data.get('message', ''),
            details=progress_data.get('details', {}),
            timestamp=datetime.now().isoformat()
        )
        
        # Notify all progress callbacks
        for callback in session.progress_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(progress_update)
                else:
                    callback(progress_update)
            except Exception as e:
                self.logger.warning(f"Progress callback failed for session {session_id}: {e}")
    
    async def _periodic_cleanup(self):
        """Periodic cleanup of expired sessions"""
        while True:
            try:
                await asyncio.sleep(300)  # Check every 5 minutes
                
                current_time = datetime.now()
                expired_sessions = []
                
                for session_id, session in self.sessions.items():
                    # Check if session is expired
                    if (current_time - session.updated_at) > self.session_timeout:
                        if session.status in [ResearchStatus.COMPLETED, ResearchStatus.FAILED, ResearchStatus.CANCELLED]:
                            expired_sessions.append(session_id)
                        elif session.status in [ResearchStatus.PENDING, ResearchStatus.RUNNING]:
                            # Cancel running sessions that are too old
                            await self.cancel_session(session_id)
                            expired_sessions.append(session_id)
                
                # Remove expired sessions
                for session_id in expired_sessions:
                    if session_id in self.sessions:
                        del self.sessions[session_id]
                        self.logger.info(f"Cleaned up expired session {session_id}")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in periodic cleanup: {e}")
                await asyncio.sleep(60)  # Wait before retrying

    async def cleanup_completed_sessions(self):
        """Clean up sessions that have completed, failed, or been cancelled"""
        current_time = datetime.now()
        completed_sessions = []
        
        for session_id, session in self.sessions.items():
            # Clean up sessions that finished more than 1 hour ago
            if (session.status in [ResearchStatus.COMPLETED, ResearchStatus.FAILED, ResearchStatus.CANCELLED] 
                and (current_time - session.updated_at) > timedelta(hours=1)):
                completed_sessions.append(session_id)
        
        # Remove completed sessions
        for session_id in completed_sessions:
            if session_id in self.sessions:
                del self.sessions[session_id]
                if self.active_session_id == session_id:
                    self.active_session_id = None
                self.logger.info(f"Cleaned up completed session {session_id}")
        
        return len(completed_sessions)
    
    def to_session_status(self, session: ResearchSession) -> SessionStatus:
        """Convert ResearchSession to SessionStatus model"""
        return SessionStatus(
            session_id=session.session_id,
            status=session.status,
            topic=session.topic,
            config=session.config,
            progress=session.progress,
            current_stage=session.current_stage,
            result=session.result,
            error_message=session.error_message,
            created_at=session.created_at.isoformat(),
            updated_at=session.updated_at.isoformat(),
            completed_at=session.completed_at.isoformat() if session.completed_at else None
        )
    
    # ============================================
    # Web Q&A Integration Methods
    # ============================================
    
    def _setup_qa_handler(self, session_id: str, web_qa_handler):
        """
        Set up Q&A handler for session to receive answers from WebSocket
        
        Args:
            session_id: Session identifier
            web_qa_handler: WebQA handler instance
        """
        # Store the handler so WebSocket can send answers to it
        if not hasattr(self, '_qa_handlers'):
            self._qa_handlers = {}
        self._qa_handlers[session_id] = web_qa_handler
        
        self.logger.info(f"Set up WebQA handler for session {session_id}")
    
    def receive_qa_answer(self, session_id: str, question_id: str, selected_option: str):
        """
        Receive Q&A answer from WebSocket and forward to handler
        
        Args:
            session_id: Session identifier
            question_id: Question identifier
            selected_option: User's selected answer
        """
        if hasattr(self, '_qa_handlers') and session_id in self._qa_handlers:
            qa_handler = self._qa_handlers[session_id]
            qa_handler.receive_answer(question_id, selected_option)
            self.logger.info(f"Forwarded Q&A answer for session {session_id}: {selected_option}")
        else:
            self.logger.warning(f"No Q&A handler found for session {session_id}")
    
    async def _run_interactive_web_research(self, researcher, topic: str, web_qa_handler):
        """
        Run interactive research using web Q&A handler instead of terminal input
        
        Args:
            researcher: InteractiveDeepResearch instance
            topic: Research topic
            web_qa_handler: Web Q&A handler
            
        Returns:
            str: Research result
        """
        try:
            # Get clarification data from researcher (reuse existing logic)
            self.logger.debug(f"Analyzing clarification needs for topic: {topic}")
            clarification_data = researcher._analyze_clarification_needs(topic)
            self.logger.debug(f"Clarification data: {clarification_data}")
            
            if clarification_data.get("needs_clarification", False):
                # Use web Q&A handler instead of terminal input
                self.logger.debug("Clarification needed, starting web Q&A process")
                refined_topic = await web_qa_handler.ask_clarifications_web(topic, clarification_data)
                self.logger.info(f"Web Q&A refined topic: {refined_topic}")
            else:
                refined_topic = topic
                self.logger.debug("No clarification needed, proceeding with original topic")
            
            # Continue with normal research using refined topic
            # Use topic_deep_research_async to bypass interactive mode (already handled)
            return await researcher.topic_deep_research_async(refined_topic)
            
        except Exception as e:
            self.logger.error(f"Error in interactive web research: {e}")
            # Fallback to non-interactive research
            researcher.interactive = False
            return await researcher.async_call(topic)