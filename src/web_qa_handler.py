"""
Web Q&A Handler for Interactive Research

This module provides a web-compatible version of the interactive Q&A functionality
that works with WebSocket communication instead of terminal input/output.

DESIGN PRINCIPLE: This is an isolated component that doesn't modify any existing 
functionality. It provides an alternative Q&A interface for web-based usage.
"""

import asyncio
import logging
from typing import List, Optional, Callable
from dataclasses import dataclass


@dataclass
class WebQAQuestion:
    """Represents a clarification question for web interface"""
    question: str
    options: List[str]
    default: str
    question_id: str


@dataclass 
class WebQAAnswer:
    """Represents a user's answer to a clarification question"""
    question_id: str
    selected_option: str


class WebQAHandler:
    """Asks the clarifying questions over WebSocket instead of terminal input()."""
    
    def __init__(self, websocket_callback: Callable = None, timeout: int = 300):
        """
        Initialize the WebQA Handler
        
        Args:
            websocket_callback: Function to send messages via WebSocket
            timeout: Timeout in seconds for waiting for user responses (default: 5 minutes)
        """
        self.websocket_callback = websocket_callback
        self.timeout = timeout
        self.pending_answers = {}
        self.logger = logging.getLogger(__name__)
        
    async def ask_clarifications_web(self, topic: str, clarification_data: dict) -> str:
        """
        WebSocket version of InteractiveDeepResearch._ask_clarifications
        
        Args:
            topic: Original research topic
            clarification_data: Dict containing questions and options
            
        Returns:
            str: Refined topic based on user answers
        """
        questions = clarification_data.get("questions", [])
        if not questions:
            return topic
            
        self.logger.info("🤔 Starting web-based interactive clarification...")
        
        # Send clarification start signal
        self.logger.debug("Sending clarification_start message")
        await self._send_websocket_message("clarification_start", {
            "reason": clarification_data.get("reason", ""),
            "topic": topic
        })
        self.logger.debug("clarification_start message sent")
        
        # Small delay to ensure WebSocket connection is fully established
        await asyncio.sleep(0.1)
        
        # Collect answers for all questions
        user_answers = {}
        total_questions = len(questions)  # Dynamic question count
        
        for i, question_data in enumerate(questions, 1):
            try:
                answer = await self._ask_single_question_web(i, question_data, total_questions)
                if answer is None:  # User didn't respond or timeout
                    self.logger.warning(f"No response for question {i}, using default")
                    answer = question_data.get("default", question_data["options"][0])
                user_answers[i] = answer
            except Exception as e:
                self.logger.error(f"Error asking question {i}: {e}")
                # Use default if error occurs
                user_answers[i] = question_data.get("default", question_data["options"][0])
        
        if not user_answers:
            return topic
            
        # Refine topic with answers (reuse existing logic structure)
        refined_topic = self._refine_topic_with_answers_web(topic, questions, user_answers)
        
        # Send clarification complete signal
        await self._send_websocket_message("clarification_complete", {
            "original_topic": topic,
            "refined_topic": refined_topic,
            "answers": user_answers
        })
        
        self.logger.info(f"✅ Topic refined via web Q&A: {refined_topic}")
        return refined_topic
    
    async def _ask_single_question_web(self, question_num: int, question_data: dict, total_questions: int) -> Optional[str]:
        """
        Web-compatible version of _ask_single_question using WebSocket
        
        Args:
            question_num: Question number
            question_data: Dict containing question and options
            total_questions: Total number of questions for progress tracking
            
        Returns:
            str: Selected answer or None if timeout/error
        """
        question_id = f"q_{question_num}_{id(question_data)}"
        
        # Prepare question for web interface
        web_question = WebQAQuestion(
            question=question_data["question"],
            options=question_data["options"],
            default=question_data.get("default", question_data["options"][0]),
            question_id=question_id
        )
        
        # Small delay to ensure WebSocket is ready for this question
        await asyncio.sleep(0.1)
        
        # Send question via WebSocket
        self.logger.debug(f"Sending clarification_question {question_num}/{total_questions} via WebSocket")
        await self._send_websocket_message("clarification_question", {
            "question_id": question_id,
            "question_num": question_num,
            "question": web_question.question,
            "options": web_question.options,
            "default": web_question.default,
            "total_questions": total_questions
        })
        self.logger.debug(f"Sent clarification_question {question_num}")
        
        # Wait for answer
        try:
            answer = await asyncio.wait_for(
                self._wait_for_answer(question_id), 
                timeout=self.timeout
            )
            return answer
        except asyncio.TimeoutError:
            self.logger.warning(f"Timeout waiting for answer to question {question_num}")
            return None
        except Exception as e:
            self.logger.error(f"Error waiting for answer: {e}")
            return None
    
    async def _wait_for_answer(self, question_id: str) -> str:
        """
        Wait for answer from WebSocket
        
        Args:
            question_id: ID of the question to wait for
            
        Returns:
            str: The selected answer
        """
        # Create future for this question
        future = asyncio.Future()
        self.pending_answers[question_id] = future
        
        try:
            # Wait for the answer
            answer = await future
            return answer
        finally:
            # Clean up
            self.pending_answers.pop(question_id, None)
    
    def receive_answer(self, question_id: str, selected_option: str):
        """
        Receive answer from WebSocket (called by WebSocket handler)
        
        Args:
            question_id: ID of the question
            selected_option: User's selected answer
        """
        if question_id in self.pending_answers:
            future = self.pending_answers[question_id]
            if not future.done():
                future.set_result(selected_option)
                self.logger.info(f"✅ Received answer for {question_id}: {selected_option}")
    
    def _refine_topic_with_answers_web(self, original_topic: str, questions: list, answers: dict) -> str:
        """
        Append the answers to the topic ("<topic> - focusing on A, focusing on B").
        Unlike the terminal version, this makes no LLM call.
        
        Args:
            original_topic: Original research topic
            questions: List of question data
            answers: Dict of user answers
            
        Returns:
            str: Refined topic
        """
        # Build refined topic by incorporating answers
        topic_parts = [original_topic]
        
        for i, answer in answers.items():
            if answer and answer.strip():
                # Add contextual information based on the answer
                if "all aspects" not in answer.lower():
                    topic_parts.append(f"focusing on {answer}")
        
        # Create refined topic
        if len(topic_parts) > 1:
            refined_topic = f"{topic_parts[0]} - {', '.join(topic_parts[1:])}"
        else:
            refined_topic = original_topic
            
        return refined_topic
    
    async def _send_websocket_message(self, message_type: str, data: dict, retry_count: int = 3):
        """
        Send message via WebSocket with retry mechanism
        
        Args:
            message_type: Type of message
            data: Message data
            retry_count: Number of retries if WebSocket not ready
        """
        self.logger.debug(f"_send_websocket_message called with type: {message_type}")
        
        if not self.websocket_callback:
            self.logger.warning("No WebSocket callback available for sending message")
            return
            
        for attempt in range(retry_count):
            try:
                message = {
                    "type": message_type,
                    "data": data
                }
                self.logger.debug(f"Attempt {attempt + 1} - Calling websocket_callback with message: {message}")
                
                if asyncio.iscoroutinefunction(self.websocket_callback):
                    await self.websocket_callback(message)
                else:
                    self.websocket_callback(message)
                
                self.logger.debug(f"websocket_callback completed successfully on attempt {attempt + 1}")
                return  # Success, exit retry loop
                    
            except Exception as e:
                self.logger.error(f"Error sending WebSocket message (attempt {attempt + 1}): {e}")
                if attempt < retry_count - 1:
                    # Wait before retrying, with exponential backoff
                    wait_time = 0.1 * (2 ** attempt)
                    self.logger.debug(f"Retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                else:
                    self.logger.error(f"Failed to send WebSocket message after {retry_count} attempts")
                    raise


def create_web_qa_handler(websocket_callback: Callable = None, timeout: int = 300) -> WebQAHandler:
    """
    Factory function to create WebQAHandler instance
    
    Args:
        websocket_callback: Function to send WebSocket messages
        timeout: Timeout for user responses in seconds
        
    Returns:
        WebQAHandler: Configured handler instance
    """
    return WebQAHandler(websocket_callback=websocket_callback, timeout=timeout)