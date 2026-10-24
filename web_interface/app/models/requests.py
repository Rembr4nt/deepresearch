"""
Pydantic models for Deep Research Web Interface

This module defines all request and response models used by the FastAPI endpoints
and WebSocket connections for the Deep Research web interface.
"""

from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, field_validator
from enum import Enum


class ResearchStatus(str, Enum):
    """Enum for research session status"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class ProgressStage(str, Enum):
    """Enum for research progress stages"""
    INITIALIZATION = "initialization"
    QUERY_GENERATION = "query_generation"
    SEARCH = "search"
    SEARCH_COMPLETE = "search_complete"
    EVALUATION = "evaluation"
    ADDITIONAL_SEARCH = "additional_search"
    SEARCH_TIMEOUT = "search_timeout"
    SEARCH_ERROR = "search_error"
    EVALUATION_TIMEOUT = "evaluation_timeout"
    EVALUATION_ERROR = "evaluation_error"
    FILTERING = "filtering"
    PROCESSING = "processing"
    SUMMARIZING_CONTENT = "summarizing_content"
    CREATING_META_SUMMARY = "creating_meta_summary"
    REPORT_GENERATION = "report_generation"
    COMPLETE = "complete"


class ResearchConfig(BaseModel):
    """Configuration model for research parameters"""
    max_queries: int = Field(default=5, ge=1, le=20, description="Maximum number of search queries")
    max_searchs: int = Field(default=5, ge=1, le=10, description="Maximum search results per query")
    max_iteration: int = Field(default=3, ge=1, le=10, description="Maximum research iterations")
    max_completion_token: int = Field(default=8192, ge=1024, le=16384, description="Maximum completion tokens")
    rerank_score_threshold: float = Field(default=0.6, ge=0.1, le=1.0, description="Relevance score threshold")
    remove_thinking_token: bool = Field(default=True, description="Remove thinking tokens from output")
    interactive: bool = Field(default=False, description="Enable interactive clarification questions")
    use_async: bool = Field(default=True, description="Enable async processing")

    @field_validator('rerank_score_threshold')
    @classmethod
    def validate_threshold(cls, v):
        """Validate rerank score threshold is reasonable"""
        return round(v, 2)


class ResearchRequest(BaseModel):
    """Request model for starting a research session"""
    topic: str = Field(..., min_length=3, max_length=1000, description="Research topic")
    config: Optional[ResearchConfig] = Field(default=None, description="Research configuration")

    @field_validator('topic')
    @classmethod
    def validate_topic(cls, v):
        """Basic topic validation"""
        if not v or not v.strip():
            raise ValueError("Topic cannot be empty")
        return v.strip()


class ResearchResponse(BaseModel):
    """Response model for research session creation"""
    session_id: str = Field(..., description="Unique session identifier")
    status: ResearchStatus = Field(..., description="Current session status")
    topic: str = Field(..., description="Research topic")
    config: ResearchConfig = Field(..., description="Applied research configuration")
    message: str = Field(..., description="Human-readable status message")


class ProgressUpdate(BaseModel):
    """Model for progress updates sent via WebSocket"""
    session_id: str = Field(..., description="Session identifier")
    stage: ProgressStage = Field(..., description="Current progress stage")
    progress: float = Field(..., ge=0.0, le=1.0, description="Progress percentage (0.0 to 1.0)")
    message: str = Field(..., description="Human-readable progress message")
    details: Dict[str, Any] = Field(default_factory=dict, description="Additional progress details")
    timestamp: Optional[str] = Field(default=None, description="ISO timestamp of update")

    @field_validator('progress')
    @classmethod
    def validate_progress(cls, v):
        """Ensure progress is between 0 and 1"""
        return max(0.0, min(1.0, v))


class SessionStatus(BaseModel):
    """Model for session status response"""
    session_id: str = Field(..., description="Session identifier")
    status: ResearchStatus = Field(..., description="Current session status")
    topic: str = Field(..., description="Research topic")
    config: ResearchConfig = Field(..., description="Research configuration")
    progress: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="Current progress")
    current_stage: Optional[ProgressStage] = Field(default=None, description="Current processing stage")
    result: Optional[str] = Field(default=None, description="Research result (if completed)")
    error_message: Optional[str] = Field(default=None, description="Error message (if failed)")
    created_at: str = Field(..., description="Session creation timestamp")
    updated_at: str = Field(..., description="Last update timestamp")
    completed_at: Optional[str] = Field(default=None, description="Completion timestamp")


class CancellationResponse(BaseModel):
    """Response model for research cancellation"""
    session_id: str = Field(..., description="Session identifier")
    status: ResearchStatus = Field(..., description="Updated session status")
    message: str = Field(..., description="Cancellation confirmation message")


class ErrorResponse(BaseModel):
    """Standard error response model"""
    error: str = Field(..., description="Error type")
    message: str = Field(..., description="Human-readable error message")
    details: Optional[Dict[str, Any]] = Field(default=None, description="Additional error details")
    session_id: Optional[str] = Field(default=None, description="Related session ID (if applicable)")


class ConfigDefaults(BaseModel):
    """Model for default configuration values"""
    max_queries: int
    max_searchs: int
    max_iteration: int
    max_completion_token: int
    rerank_score_threshold: float
    remove_thinking_token: bool
    interactive: bool
    use_async: bool


class WebSocketMessage(BaseModel):
    """Model for WebSocket message handling"""
    type: str = Field(..., description="Message type")
    data: Dict[str, Any] = Field(..., description="Message data")
    session_id: Optional[str] = Field(default=None, description="Related session ID")


# Interactive Q&A Models
class ClarificationQuestion(BaseModel):
    """Model for clarification questions in interactive mode"""
    question_id: str = Field(..., description="Unique question identifier")
    question_num: int = Field(..., description="Question number in sequence")
    question: str = Field(..., description="The clarification question text")
    options: List[str] = Field(..., description="Available answer options")
    default: str = Field(..., description="Default/recommended option")
    total_questions: int = Field(..., description="Total number of questions")


class ClarificationAnswer(BaseModel):
    """Model for user's answer to clarification question"""
    question_id: str = Field(..., description="Question identifier")
    selected_option: str = Field(..., description="User's selected answer")


class ClarificationComplete(BaseModel):
    """Model for completion of clarification phase"""
    original_topic: str = Field(..., description="Original research topic")
    refined_topic: str = Field(..., description="Refined topic after clarification")
    answers: Dict[int, str] = Field(..., description="All Q&A pairs")


class HealthResponse(BaseModel):
    """Health check response model"""
    status: str = Field(..., description="Service health status")
    service: str = Field(..., description="Service name")
    version: str = Field(..., description="Service version")
    uptime: Optional[float] = Field(default=None, description="Uptime in seconds")


# Response models for OpenAPI documentation
class ResearchStartResponse(ResearchResponse):
    """Response model specifically for research start endpoint"""
    websocket_url: str = Field(..., description="WebSocket URL for progress updates")


class SessionListResponse(BaseModel):
    """Response model for listing sessions (if needed for debugging)"""
    sessions: List[SessionStatus] = Field(..., description="List of active sessions")
    total: int = Field(..., description="Total number of sessions")