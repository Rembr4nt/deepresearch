"""
WebSocket handler for Deep Research Web Interface

This module provides WebSocket endpoints for real-time progress updates
during research sessions.
"""

import json
import logging
from typing import Dict, Set
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, WebSocketException

from app.models.requests import ProgressUpdate, WebSocketMessage
from app.core.research_manager import ResearchManager

# Create router
router = APIRouter(tags=["websocket"])

# Logger
logger = logging.getLogger(__name__)

# Store active WebSocket connections
class ConnectionManager:
    """Manages WebSocket connections for research progress updates"""
    
    def __init__(self):
        # Map of session_id -> set of WebSocket connections
        self.active_connections: Dict[str, Set[WebSocket]] = {}
    
    async def connect(self, websocket: WebSocket, session_id: str):
        """Accept a WebSocket connection and associate it with a session"""
        await websocket.accept()
        
        if session_id not in self.active_connections:
            self.active_connections[session_id] = set()
        
        self.active_connections[session_id].add(websocket)
        logger.info(f"WebSocket connected for session {session_id}")
    
    def disconnect(self, websocket: WebSocket, session_id: str):
        """Remove a WebSocket connection"""
        if session_id in self.active_connections:
            self.active_connections[session_id].discard(websocket)
            
            # Clean up empty session
            if not self.active_connections[session_id]:
                del self.active_connections[session_id]
        
        logger.info(f"WebSocket disconnected for session {session_id}")
    
    async def send_progress_update(self, session_id: str, progress_update: ProgressUpdate):
        """Send progress update to all connections for a session"""
        if session_id not in self.active_connections:
            return
        
        message = WebSocketMessage(
            type="progress_update",
            data=progress_update.model_dump(),
            session_id=session_id
        )
        
        # Send to all active connections for this session
        disconnected_connections = set()
        
        for connection in self.active_connections[session_id]:
            try:
                await connection.send_text(json.dumps(message.model_dump()))
            except Exception as e:
                logger.warning(f"Failed to send progress update to WebSocket: {e}")
                disconnected_connections.add(connection)
        
        # Clean up disconnected connections
        for connection in disconnected_connections:
            self.disconnect(connection, session_id)
    
    async def send_session_update(self, session_id: str, status_data: dict):
        """Send session status update to all connections"""
        if session_id not in self.active_connections:
            return
        
        message = WebSocketMessage(
            type="session_update",
            data=status_data,
            session_id=session_id
        )
        
        disconnected_connections = set()
        
        for connection in self.active_connections[session_id]:
            try:
                await connection.send_text(json.dumps(message.model_dump()))
            except Exception as e:
                logger.warning(f"Failed to send session update to WebSocket: {e}")
                disconnected_connections.add(connection)
        
        # Clean up disconnected connections
        for connection in disconnected_connections:
            self.disconnect(connection, session_id)
    
    async def send_message_to_session(self, session_id: str, message: dict):
        """
        Send custom message to all connections for a session
        
        Args:
            session_id: Session identifier
            message: Message dict to send
        """
        if session_id not in self.active_connections:
            return
        
        disconnected_connections = set()
        
        for connection in self.active_connections[session_id]:
            try:
                await connection.send_text(json.dumps(message))
            except Exception as e:
                logger.warning(f"Failed to send message to WebSocket: {e}")
                disconnected_connections.add(connection)
        
        # Clean up disconnected connections
        for connection in disconnected_connections:
            self.disconnect(connection, session_id)
    
    def get_connection_count(self, session_id: str) -> int:
        """Get number of active connections for a session"""
        return len(self.active_connections.get(session_id, set()))

# Global connection manager
connection_manager = ConnectionManager()

def get_research_manager() -> ResearchManager:
    """Get research manager instance"""
    from app.main import get_research_manager
    manager = get_research_manager()
    if not manager:
        raise WebSocketException(code=1011, reason="Research manager not available")
    return manager


@router.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """
    WebSocket endpoint for real-time progress updates.
    
    Clients connect to this endpoint to receive real-time updates
    about the progress of their research session.
    """
    try:
        # Get research manager
        manager = get_research_manager()
        
        # Verify session exists
        session = manager.get_session(session_id)
        if not session:
            await websocket.close(code=1008, reason=f"Session {session_id} not found")
            return
        
        # Accept connection
        await connection_manager.connect(websocket, session_id)
        
        # Create progress callback for this WebSocket
        async def websocket_progress_callback(progress_update: ProgressUpdate):
            """Callback to send progress updates via WebSocket"""
            await connection_manager.send_progress_update(session_id, progress_update)
        
        # Register the callback with the session
        manager.add_progress_callback(session_id, websocket_progress_callback)
        
        # Send initial session status
        session_status = manager.to_session_status(session)
        await connection_manager.send_session_update(
            session_id, 
            {
                "type": "initial_status",
                "status": session_status.model_dump()
            }
        )
        
        try:
            # Keep connection alive and handle incoming messages
            while True:
                # Wait for messages (for potential future client-to-server communication)
                try:
                    data = await websocket.receive_text()
                    
                    # Parse message
                    try:
                        message = json.loads(data)
                        await handle_websocket_message(websocket, session_id, message, manager)
                    except json.JSONDecodeError:
                        await websocket.send_text(json.dumps({
                            "type": "error",
                            "data": {"message": "Invalid JSON format"},
                            "session_id": session_id
                        }))
                        
                except WebSocketDisconnect:
                    break
                    
        except Exception as e:
            logger.error(f"Error in WebSocket connection for session {session_id}: {e}")
            
    except Exception as e:
        logger.error(f"Failed to establish WebSocket connection for session {session_id}: {e}")
        try:
            await websocket.close(code=1011, reason="Internal server error")
        except:
            pass
    
    finally:
        # Clean up
        connection_manager.disconnect(websocket, session_id)
        
        # Remove progress callback
        if 'websocket_progress_callback' in locals():
            manager.remove_progress_callback(session_id, websocket_progress_callback)


async def handle_websocket_message(
    websocket: WebSocket, 
    session_id: str, 
    message: dict, 
    manager: ResearchManager
):
    """
    Handle incoming WebSocket messages from clients.
    
    This allows for potential client-to-server communication,
    such as requesting status updates or sending commands.
    """
    message_type = message.get("type", "")
    
    if message_type == "ping":
        # Ping/pong for connection health
        await websocket.send_text(json.dumps({
            "type": "pong",
            "data": {"timestamp": message.get("data", {}).get("timestamp")},
            "session_id": session_id
        }))
        
    elif message_type == "request_status":
        # Client requesting current session status
        session = manager.get_session(session_id)
        if session:
            session_status = manager.to_session_status(session)
            await websocket.send_text(json.dumps({
                "type": "status_response",
                "data": session_status.model_dump(),
                "session_id": session_id
            }))
        else:
            await websocket.send_text(json.dumps({
                "type": "error",
                "data": {"message": f"Session {session_id} not found"},
                "session_id": session_id
            }))
    
    elif message_type == "cancel_request":
        # Client requesting to cancel the research
        logger.debug(f"WebSocket cancel_request received for session {session_id}")
        try:
            logger.debug(f"Calling manager.cancel_session({session_id}) via WebSocket")
            success = await manager.cancel_session(session_id)
            
            if success:
                logger.debug(f"WebSocket cancellation successful for session {session_id}")
                await websocket.send_text(json.dumps({
                    "type": "cancellation_confirmed",
                    "data": {"message": "Research has been cancelled"},
                    "session_id": session_id
                }))
                logger.debug(f"Sent cancellation_confirmed message via WebSocket for session {session_id}")
            else:
                logger.warning(f"WebSocket cancellation failed for session {session_id}")
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "data": {"message": "Failed to cancel research"},
                    "session_id": session_id
                }))
        except Exception as e:
            logger.error(f"WebSocket cancel_request error for session {session_id}: {str(e)}")
            await websocket.send_text(json.dumps({
                "type": "error",
                "data": {"message": f"Error cancelling research: {str(e)}"},
                "session_id": session_id
            }))
    
    elif message_type == "clarification_answer":
        # Handle Q&A answers from interactive mode
        try:
            data = message.get("data", {})
            question_id = data.get("question_id")
            selected_option = data.get("selected_option")
            
            if question_id and selected_option:
                # Forward answer to research manager
                manager.receive_qa_answer(session_id, question_id, selected_option)
                
                # Send acknowledgment
                await websocket.send_text(json.dumps({
                    "type": "answer_received",
                    "data": {"question_id": question_id, "answer": selected_option},
                    "session_id": session_id
                }))
            else:
                await websocket.send_text(json.dumps({
                    "type": "error",
                    "data": {"message": "Invalid clarification answer format"},
                    "session_id": session_id
                }))
                
        except Exception as e:
            await websocket.send_text(json.dumps({
                "type": "error",
                "data": {"message": f"Error handling clarification answer: {str(e)}"},
                "session_id": session_id
            }))
    
    else:
        # Unknown message type
        await websocket.send_text(json.dumps({
            "type": "error",
            "data": {"message": f"Unknown message type: {message_type}"},
            "session_id": session_id
        }))
