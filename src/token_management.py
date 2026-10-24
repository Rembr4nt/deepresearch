"""
Token management for Deep Research

This module provides comprehensive token counting, context optimization, and management
capabilities for AI model interactions, ensuring optimal context utilization while 
respecting model token limits.
"""

import tiktoken
import logging
from typing import List, Dict, Tuple
from dataclasses import dataclass
from .data_types import DeepResearchResults
from .utils import llm_rerank

logger = logging.getLogger(__name__)

@dataclass
class TokenInfo:
    """Information about token usage"""
    content: str
    token_count: int
    char_count: int
    estimated_tokens: int

@dataclass
class ContextSegment:
    """Represents a segment of context with metadata"""
    content: str
    token_count: int
    priority: int  # Higher number = higher priority
    segment_type: str  # 'topic', 'queries', 'results', 'summary'
    relevance_score: float = 0.0

class TokenCounter:
    """Advanced token counting utility using tiktoken"""
    
    def __init__(self, model_name: str = "gpt-4"):
        """
        Initialize token counter with specific model encoding
        
        Args:
            model_name: Model name for token encoding (defaults to gpt-4 for compatibility)
        """
        try:
            # Try to get model-specific encoding
            self.encoding = tiktoken.encoding_for_model(model_name)
        except KeyError:
            # Fallback to cl100k_base for unknown models (covers most modern models)
            logger.warning(f"Unknown model {model_name}, using cl100k_base encoding")
            self.encoding = tiktoken.get_encoding("cl100k_base")
    
    def count_tokens(self, text: str) -> int:
        """
        Count exact tokens in text using tiktoken
        
        Args:
            text: Text to count tokens for
            
        Returns:
            Exact token count
        """
        if not text:
            return 0
        return len(self.encoding.encode(text))
    
    def get_token_info(self, text: str) -> TokenInfo:
        """
        Get comprehensive token information for text
        
        Args:
            text: Text to analyze
            
        Returns:
            TokenInfo object with detailed metrics
        """
        token_count = self.count_tokens(text)
        char_count = len(text)
        # Rough estimation: ~4 chars per token
        estimated_tokens = char_count // 4
        
        return TokenInfo(
            content=text,
            token_count=token_count,
            char_count=char_count,
            estimated_tokens=estimated_tokens
        )
    
    def truncate_to_tokens(self, text: str, max_tokens: int, suffix: str = "...") -> str:
        """
        Truncate text to fit within token limit
        
        Args:
            text: Text to truncate
            max_tokens: Maximum allowed tokens
            suffix: Suffix to add when truncating
            
        Returns:
            Truncated text that fits within token limit
        """
        if not text:
            return text
            
        tokens = self.encoding.encode(text)
        if len(tokens) <= max_tokens:
            return text
        
        # Reserve tokens for suffix
        suffix_tokens = self.count_tokens(suffix)
        available_tokens = max_tokens - suffix_tokens
        
        if available_tokens <= 0:
            return suffix
        
        # Truncate and decode
        truncated_tokens = tokens[:available_tokens]
        truncated_text = self.encoding.decode(truncated_tokens)
        
        return truncated_text + suffix

class ContextManager:
    """
    Advanced context management system with dual-stream architecture
    
    Maintains separate optimized contexts for planning vs reporting models
    while preserving all information for final report generation.
    """
    
    def __init__(self, token_counter: TokenCounter, planning_limit: int = 100000, report_limit: int = 400000):
        """
        Initialize context manager
        
        Args:
            token_counter: TokenCounter instance
            planning_limit: Token limit for planning context (default: ~100K tokens)
            report_limit: Token limit for report context (default: ~400K tokens)
        """
        self.token_counter = token_counter
        self.planning_limit = planning_limit
        self.report_limit = report_limit
        
        # Dual context storage
        self._planning_context: List[ContextSegment] = []
        self._report_context: List[ContextSegment] = []
        
        # Context history for progressive summarization
        self._context_history: List[Dict] = []
    
    def add_context_segment(
        self, 
        content: str, 
        segment_type: str, 
        priority: int = 5,
        relevance_score: float = 0.0
    ) -> None:
        """
        Add a context segment to both planning and report contexts
        
        Args:
            content: Context content
            segment_type: Type of context ('topic', 'queries', 'results', 'summary')
            priority: Priority level (1-10, higher = more important)
            relevance_score: Relevance score from semantic ranking (0.0-1.0)
        """
        token_count = self.token_counter.count_tokens(content)
        
        segment = ContextSegment(
            content=content,
            token_count=token_count,
            priority=priority,
            segment_type=segment_type,
            relevance_score=relevance_score
        )
        
        # Add to both contexts
        self._planning_context.append(segment)
        self._report_context.append(segment)
        
        logger.debug(f"Added context segment: {segment_type}, tokens: {token_count}, priority: {priority}")
    
    def get_planning_context(self, research_topic: str = "", additional_tokens: int = 2048) -> str:
        """
        Get optimized context for planning model calls with semantic ranking
        
        Args:
            research_topic: Current research topic for relevance ranking
            additional_tokens: Tokens to reserve for model response
            
        Returns:
            Optimized context string that fits within planning token limit
        """
        available_tokens = self.planning_limit - additional_tokens
        
        # Apply semantic ranking if research topic provided
        if research_topic and len(self._planning_context) > 1:
            self._rank_context_segments(self._planning_context, research_topic)
        
        return self._build_optimized_context(self._planning_context, available_tokens)
    
    def get_report_context(self, additional_tokens: int = 4096) -> str:
        """
        Get complete context for report generation
        
        Args:
            additional_tokens: Tokens to reserve for model response
            
        Returns:
            Complete context string for report generation
        """
        available_tokens = self.report_limit - additional_tokens
        return self._build_optimized_context(self._report_context, available_tokens)
    
    def _rank_context_segments(self, segments: List[ContextSegment], research_topic: str) -> None:
        """
        Rank context segments by relevance to research topic using Voyage AI
        
        Args:
            segments: List of context segments to rank
            research_topic: Research topic for relevance comparison
        """
        try:
            # Prepare documents for reranking (only rankable segments)
            rankable_segments = [s for s in segments if s.segment_type in ['results', 'summary']]
            
            if len(rankable_segments) < 2:
                logger.debug("Not enough rankable segments for semantic ranking")
                return
            
            # Create documents list for Voyage AI
            documents = []
            segment_map = {}
            
            for i, segment in enumerate(rankable_segments):
                # Use first 1000 chars to avoid overwhelming the reranker
                doc_content = segment.content[:1000] if len(segment.content) > 1000 else segment.content
                documents.append(doc_content)
                segment_map[i] = segment
            
            # Call Voyage AI reranking
            rerank_response = llm_rerank(
                topic=research_topic,
                documents=documents,
                model="rerank-2",
                top_k_documents=len(documents)  # Rank all documents
            )
            
            # Update relevance scores based on reranking results
            for result in rerank_response.results:
                if result.index in segment_map:
                    segment = segment_map[result.index]
                    segment.relevance_score = result.relevance_score
                    logger.debug(f"Updated relevance score for {segment.segment_type}: {result.relevance_score:.3f}")
            
            logger.info(f"Successfully ranked {len(rankable_segments)} context segments by relevance")
            
        except Exception as e:
            logger.warning(f"Failed to rank context segments: {e}")
            # Continue without ranking - system should still work
    
    def _build_optimized_context(self, segments: List[ContextSegment], max_tokens: int) -> str:
        """
        Build optimized context within token limits using intelligent prioritization
        
        Args:
            segments: List of context segments
            max_tokens: Maximum tokens allowed
            
        Returns:
            Optimized context string
        """
        if not segments:
            return ""
        
        # Sort by priority (high to low), then by relevance score
        sorted_segments = sorted(
            segments, 
            key=lambda x: (x.priority, x.relevance_score), 
            reverse=True
        )
        
        # Always include highest priority segments first
        selected_segments = []
        current_tokens = 0
        
        # First pass: Include all high-priority segments (priority >= 8)
        for segment in sorted_segments:
            if segment.priority >= 8:
                if current_tokens + segment.token_count <= max_tokens:
                    selected_segments.append(segment)
                    current_tokens += segment.token_count
                    logger.debug(f"Added high-priority segment: {segment.segment_type} ({segment.token_count} tokens)")
        
        # Second pass: Fill remaining space with other segments by priority
        remaining_segments = [s for s in sorted_segments if s.priority < 8 and s not in selected_segments]
        
        for segment in remaining_segments:
            if current_tokens + segment.token_count <= max_tokens:
                selected_segments.append(segment)
                current_tokens += segment.token_count
                logger.debug(f"Added segment: {segment.segment_type} ({segment.token_count} tokens)")
            else:
                # Try to truncate the segment if it's important
                if segment.priority >= 6:
                    available_tokens = max_tokens - current_tokens
                    if available_tokens > 100:  # Only truncate if we have meaningful space
                        truncated_content = self.token_counter.truncate_to_tokens(
                            segment.content, 
                            available_tokens, 
                            "\n\n[Content truncated due to token limits...]"
                        )
                        truncated_segment = ContextSegment(
                            content=truncated_content,
                            token_count=self.token_counter.count_tokens(truncated_content),
                            priority=segment.priority,
                            segment_type=segment.segment_type,
                            relevance_score=segment.relevance_score
                        )
                        selected_segments.append(truncated_segment)
                        current_tokens += truncated_segment.token_count
                        logger.debug(f"Added truncated segment: {segment.segment_type} ({truncated_segment.token_count} tokens)")
                        break
        
        # Build final context string in logical order
        context_parts = []
        
        # Group segments by type for better organization
        segment_groups = {}
        for segment in selected_segments:
            if segment.segment_type not in segment_groups:
                segment_groups[segment.segment_type] = []
            segment_groups[segment.segment_type].append(segment)
        
        # Add segments in logical order
        type_order = ['topic', 'queries', 'summary', 'results']
        for segment_type in type_order:
            if segment_type in segment_groups:
                for segment in segment_groups[segment_type]:
                    context_parts.append(segment.content)
        
        # Add any remaining segments
        for segment_type, segments in segment_groups.items():
            if segment_type not in type_order:
                for segment in segments:
                    context_parts.append(segment.content)
        
        final_context = "\n\n".join(context_parts)
        final_tokens = self.token_counter.count_tokens(final_context)
        
        logger.info(f"Built optimized context: {final_tokens}/{max_tokens} tokens ({len(selected_segments)} segments)")
        
        return final_context
    
    def get_fallback_context(self, research_topic: str, emergency_token_limit: int = 50000) -> str:
        """
        Get emergency fallback context when normal context building fails
        
        Args:
            research_topic: Research topic for context
            emergency_token_limit: Emergency token limit (much smaller)
            
        Returns:
            Minimal context string for emergency situations
        """
        # Create minimal context with just the topic and highest priority segments
        fallback_segments = []
        
        # Always include topic if available
        topic_segments = [s for s in self._planning_context if s.segment_type == "topic"]
        if topic_segments:
            fallback_segments.extend(topic_segments[:1])  # Just the first topic segment
        elif research_topic:
            # Create topic segment from research_topic if none exists
            fallback_segments.append(ContextSegment(
                content=f"Research Topic: {research_topic}",
                token_count=self.token_counter.count_tokens(f"Research Topic: {research_topic}"),
                priority=10,
                segment_type="topic"
            ))
        
        # Add only the highest priority segments that fit
        other_segments = [s for s in self._planning_context if s.segment_type != "topic"]
        other_segments.sort(key=lambda x: (x.priority, x.relevance_score), reverse=True)
        
        current_tokens = sum(s.token_count for s in fallback_segments)
        
        for segment in other_segments:
            if current_tokens + segment.token_count <= emergency_token_limit:
                fallback_segments.append(segment)
                current_tokens += segment.token_count
            else:
                # Try to include a truncated version if it's high priority
                if segment.priority >= 8:
                    available_tokens = emergency_token_limit - current_tokens
                    if available_tokens > 100:
                        truncated_content = self.token_counter.truncate_to_tokens(
                            segment.content, 
                            available_tokens - 50,  # Reserve some space
                            "...[truncated]"
                        )
                        fallback_segments.append(ContextSegment(
                            content=truncated_content,
                            token_count=self.token_counter.count_tokens(truncated_content),
                            priority=segment.priority,
                            segment_type=segment.segment_type,
                            relevance_score=segment.relevance_score
                        ))
                        break
        
        # Build fallback context
        context_parts = [segment.content for segment in fallback_segments]
        fallback_context = "\n\n".join(context_parts)
        
        final_tokens = self.token_counter.count_tokens(fallback_context)
        logger.warning(f"🚨 Using fallback context: {final_tokens}/{emergency_token_limit} tokens ({len(fallback_segments)} segments)")
        
        return fallback_context
    
    def handle_token_limit_error(self, research_topic: str, original_error: str) -> str:
        """
        Handle token limit errors by providing progressively smaller contexts
        
        Args:
            research_topic: Research topic for context
            original_error: Original error message
            
        Returns:
            Reduced context that should fit within limits
        """
        logger.error(f"💥 Token limit error encountered: {original_error}")
        
        # Try progressively smaller contexts
        retry_limits = [80000, 60000, 40000, 20000, 10000]
        
        for limit in retry_limits:
            try:
                reduced_context = self._build_optimized_context(self._planning_context, limit)
                context_tokens = self.token_counter.count_tokens(reduced_context)
                
                if context_tokens <= limit:
                    logger.warning(f"🔄 Reduced context to {context_tokens:,} tokens (limit: {limit:,})")
                    return reduced_context
                    
            except Exception as e:
                logger.warning(f"Failed to build context with limit {limit}: {e}")
                continue
        
        # If all else fails, use emergency fallback
        logger.error("🚨 All context reduction attempts failed, using emergency fallback")
        return self.get_fallback_context(research_topic, 10000)
    
    def create_research_summary(self, results: DeepResearchResults, max_tokens: int = 5000) -> str:
        """
        Create a condensed summary of research results for context optimization
        
        Args:
            results: DeepResearchResults to summarize
            max_tokens: Maximum tokens for the summary
            
        Returns:
            Condensed summary string
        """
        if not results.results:
            return "No research results available."
        
        # Extract key information from each result
        summaries = []
        for i, result in enumerate(results.results[:10]):  # Limit to top 10 results
            # Use summarized content if available, otherwise truncate content
            content = result.summarized_content or result.content or result.raw_content
            if content:
                # Truncate to reasonable size for summary
                truncated = self.token_counter.truncate_to_tokens(content, 300, "...")
                summary = f"[{i+1}] {result.title}\nURL: {result.link}\nContent: {truncated}\n"
                summaries.append(summary)
        
        full_summary = "\n".join(summaries)
        
        # Ensure the summary fits within token limits
        if self.token_counter.count_tokens(full_summary) > max_tokens:
            full_summary = self.token_counter.truncate_to_tokens(
                full_summary, 
                max_tokens, 
                "\n\n[Summary truncated due to length...]"
            )
        
        return full_summary
    
    def get_context_stats(self) -> Dict:
        """
        Get statistics about current context usage
        
        Returns:
            Dictionary with context statistics
        """
        planning_tokens = sum(seg.token_count for seg in self._planning_context)
        report_tokens = sum(seg.token_count for seg in self._report_context)
        
        return {
            'planning_context': {
                'segments': len(self._planning_context),
                'total_tokens': planning_tokens,
                'limit': self.planning_limit,
                'utilization': planning_tokens / self.planning_limit * 100
            },
            'report_context': {
                'segments': len(self._report_context),
                'total_tokens': report_tokens,
                'limit': self.report_limit,
                'utilization': report_tokens / self.report_limit * 100
            }
        }
    
    def clear_context(self, context_type: str = "both") -> None:
        """
        Clear context segments
        
        Args:
            context_type: Which context to clear ('planning', 'report', or 'both')
        """
        if context_type in ["planning", "both"]:
            self._planning_context.clear()
            logger.debug("Cleared planning context")
        
        if context_type in ["report", "both"]:
            self._report_context.clear()
            logger.debug("Cleared report context")

def create_token_manager(
    model_name: str = "meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8",
    config: dict = None
) -> Tuple[TokenCounter, ContextManager]:
    """
    Create a token counter and context manager for the specified model
    
    Args:
        model_name: Name of the model to optimize for
        config: Configuration dictionary with token management settings
        
    Returns:
        Tuple of (TokenCounter, ContextManager)
    """
    # Map model names to appropriate encodings
    model_encoding_map = {
        "meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8": "gpt-4",
        "meta-llama/Llama-3.3-70B-Instruct-Turbo": "gpt-4", 
        "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo": "gpt-4",
        "deepseek-ai/DeepSeek-R1": "gpt-4"
    }
    
    encoding_model = model_encoding_map.get(model_name, "gpt-4")
    token_counter = TokenCounter(encoding_model)
    
    # Use configuration values if provided, otherwise use defaults
    if config and 'token_management' in config:
        tm_config = config['token_management']
        planning_limit = tm_config.get('planning_token_limit', 100000)
        report_limit = tm_config.get('report_token_limit', 400000)
    else:
        # Fallback to default values if no config provided
        planning_limit = 100000
        report_limit = 400000
    
    context_manager = ContextManager(token_counter, planning_limit, report_limit)
    
    logger.info(f"Created token manager for model: {model_name} (encoding: {encoding_model})")
    logger.info(f"Token limits - Planning: {planning_limit:,}, Report: {report_limit:,}")
    
    return token_counter, context_manager