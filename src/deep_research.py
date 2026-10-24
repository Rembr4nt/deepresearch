import asyncio
import json
import logging
import os
import re
import yaml
from pathlib import Path
from typing import List

from dotenv import load_dotenv

from .data_types import ResearchPlan, DeepResearchResult, DeepResearchResults
from .tavily_search import tavily_search, tavily_search_async
from .utils import llm_call, llm_rerank, remove_thinking_tags, llm_call_async
from .token_management import create_token_manager

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = str(ROOT_DIR / "config" / "config.yaml")
PROMPTS_PATH = ROOT_DIR / "config" / "prompts.yaml"

load_dotenv()

class DeepResearchError(Exception):
    """Base exception class for Deep Research errors"""
    pass

class APIError(DeepResearchError):
    """Exception raised for API-related errors"""
    pass

class ValidationError(DeepResearchError):
    """Exception raised for input validation errors"""
    pass

class ConfigurationError(DeepResearchError):
    """Exception raised for configuration issues"""
    pass

def setup_logging(level: str = "INFO") -> logging.Logger:
    """Setup logging configuration"""
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('deep_research.log')
        ]
    )
    return logging.getLogger(__name__)

def validate_research_topic(topic: str) -> str:
    """Comprehensive validation and sanitization of research topic"""
    # Type and basic validation
    if not topic or not isinstance(topic, str):
        raise ValidationError("Research topic must be a non-empty string")
    
    # Normalize whitespace and strip
    topic = re.sub(r'\s+', ' ', topic).strip()
    
    # Length validation
    if len(topic) < 3:
        raise ValidationError("Research topic must be at least 3 characters long")
    
    if len(topic) > 1000:
        raise ValidationError("Research topic is too long (maximum 1000 characters)")
    
    # Security validation - detect common injection patterns
    if _contains_potential_injection(topic):
        raise ValidationError("Research topic contains potentially harmful content")
    
    # Content quality validation
    if not _is_meaningful_research_topic(topic):
        raise ValidationError("Research topic must contain meaningful content")
    
    # Sanitize while preserving research-relevant punctuation
    topic = _sanitize_research_topic(topic)
    
    if not topic:
        raise ValidationError("Research topic contains only invalid characters")
    
    return topic

def _contains_potential_injection(topic: str) -> bool:
    """Reject markup or template syntax in a topic. Plain words like "update" or
    "system" are allowed: the topic only goes into prompts and a sanitized file name."""
    injection_patterns = [
        r'<script.*?>.*?</script>',  # XSS
        r'javascript:',              # JavaScript injection
        r'data:.*?base64',          # Data URI with base64
        r'<!--.*?-->',              # HTML comments
        r'{{.*?}}',                 # Template injection
        r'{%.*?%}',                 # Template injection
        r'\$\{.*?\}',              # Variable injection
    ]
    
    topic_lower = topic.lower()
    return any(re.search(pattern, topic_lower, re.IGNORECASE | re.DOTALL) 
               for pattern in injection_patterns)

def _is_meaningful_research_topic(topic: str) -> bool:
    """Check if topic contains meaningful research content"""
    # Remove punctuation and check if there are actual words
    words = re.findall(r'\b[a-zA-Z]{2,}\b', topic)
    
    # Must have at least 2 meaningful words
    if len(words) < 2:
        return False
    
    # Check for excessive repetition of single characters or words
    if len(set(topic.lower().replace(' ', ''))) < 3:  # Too repetitive
        return False
    
    # Check for spam-like patterns (excessive punctuation)
    if len(re.findall(r'[!@#$%^&*()_+={}|:"<>?`~]', topic)) > len(topic) * 0.3:
        return False
    
    return True

def _sanitize_research_topic(topic: str) -> str:
    """Sanitize topic while preserving research-relevant content"""
    # Remove dangerous characters but preserve research punctuation
    # Keep: letters, numbers, spaces, basic punctuation for research
    sanitized = re.sub(r'[<>\"\'&;]', '', topic)
    
    # Normalize excessive punctuation
    sanitized = re.sub(r'[!]{3,}', '!', sanitized)
    sanitized = re.sub(r'[?]{3,}', '?', sanitized)
    sanitized = re.sub(r'[.]{4,}', '...', sanitized)
    
    # Clean up extra whitespace
    sanitized = re.sub(r'\s+', ' ', sanitized).strip()
    
    return sanitized

def validate_api_keys():
    """Comprehensive validation of required API keys"""
    required_keys = ['TOGETHER_API_KEY', 'VOYAGE_API_KEY', 'TAVILY_API_KEY']
    missing_keys = []
    invalid_keys = []
    
    for key in required_keys:
        value = os.getenv(key)
        if not value:
            missing_keys.append(key)
        elif not _is_valid_api_key_format(key, value):
            invalid_keys.append(key)
    
    if missing_keys:
        raise ConfigurationError(f"Missing required API keys: {', '.join(missing_keys)}")
    
    if invalid_keys:
        raise ConfigurationError(f"Invalid format for API keys: {', '.join(invalid_keys)}")
    
    return True

def _is_valid_api_key_format(key_name: str, key_value: str) -> bool:
    """Validate API key format without exposing the actual key"""
    # Basic format validation without revealing the key
    if len(key_value.strip()) < 10:  # Too short to be a real API key
        return False
    
    # Check for placeholder values that users might forget to replace
    placeholder_patterns = [
        'your_api_key_here', 'replace_with_actual_key', 'api_key_placeholder',
        'changeme', 'placeholder', 'dummy_key', 'test_key', 'fake_key'
    ]
    
    if key_value.lower().strip() in placeholder_patterns:
        return False
    
    # Basic character validation - API keys usually contain alphanumeric and some symbols
    if not re.match(r'^[a-zA-Z0-9\-_.]+$', key_value):
        return False
    
    return True

class ResearchConfig:
    """Configuration management for Deep Research system"""
    
    def __init__(self, config_path: str = CONFIG_PATH):
        self.config_path = config_path
        self._config = self._load_config()
    
    def _load_config(self) -> dict:
        """Load configuration from YAML file"""
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r') as f:
                    config = yaml.safe_load(f) or {}
            else:
                config = {}
        except Exception as e:
            raise ConfigurationError(f"Failed to load config from {self.config_path}: {e}")
        
        # Set defaults if not present
        defaults = {
            'research': {
                'max_queries': 5,
                'max_searchs': 5,
                'max_iteration': 5,
                'rerank_score_threshold': 0.5,
                'max_completion_token': 4096,
                'interactive': True,
                'remove_thinking_token': False
            },
            'models': {
                'planning_model': "meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8",
                'summarization_model': "meta-llama/Llama-3.3-70B-Instruct-Turbo",
                'json_model': "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
                'answer_model': "deepseek-ai/DeepSeek-R1"
            },
            'logging': {
                'level': 'INFO'
            },
            'token_management': {
                'planning_token_limit': 100000,
                'report_token_limit': 400000
            }
        }
        
        # Merge defaults with loaded config
        for section, section_defaults in defaults.items():
            if section not in config:
                config[section] = {}
            for key, value in section_defaults.items():
                if key not in config[section]:
                    config[section][key] = value
        
        return config
    
    def get(self, section: str, key: str = None, default=None):
        """Get configuration value"""
        if key is None:
            return self._config.get(section, default)
        return self._config.get(section, {}).get(key, default)
    
    def override_from_env(self):
        """Override config values from environment variables"""
        env_mappings = {
            'PLANNING_MODEL': ('models', 'planning_model'),
            'SUMMARIZATION_MODEL': ('models', 'summarization_model'),
            'JSON_MODEL': ('models', 'json_model'),
            'ANSWER_MODEL': ('models', 'answer_model'),
            'LOG_LEVEL': ('logging', 'level'),
            'MAX_QUERIES': ('research', 'max_queries'),
            'MAX_ITERATIONS': ('research', 'max_iteration'),
        }
        
        for env_var, (section, key) in env_mappings.items():
            value = os.getenv(env_var)
            if value is not None:
                if section not in self._config:
                    self._config[section] = {}
                # Convert numeric values
                if key in ['max_queries', 'max_iteration', 'max_searchs']:
                    try:
                        value = int(value)
                    except ValueError:
                        continue
                elif key == 'rerank_score_threshold':
                    try:
                        value = float(value)
                    except ValueError:
                        continue
                self._config[section][key] = value

class InteractiveDeepResearch:
    def __init__(
        self,
        config_path: str = CONFIG_PATH,
        max_queries: int = None,
        max_searchs: int = None,
        max_iteration: int = None,
        rerank_score_threshold: float = None,
        remove_thinking_token: bool = None,
        max_completion_token: int = None,
        planning_model: str = None,
        summarization_model: str = None,
        json_model: str = None,
        answer_model: str = None,
        interactive: bool = None,
        use_async: bool = None,
        log_level: str = None,
        progress_callback: callable = None,
    ):
        # Load configuration
        self.config = ResearchConfig(config_path)
        self.config.override_from_env()
        
        # Set parameters (explicit parameters override config)
        self.max_queries = max_queries or self.config.get('research', 'max_queries')
        self.max_searchs = max_searchs or self.config.get('research', 'max_searchs')
        self.max_iteration = max_iteration or self.config.get('research', 'max_iteration')
        self.rerank_score_threshold = rerank_score_threshold or self.config.get('research', 'rerank_score_threshold')
        self.remove_thinking_token = remove_thinking_token if remove_thinking_token is not None else self.config.get('research', 'remove_thinking_token')
        self.max_completion_token = max_completion_token or self.config.get('research', 'max_completion_token')
        self.planning_model = planning_model or self.config.get('models', 'planning_model')
        self.summarization_model = summarization_model or self.config.get('models', 'summarization_model')
        self.json_model = json_model or self.config.get('models', 'json_model')
        self.answer_model = answer_model or self.config.get('models', 'answer_model')
        self.interactive = interactive if interactive is not None else self.config.get('research', 'interactive')
        self.use_async = use_async if use_async is not None else self.config.get('research', 'use_async', default=True)  # Default to async for better performance
        
        # Setup logging
        log_level = log_level or self.config.get('logging', 'level')
        self.logger = setup_logging(log_level)
        
        # Progress callback for real-time updates
        self.progress_callback = progress_callback
        
        # Backend progress deduplication state
        self._last_emitted_progress = -1
        self._last_progress_time = 0
        self._progress_min_increment = 0.01  # Minimum 1% change to emit
        self._progress_min_interval = 0.05   # Minimum 50ms between emissions
        
        # Track last known details for consistent emission
        self._last_known_details = {
            'iteration': None,
            'results': None,
            'topic': None
        }
        
        # Validate API keys on initialization
        try:
            validate_api_keys()
            self.logger.info("✅ API keys validated successfully")
        except ConfigurationError as e:
            self.logger.error(f"❌ API validation failed: {e}")
            raise

        with open(PROMPTS_PATH, "r", encoding="utf-8") as f:
            self.prompts = yaml.safe_load(f)
        
        # Initialize token management system with configuration
        self.token_counter, self.context_manager = create_token_manager(
            self.planning_model, 
            self.config._config
        )
        self.logger.info(f"✅ Token management system initialized for model: {self.planning_model}")
    
    async def _emit_progress(self, stage: str, progress: float, message: str, details: dict = None):
        """Emit progress update if callback is available with backend deduplication"""
        if not self.progress_callback:
            return
        
        # Validate progress bounds to prevent display issues
        if progress < 0.0:
            self.logger.warning(f"Progress validation: progress {progress:.3f} is negative, clamping to 0.0")
            progress = 0.0
        elif progress > 1.0:
            self.logger.warning(f"Progress validation: progress {progress:.3f} exceeds 100%, clamping to 1.0")
            progress = 1.0
        
        # Log progress for debugging if needed
        if progress > 0.9:  # Log high progress values for debugging
            self.logger.debug(f"Progress debug: stage={stage}, progress={progress:.3f} ({progress*100:.1f}%), message={message[:50]}...")
            
        import time
        current_time = time.time()
        
        # Update last known details with any new information
        if details:
            # Update persistent detail tracking
            if 'iteration' in details and details['iteration'] is not None:
                self._last_known_details['iteration'] = details['iteration']
            if 'current_iteration' in details and details['current_iteration'] is not None:
                self._last_known_details['iteration'] = details['current_iteration']
            if 'results_found' in details and details['results_found'] is not None:
                self._last_known_details['results'] = details['results_found']
            if 'total_results' in details and details['total_results'] is not None:
                self._last_known_details['results'] = details['total_results']
            if 'filtered_results' in details and details['filtered_results'] is not None:
                self._last_known_details['results'] = details['filtered_results']
            if 'topic' in details and details['topic'] is not None:
                self._last_known_details['topic'] = details['topic']
        
        # Backend deduplication to reduce glitchy progress updates
        # Skip emission if:
        # 1. Progress change is too small (less than 1%)
        # 2. Time interval is too short (less than 50ms)
        # 3. Progress value hasn't changed significantly
        
        progress_delta = abs(progress - self._last_emitted_progress)
        time_delta = current_time - self._last_progress_time
        
        # Always emit for stage changes, completion (100%), or significant progress changes
        should_emit = (
            stage != getattr(self, '_last_stage', '') or  # Stage changed
            progress >= 1.0 or  # Completion (100%)
            progress_delta >= self._progress_min_increment or  # Significant progress change
            time_delta >= 0.5 or  # Force emit every 500ms regardless
            progress == 0.0  # Always emit initialization
        )
        
        # Additional check: don't emit if too frequent and change is minimal
        if not should_emit and time_delta < self._progress_min_interval:
            return
            
        # Update tracking variables
        self._last_emitted_progress = progress
        self._last_progress_time = current_time
        self._last_stage = stage
        
        # Always include last known details in emission
        merged_details = {}
        if details:
            merged_details.update(details)
        
        # Add persistent details if they exist and aren't already in the details
        if self._last_known_details['iteration'] is not None and 'iteration' not in merged_details and 'current_iteration' not in merged_details:
            merged_details['iteration'] = self._last_known_details['iteration']
        if self._last_known_details['results'] is not None and 'results_found' not in merged_details and 'total_results' not in merged_details:
            merged_details['results_found'] = self._last_known_details['results']
        if self._last_known_details['topic'] is not None and 'topic' not in merged_details:
            merged_details['topic'] = self._last_known_details['topic']
        
        progress_data = {
            'stage': stage,
            'progress': progress,
            'message': message,
            'details': merged_details
        }
        
        try:
            if asyncio.iscoroutinefunction(self.progress_callback):
                await self.progress_callback(progress_data)
            else:
                self.progress_callback(progress_data)
        except Exception as e:
            self.logger.warning(f"Progress callback failed: {e}")

    def __call__(self, topic: str) -> str:
        """Main entry point - automatically chooses async version if use_async=True for better performance"""
        if self.use_async:
            # Run the async version using asyncio.run for convenience
            return asyncio.run(self.async_call(topic))
        else:
            return self.sync_call(topic)

    def sync_call(self, topic: str) -> str:
        """Synchronous version (use_async: false)"""
        # Validate and sanitize input topic
        try:
            topic = validate_research_topic(topic)
        except ValidationError as e:
            self.logger.error(f"❌ Topic validation failed: {e}")
            raise
            
        if self.interactive:
            return self.interactive_deep_research(topic)
        else:
            return self.topic_deep_research(topic)

    async def async_call(self, topic: str) -> str:
        """Async version with parallel processing for better performance"""
        # Validate and sanitize input topic
        try:
            topic = validate_research_topic(topic)
        except ValidationError as e:
            self.logger.error(f"❌ Topic validation failed: {e}")
            raise
            
        if self.interactive:
            return await self.interactive_deep_research_async(topic)
        else:
            return await self.topic_deep_research_async(topic)
    
    def interactive_deep_research(self, topic: str) -> str:
        """Interactive research with clarification questions"""
        
        self.logger.info("🤔 Analyzing topic for clarification needs...")
        
        # Step 1: Check if clarification needed
        clarification_data = self._analyze_clarification_needs(topic)
        
        if clarification_data.get("needs_clarification", False):
            self.logger.info(f"💡 Clarification needed: {clarification_data.get('reason')}")
            refined_topic = self._ask_clarifications(topic, clarification_data)
            self.logger.info(f"✅ Topic refined: {refined_topic}")
        else:
            self.logger.info("✅ Topic is clear enough, proceeding with research")
            refined_topic = topic
        
        # Step 2: Proceed with deep research using refined topic
        return self.topic_deep_research(refined_topic)

    async def interactive_deep_research_async(self, topic: str) -> str:
        """Async research with clarification questions asked in the terminal.

        The web UI asks its questions over WebSocket instead
        (research_manager._run_interactive_web_research) and never reaches this method.
        """
        
        self.logger.info("🤔 Analyzing topic for clarification needs...")
        
        # Step 1: Check if clarification needed
        clarification_data = self._analyze_clarification_needs(topic)
        
        if clarification_data.get("needs_clarification", False):
            self.logger.info(f"💡 Clarification needed: {clarification_data.get('reason')}")
            refined_topic = self._ask_clarifications(topic, clarification_data)
            self.logger.info(f"✅ Topic refined: {refined_topic}")
        else:
            self.logger.info("✅ Topic is clear enough, proceeding with research")
            refined_topic = topic
        
        # Step 2: Proceed with async deep research using refined topic
        return await self.topic_deep_research_async(refined_topic)
    
    def _analyze_clarification_needs(self, topic: str) -> dict:
        """Analyze if topic needs clarification questions"""
        try:
            clarification_prompt = self._get_clarification_prompt()
            
            # If user explicitly enabled interactive mode, ensure questions are generated
            if self.interactive:
                clarification_prompt += "\n\nCRITICAL: The user has explicitly enabled Interactive Mode, which means they WANT clarification questions regardless of topic specificity. You MUST generate 2-3 relevant questions to refine the research focus and approach. Set needs_clarification to true and provide questions."
            
            response = self._call_clarification_analysis(topic, clarification_prompt)
            return self._parse_clarification_response(response)
            
        except Exception as e:
            self.logger.error(f"❌ Error analyzing clarification needs: {e}")
            return {"needs_clarification": False, "questions": []}
    
    def _get_clarification_prompt(self) -> str:
        """Get the prompt for clarification needs analysis"""
        return """
Analyze the user's research request. Determine if there are ambiguous aspects that would benefit from clarification to improve research quality.

Common areas that often need clarification (adapt based on topic):
1. Time horizon/scope (recent, current, future, historical)
2. Depth and detail level (overview vs comprehensive analysis)
3. Geographic/regional focus (global, specific countries/regions)
4. Target audience or perspective (academic, business, general public)
5. Specific aspects to focus on within the broad topic
6. Preferred approach or methodology
7. Comparison or standalone analysis

Analyze what type of research this is (business, academic, technical, health, social, etc.) and generate relevant questions accordingly.

If clarification would significantly improve the research quality and focus, generate 2-4 targeted questions.
If the topic is specific enough, return empty questions array.

Output format:
{
  "needs_clarification": true/false,
  "reason": "Brief explanation of why clarification would help",
  "questions": [
    {
      "question": "Clear, direct question relevant to the topic",
      "options": ["Option 1", "Option 2", "Option 3", "Option 4"],
      "default": "Most common/reasonable default"
    }
  ]
}

Examples across different domains:

Input: "Impact of AI on healthcare"
Output: {"needs_clarification": true, "reason": "Scope and focus area unclear", "questions": [{"question": "Which aspect of AI impact interests you most?", "options": ["Patient care and diagnosis", "Healthcare operations", "Medical research", "All aspects"], "default": "All aspects"}]}

Input: "Climate change effects in Southeast Asia with economic impact analysis"
Output: {"needs_clarification": false, "reason": "Scope and approach are clearly defined", "questions": []}

Input: "Marketing strategies for small businesses"
Output: {"needs_clarification": true, "reason": "Industry and business type not specified", "questions": [{"question": "What type of small business?", "options": ["Retail/E-commerce", "Services", "Technology", "General strategies"], "default": "General strategies"}]}

Only generate questions that would significantly change the research approach or improve the quality.
IMPORTANT: Respond ONLY with valid JSON, no additional text or explanations.
"""
    
    def _call_clarification_analysis(self, topic: str, prompt: str) -> str:
        """Make the API call for clarification analysis"""
        return llm_call(
            model=self.planning_model,
            system_prompt=prompt,
            message=f"User Research Request: {topic}",
            response_format={"type": "json_object"}
        )
    
    def _parse_clarification_response(self, response: str) -> dict:
        """Parse and validate the clarification analysis response"""
        try:
            parsed_data = json.loads(response)
            
            # Validate required fields
            if "needs_clarification" not in parsed_data:
                parsed_data["needs_clarification"] = False
            
            if "questions" not in parsed_data:
                parsed_data["questions"] = []
                
            if "reason" not in parsed_data:
                parsed_data["reason"] = "No clarification needed"
            
            return parsed_data
        except json.JSONDecodeError:
            return {"needs_clarification": False, "questions": [], "reason": "Invalid response format"}
    
    def _ask_clarifications(self, topic: str, clarification_data: dict) -> str:
        """Ask clarification questions to user"""
        questions = clarification_data.get("questions", [])
        if not questions:
            return topic
        
        self._display_clarification_header()
        user_answers = self._collect_user_answers(questions)
        
        if not user_answers:  # User interrupted
            return topic
            
        refined_topic = self._refine_topic_with_answers(topic, questions, user_answers)
        self._display_refinement_confirmation(refined_topic)
        
        return refined_topic
    
    def _display_clarification_header(self) -> None:
        """Display the clarification questions header"""
        print(f"\n{'='*60}")
        print("🤔 To provide the best research, I have a few questions:")
        print(f"{'='*60}")
    
    def _collect_user_answers(self, questions: list) -> dict:
        """Collect answers from user for all clarification questions"""
        user_answers = {}
        
        for i, question in enumerate(questions, 1):
            try:
                answer = self._ask_single_question(i, question)
                if answer is None:  # User interrupted
                    return {}
                user_answers[i] = answer
            except KeyboardInterrupt:
                print("\n\n❌ Process interrupted by user")
                return {}
        
        return user_answers
    
    def _ask_single_question(self, question_num: int, question_data: dict) -> str:
        """Ask a single clarification question and get user response"""
        print(f"\n{question_num}. {question_data['question']}")
        
        if 'options' in question_data:
            return self._ask_multiple_choice_question(question_data)
        else:
            return self._ask_free_text_question()
    
    def _ask_multiple_choice_question(self, question_data: dict) -> str:
        """Handle multiple choice question"""
        options = question_data['options']
        
        # Display options
        for j, option in enumerate(options, 1):
            print(f"   {j}. {option}")
        
        # Get user choice
        while True:
            try:
                choice = input(f"\nYour choice (1-{len(options)}): ").strip()
                choice_idx = int(choice) - 1
                if 0 <= choice_idx < len(options):
                    return options[choice_idx]
                else:
                    print("Invalid choice. Please try again.")
            except ValueError:
                print("Please enter a number.")
            except KeyboardInterrupt:
                return None
    
    def _ask_free_text_question(self) -> str:
        """Handle free text question"""
        try:
            return input("Your answer: ").strip()
        except KeyboardInterrupt:
            return None
    
    def _display_refinement_confirmation(self, refined_topic: str) -> None:
        """Display confirmation of the refined topic"""
        print(f"\n✅ Perfect! I'll research: {refined_topic}")
        print(f"{'='*60}\n")
    
    def _refine_topic_with_answers(self, original_topic: str, questions: list, answers: dict) -> str:
        """Refine topic with user clarification answers"""
        
        refine_prompt = """
Refine the original research topic by incorporating the user's clarification answers.

Create a comprehensive, specific research topic that:
1. Maintains the original intent
2. Includes all clarification details
3. Is clear and actionable for research
4. Preserves the user's original question style and urgency

Return only the refined topic, nothing else.
"""
        
        # Format context
        context = f"Original Topic: {original_topic}\n\nClarifications:\n"
        for i, (q_num, answer) in enumerate(answers.items()):
            question = questions[q_num - 1]['question']
            context += f"- {question}: {answer}\n"
        
        try:
            response = llm_call(
                model=self.planning_model,
                system_prompt=refine_prompt,
                message=context,
                max_completion_tokens=500
            )
            
            return response.strip()
            
        except Exception as e:
            self.logger.error(f"❌ Error refining topic: {e}")
            return original_topic

    def topic_deep_research(self, topic: str) -> str:
        self.logger.info(f"🔬 Initiate Topic Research")
        queries = self.generate_research_queries(topic)
        all_queries = [topic] + queries
        self.logger.info(f"📋 Research Iteration Number {1}")
        self.logger.info("🔍 Generate Initial Research Query. Found:\n{query}".format(query='\n'.join(all_queries)))
    
        for iteration in range(self.max_iteration):
            if iteration == 0:
                results = self.search_all_queries(all_queries)
                continue
            self.logger.info(f"📋 Research Iteration Number {iteration+1}")
        
            additional_queries = self.evaluate_research_completeness(topic, results, all_queries)
            
            additional_queries = [q for q in additional_queries if q]
            additional_queries = list(set(additional_queries) - set(all_queries))
            if not additional_queries:
                self.logger.info(f"✅ No Additional Research Query Needed")
                break
            self.logger.info("🔍 Additional Research Query Discovered:\n{query}".format(query='\n'.join(additional_queries)))
        
            new_results = self.search_all_queries(additional_queries)
        
            results = results + new_results
            all_queries.extend(additional_queries)

        self.logger.info(f"📊 Data Research Completed, Found {len(results.results)} Research Information")
        filtered_results = self.filter_results_with_rerank(topic, results)
        self.logger.info(f"🔽 Filtering Research Information With Rerank Relevance Score Threshold of {self.rerank_score_threshold}, Retrieved {len(filtered_results.results)} Research Information")

        self.logger.info(f"📝 Generate Research Report")
        report = self.generate_research_answer(topic, filtered_results)
    
        return report

    async def _check_cancellation(self, operation_name: str = "operation") -> None:
        """Check for task cancellation and raise CancelledError if cancelled"""
        try:
            await asyncio.sleep(0.001)  # yield so a pending cancel is raised here
        except asyncio.CancelledError:
            self.logger.info(f"🛑 Research cancelled during {operation_name}")
            raise

    async def topic_deep_research_async(self, topic: str) -> str:
        """Async version of topic_deep_research with parallel search processing"""
        self.logger.info(f"🔬 Initiate Async Topic Research")
        
        # Iteration-based progress allocation for clear "X/Y iteration" display
        # Each iteration gets equal weight, with sub-progress for stages within iterations
        
        # Calculate progress allocation per iteration
        iteration_weight = 0.85 / self.max_iteration if self.max_iteration > 0 else 0.85  # 85% for all iterations
        query_generation_weight = 0.05   # 5% for initial query generation
        
        # Define sub-stages within each iteration (for sub-progress display)
        iteration_substages = {
            'search': 0.4,          # 40% of iteration progress
            'evaluation': 0.3,      # 30% of iteration progress  
            'additional_search': 0.3 # 30% of iteration progress
        }
        
        # Helper function to calculate iteration progress
        def get_iteration_progress(iteration_num, substage_name=None, substage_progress=0.0):
            """Calculate progress based on iteration number and optional substage"""
            # Base progress from completed iterations
            base_progress = query_generation_weight + (iteration_num - 1) * iteration_weight
            
            if substage_name and substage_name in iteration_substages:
                # Add progress within current iteration
                substage_weight = iteration_substages[substage_name]
                base_progress += substage_weight * substage_progress * iteration_weight
            
            return min(base_progress, 0.95)  # Cap at 95% to leave room for report generation
        
        # Stage 1: Query Generation
        await self._emit_progress("query_generation", query_generation_weight * 0.2, "Analyzing research topic...", {
            "topic": topic,
            "current_iteration": 0,
            "total_iterations": self.max_iteration,
            "stage": "analysis"
        })
        await self._emit_progress("query_generation", query_generation_weight * 0.6, "Generating research queries...", {
            "topic": topic,
            "current_iteration": 0,
            "total_iterations": self.max_iteration,
            "stage": "generation"
        })
        queries = self.generate_research_queries(topic)
        all_queries = [topic] + queries
        self.logger.info(f"📋 Research Iteration Number {1}")
        self.logger.info("🔍 Generate Initial Research Query. Found:\n{query}".format(query='\n'.join(all_queries)))
        await self._emit_progress("query_generation", query_generation_weight, f"Generated {len(queries)} strategic research queries", {
            "queries_generated": len(queries), 
            "queries_count": len(all_queries),
            "total_queries": len(all_queries),
            "current_iteration": 0,
            "total_iterations": self.max_iteration,
            "stage": "complete"
        })
        
        # Track iterations completed for adaptive progress
        completed_iterations = 0
        results = None
        
        for iteration in range(self.max_iteration):
            # Check for cancellation at start of each iteration
            await self._check_cancellation(f"iteration {iteration+1}")
            
            current_iteration = iteration + 1
            
            if iteration == 0:
                # FIRST ITERATION - Initial search
                iteration_start_progress = get_iteration_progress(current_iteration)
                
                await self._emit_progress("search", iteration_start_progress, f"Conducting initial search with {len(all_queries)} queries... (Iteration {current_iteration}/{self.max_iteration})", {
                    "current_iteration": current_iteration,
                    "total_iterations": self.max_iteration,
                    "queries_count": len(all_queries),
                    "total_queries": len(all_queries),
                    "iteration_progress": 0.0,
                    "substage": "search_start"
                })
                
                # Calculate search progress for this iteration
                search_start_progress = iteration_start_progress
                search_end_progress = get_iteration_progress(current_iteration, "search", 1.0)
                
                results = await self.search_all_queries_async(
                    all_queries, "search", search_start_progress, search_end_progress - search_start_progress, 
                    current_iteration, self.max_iteration
                )
                
                completed_iterations += 1
                
                # Update progress to show first iteration search completion
                await self._emit_progress("search", search_end_progress, f"Initial search completed (Iteration {current_iteration}/{self.max_iteration})", {
                    "current_iteration": current_iteration,
                    "total_iterations": self.max_iteration,
                    "queries_count": len(all_queries),
                    "total_queries": len(all_queries),
                    "iteration_progress": 0.4,
                    "substage": "search_complete"
                })
                continue
                
            # ADDITIONAL ITERATIONS (2+) - Each iteration gets equal weight
            self.logger.info(f"📋 Research Iteration Number {current_iteration}")
            
            # Stage 3: Evaluation and Additional Search
            await self._check_cancellation(f"evaluation phase - iteration {current_iteration}")
            
            # Calculate evaluation progress for this iteration
            evaluation_start_progress = get_iteration_progress(current_iteration, "evaluation", 0.0)
            evaluation_end_progress = get_iteration_progress(current_iteration, "evaluation", 1.0)
            
            await self._emit_progress("evaluation", evaluation_start_progress, f"Evaluating research completeness... (Iteration {current_iteration}/{self.max_iteration})", {
                "current_iteration": current_iteration,
                "total_iterations": self.max_iteration,
                "current_results": len(results.results),
                "queries_count": len(all_queries),
                "total_queries": len(all_queries),
                "iteration_progress": 0.4,
                "substage": "evaluation_start"
            })
        
            try:
                # Add timeout protection for the entire evaluation
                evaluation_timeout = 180  # 3 minutes
                evaluation_task = asyncio.create_task(
                    self.evaluate_research_completeness_async(topic, results, all_queries, "evaluation", evaluation_start_progress)
                )
                additional_queries = await asyncio.wait_for(evaluation_task, timeout=evaluation_timeout)
                
                # Clean and deduplicate queries
                additional_queries = [q for q in additional_queries if q]
                additional_queries = list(set(additional_queries) - set(all_queries))
                
                await self._emit_progress("evaluation", evaluation_end_progress, f"Evaluation complete - {len(additional_queries)} new queries identified (Iteration {current_iteration}/{self.max_iteration})", {
                    "current_iteration": current_iteration,
                    "total_iterations": self.max_iteration,
                    "additional_queries_found": len(additional_queries),
                    "queries_count": len(all_queries),
                    "total_queries": len(all_queries) + len(additional_queries),
                    "iteration_progress": 0.7,
                    "substage": "evaluation_complete"
                })
                
                if not additional_queries:
                    self.logger.info(f"✅ No Additional Research Query Needed")
                    completed_iterations += 1  # Current iteration completed
                    
                    # Calculate final progress - iteration complete
                    iteration_complete_progress = get_iteration_progress(current_iteration, "additional_search", 1.0)
                    
                    if iteration < self.max_iteration - 1:
                        # Skip remaining iterations, jump to filtering phase
                        filtering_progress = query_generation_weight + (self.max_iteration * iteration_weight)
                        await self._emit_progress("search_complete", filtering_progress, f"Research search completed - no additional queries needed (Iteration {current_iteration}/{self.max_iteration})", {
                            "current_iteration": current_iteration,
                            "total_iterations": self.max_iteration,
                            "queries_count": len(all_queries),
                            "total_queries": len(all_queries),
                            "completion_reason": "no_additional_queries",
                            "skipped_iterations": self.max_iteration - current_iteration
                        })
                    else:
                        # Last iteration completed normally
                        await self._emit_progress("search_complete", iteration_complete_progress, f"Research search completed - no additional queries needed (Iteration {current_iteration}/{self.max_iteration})", {
                            "current_iteration": current_iteration,
                            "total_iterations": self.max_iteration,
                            "queries_count": len(all_queries),
                            "total_queries": len(all_queries),
                            "completion_reason": "no_additional_queries"
                        })
                    break
                    
                self.logger.info("🔍 Additional Research Query Discovered:\n{query}".format(query='\n'.join(additional_queries)))
                
            except asyncio.TimeoutError:
                self.logger.warning(f"⚠️ Evaluation phase timed out after {evaluation_timeout}s in iteration {current_iteration}")
                completed_iterations += 1  # Current iteration completed due to timeout
                iteration_complete_progress = get_iteration_progress(current_iteration, "additional_search", 1.0)
                await self._emit_progress("evaluation_timeout", iteration_complete_progress, f"Evaluation timed out - proceeding to next stage (Iteration {current_iteration}/{self.max_iteration})", {
                    "current_iteration": current_iteration,
                    "total_iterations": self.max_iteration,
                    "timeout": evaluation_timeout,
                    "queries_count": len(all_queries),
                    "total_queries": len(all_queries),
                    "action": "continuing_without_additional_queries"
                })
                break
                
            except Exception as e:
                self.logger.error(f"❌ Error in evaluation iteration {current_iteration}: {e}")
                completed_iterations += 1  # Current iteration completed due to error
                iteration_complete_progress = get_iteration_progress(current_iteration, "additional_search", 1.0)
                await self._emit_progress("evaluation_error", iteration_complete_progress, f"Evaluation error - continuing with current results (Iteration {current_iteration}/{self.max_iteration})", {
                    "current_iteration": current_iteration,
                    "total_iterations": self.max_iteration,
                    "error": str(e)[:200],
                    "queries_count": len(all_queries),
                    "total_queries": len(all_queries),
                    "action": "continuing_with_current_results"
                })
                break
            
            # Check for cancellation before additional search
            await self._check_cancellation(f"additional search - iteration {current_iteration}")
            
            # Calculate additional search progress for this iteration
            additional_search_start_progress = get_iteration_progress(current_iteration, "additional_search", 0.0)
            additional_search_end_progress = get_iteration_progress(current_iteration, "additional_search", 1.0)
            
            await self._emit_progress("additional_search", additional_search_start_progress, f"Searching additional queries... (Iteration {current_iteration}/{self.max_iteration})", {
                "current_iteration": current_iteration,
                "total_iterations": self.max_iteration,
                "additional_queries": len(additional_queries),
                "queries_count": len(all_queries) + len(additional_queries),
                "total_queries": len(all_queries) + len(additional_queries),
                "iteration_progress": 0.7,
                "substage": "additional_search_start"
            })
        
            try:
                # Use async version for parallel processing with progress tracking
                search_progress_weight = additional_search_end_progress - additional_search_start_progress
                
                # Add timeout for search operations
                search_timeout = 300  # 5 minutes for searches
                search_task = asyncio.create_task(
                    self.search_all_queries_async(additional_queries, "additional_search", additional_search_start_progress, search_progress_weight, current_iteration, self.max_iteration)
                )
                new_results = await asyncio.wait_for(search_task, timeout=search_timeout)
            
                results = results + new_results
                all_queries.extend(additional_queries)
                
                # Complete this iteration
                completed_iterations += 1
                await self._emit_progress("additional_search", additional_search_end_progress, f"Additional search completed (Iteration {current_iteration}/{self.max_iteration})", {
                    "current_iteration": current_iteration,
                    "total_iterations": self.max_iteration,
                    "new_results": len(new_results.results),
                    "queries_count": len(all_queries),
                    "total_queries": len(all_queries),
                    "iteration_progress": 1.0,
                    "substage": "additional_search_complete"
                })
                
            except asyncio.TimeoutError:
                self.logger.warning(f"⚠️ Additional search timed out after {search_timeout}s in iteration {current_iteration}")
                completed_iterations += 1  # Current iteration completed due to timeout
                await self._emit_progress("search_timeout", additional_search_end_progress, f"Search timed out - proceeding with current results (Iteration {current_iteration}/{self.max_iteration})", {
                    "current_iteration": current_iteration,
                    "total_iterations": self.max_iteration,
                    "timeout": search_timeout,
                    "queries_count": len(all_queries),
                    "total_queries": len(all_queries)
                })
                break
                
            except Exception as e:
                self.logger.error(f"❌ Error in additional search iteration {current_iteration}: {e}")
                completed_iterations += 1  # Current iteration completed due to error
                await self._emit_progress("search_error", additional_search_end_progress, f"Search error - continuing with current results (Iteration {current_iteration}/{self.max_iteration})", {
                    "current_iteration": current_iteration,
                    "total_iterations": self.max_iteration,
                    "error": str(e)[:200],
                    "queries_count": len(all_queries),
                    "total_queries": len(all_queries)
                })
                break

        # Handle case where no results were generated (shouldn't happen, but defensive)
        if results is None:
            results = DeepResearchResults(results=[])
            
        self.logger.info(f"📊 Data Research Completed, Found {len(results.results)} Research Information")
        
        # Filtering phase - post-iteration processing
        await self._check_cancellation("filtering phase")
        
        # Calculate filtering progress (after all iterations)
        filtering_start_progress = query_generation_weight + (self.max_iteration * iteration_weight)
        filtering_end_progress = 0.95  # Leave room for report generation
        
        await self._emit_progress("filtering", filtering_start_progress + 0.01, "Starting relevance analysis and filtering...", {
            "threshold": self.rerank_score_threshold,
            "current_iteration": completed_iterations,
            "total_iterations": self.max_iteration,
            "queries_count": len(all_queries),
            "total_queries": len(all_queries),
            "stage": "filtering_start"
        })
        
        await self._emit_progress("filtering", filtering_start_progress + 0.02, "Filtering and ranking results by relevance...", {
            "threshold": self.rerank_score_threshold,
            "current_iteration": completed_iterations,
            "total_iterations": self.max_iteration,
            "queries_count": len(all_queries),
            "total_queries": len(all_queries),
            "stage": "filtering_active"
        })
        
        filtered_results = await self.filter_results_with_rerank_async(topic, results, "filtering", filtering_start_progress + 0.02)
        self.logger.info(f"🔽 Filtering Research Information With Rerank Relevance Score Threshold of {self.rerank_score_threshold}, Retrieved {len(filtered_results.results)} Research Information")
        
        await self._emit_progress("filtering", filtering_end_progress, f"Filtering complete - selected {len(filtered_results.results)} high-quality sources", {
            "total_results": len(filtered_results.results),
            "removed_results": len(results.results) - len(filtered_results.results),
            "current_iteration": completed_iterations,
            "total_iterations": self.max_iteration,
            "queries_count": len(all_queries),
            "total_queries": len(all_queries),
            "stage": "filtering_complete"
        })

        # Report Generation phase - final stage
        await self._check_cancellation("report generation phase")
        
        report_start_progress = 0.95
        report_complete_progress = 1.0
        
        await self._emit_progress("report_generation", report_start_progress + 0.01, "Starting comprehensive research report generation...", {
            "total_results": len(filtered_results.results),
            "model": self.answer_model,
            "current_iteration": completed_iterations,
            "total_iterations": self.max_iteration,
            "queries_count": len(all_queries),
            "total_queries": len(all_queries),
            "stage": "report_start"
        })
        self.logger.info(f"📝 Generate Research Report")
        
        # Report generation progress
        report_progress = report_start_progress  # the report step reports 0.95-0.99
        report = await self.generate_research_answer_async(topic, filtered_results, "report_generation", report_progress)
        
        # Complete (100% progress)
        await self._emit_progress("complete", report_complete_progress, "Research completed successfully!", {
            "total_results": len(filtered_results.results),
            "report_length": len(report),
            "current_iteration": completed_iterations,
            "total_iterations": self.max_iteration,
            "queries_count": len(all_queries),
            "total_queries": len(all_queries),
            "stage": "complete"
        })
    
        return report

    def generate_research_queries(self, topic: str) -> list[str]:
        
        PLANNING_PROMPT = self.prompts['planning_prompt'].format(
            number_of_queries=self.max_queries
        )
        plan = llm_call(
            model=self.planning_model,
            system_prompt=PLANNING_PROMPT,
            message=f"Research Topic: {topic}"
        )
    
        SEARCH_PROMPT = self.prompts["plan_parsing_prompt"]
        json_plan = llm_call(
            model=self.json_model,
            system_prompt=SEARCH_PROMPT,
            message=f"Plan to be parsed: {plan}",
            response_format={
                "type": "json_object",
                "schema": ResearchPlan.model_json_schema()},
        )
        
        plan = json.loads(json_plan)
        return plan['queries']

    def search_all_queries(self, queries: List[str]) -> DeepResearchResults:
        """Synchronous version (use_async: false)"""
        result_list = []

        for query in queries:
            result_list.append(self._search_engine_call(query))
    
        combined_results = DeepResearchResults(results=[])
        for results in result_list:
            combined_results = combined_results + results
        
        return combined_results

    async def search_all_queries_async(self, queries: List[str], stage_name: str = "search", base_progress: float = 0.0, progress_weight: float = 0.6, current_iteration: int = 1, total_iterations: int = 1) -> DeepResearchResults:
        """Async version for parallel processing with fine-grained progress tracking"""
        if not queries:
            return DeepResearchResults(results=[])
        
        total_queries = len(queries)
        combined_results = DeepResearchResults(results=[])
        
        # Create a semaphore to limit concurrent requests (avoid overwhelming the API)
        semaphore = asyncio.Semaphore(5)  # Max 5 concurrent searches
        
        # Thread-safe counter for completed queries
        completed_lock = asyncio.Lock()
        completed_queries = 0
        
        async def search_with_progress(query: str, query_index: int) -> DeepResearchResults:
            nonlocal completed_queries
            async with semaphore:
                try:
                    # Check for cancellation before starting each search query
                    await self._check_cancellation(f"search query {query_index+1}/{total_queries}")
                    
                    # Emit progress before starting this query
                    async with completed_lock:
                        current_completed = completed_queries
                    
                    # More granular progress tracking within search phase
                    # Show individual query progress as small increments within the allocated range
                    query_progress_increment = (current_completed / total_queries) * progress_weight
                    current_query_progress = base_progress + query_progress_increment
                    
                    await self._emit_progress(stage_name, current_query_progress, f"Searching: {query[:50]}{'...' if len(query) > 50 else ''}", {
                        "query_index": query_index + 1,
                        "queries_count": total_queries,
                        "total_queries": total_queries,
                        "completed_queries": current_completed,
                        "current_query": query,
                        "current_iteration": current_iteration,
                        "total_iterations": total_iterations,
                        "current_iteration_queries": total_queries,
                        "completed_queries_current_iteration": current_completed,
                        "progress_detail": f"query_{query_index+1}_start"
                    })
                    
                    # Check for cancellation before performing the search
                    await self._check_cancellation(f"executing search for query {query_index+1}")
                    
                    # Perform the actual search
                    result = await self._search_engine_call_async(query)
                    
                    # Thread-safe update of completed count and emit progress
                    async with completed_lock:
                        completed_queries += 1
                        current_completed = completed_queries
                    
                    # Update progress after query completion
                    query_progress_increment = (current_completed / total_queries) * progress_weight
                    completed_query_progress = base_progress + query_progress_increment
                    
                    await self._emit_progress(stage_name, completed_query_progress, f"Completed {current_completed}/{total_queries} searches", {
                        "query_index": query_index + 1,
                        "queries_count": total_queries,
                        "total_queries": total_queries,
                        "completed_queries": current_completed,
                        "results_found": len(result.results) if result else 0,
                        "current_iteration": current_iteration,
                        "total_iterations": total_iterations,
                        "current_iteration_queries": total_queries,
                        "completed_queries_current_iteration": current_completed,
                        "progress_detail": f"query_{query_index+1}_complete"
                    })
                    
                    return result
                    
                except Exception as e:
                    # Thread-safe update even on failure
                    async with completed_lock:
                        completed_queries += 1
                        current_completed = completed_queries
                    
                    self.logger.error(f"Search query failed for '{query}': {e}")
                    
                    # Still emit progress even on failure
                    query_progress_increment = (current_completed / total_queries) * progress_weight
                    failed_query_progress = base_progress + query_progress_increment
                    
                    await self._emit_progress(stage_name, failed_query_progress, f"Query failed, continuing ({current_completed}/{total_queries})", {
                        "query_index": query_index + 1,
                        "queries_count": total_queries,
                        "total_queries": total_queries,
                        "completed_queries": current_completed,
                        "error": str(e),
                        "current_iteration": current_iteration,
                        "total_iterations": total_iterations,
                        "progress_detail": f"query_{query_index+1}_failed"
                    })
                    
                    return DeepResearchResults(results=[])
        
        # Create tasks for all queries with their indices
        tasks = [search_with_progress(query, i) for i, query in enumerate(queries)]
        
        # Execute all searches concurrently
        result_list = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Combine all results
        for result in result_list:
            if isinstance(result, Exception):
                self.logger.error(f"Unexpected search error: {result}")
                continue
            if result:
                combined_results = combined_results + result
        
        # Final progress update for this stage - ensure we reach the target progress
        final_progress = base_progress + progress_weight
        await self._emit_progress(stage_name, final_progress, f"Search completed - found {len(combined_results.results)} raw results", {
            "queries_count": total_queries,
            "total_queries": total_queries,
            "completed_queries": completed_queries,
            "current_iteration": current_iteration,
            "total_iterations": total_iterations,
            "progress_detail": "search_stage_complete"
        })
        
        return combined_results

    def _search_engine_call(self, query: str) -> DeepResearchResults:
        if len(query) > 400:
            query = query[:400]
    
        response = tavily_search(query, max_results=self.max_searchs)
    
        RAW_CONTENT_SUMMARIZER_PROMPT = self.prompts['raw_content_summarizer_prompt']
        summarized_contents = []
        result_info = []
    
        for result in response.results:
            task = llm_call(
                model = self.summarization_model,
                system_prompt=RAW_CONTENT_SUMMARIZER_PROMPT,
                message=f"<Raw Content>{result.raw_content}</Raw Content>\n\n<Research Topic>{query}</Research Topic>"
            )
        
            summarized_contents.append(task)
            result_info.append(result)
    
        formatted_results = []
        for result, summarized_content in zip(result_info, summarized_contents):
            formatted_results.append(
                DeepResearchResult(
                    title=result.title,
                    link=result.link,
                    content=result.content,
                    raw_content=result.raw_content,
                    summarized_content=summarized_content,
                )
            )
    
        return DeepResearchResults(results=formatted_results)

    async def _intelligently_process_long_content(self, content: str, research_topic: str) -> str:
        """
        Intelligently process long content using hierarchical summarization
        instead of crude truncation to preserve all valuable information.
        Now with async support and cancellation checks for responsive cancellation.
        
        Args:
            content: Raw content that may exceed token limits
            research_topic: Research topic for context-aware processing
            
        Returns:
            Comprehensive summary preserving information from entire content
        """
        if not content:
            return ""
        
        # Check for cancellation at the start
        await self._check_cancellation("content processing initialization")
        
        
        # Conservative token limit per chunk (leaving room for prompt overhead)
        MAX_CHUNK_TOKENS = 60000  # ~240K chars, well under API limits
        
        # Check if content fits within limits
        content_tokens = self.token_counter.count_tokens(content)
        if content_tokens <= MAX_CHUNK_TOKENS:
            # Content is manageable, process normally
            return content
        
        # Content is too large - use hierarchical summarization
        self.logger.info(f"Content has {content_tokens} tokens ({len(content)} chars), using hierarchical summarization")
        
        # Check for cancellation before starting expensive processing
        await self._check_cancellation("hierarchical summarization start")
        
        # Split content into manageable chunks with smart boundaries
        chunks = self._split_content_intelligently(content, MAX_CHUNK_TOKENS)
        
        # Summarize each chunk with cancellation checks
        chunk_summaries = []
        for i, chunk in enumerate(chunks):
            # Check for cancellation before processing each chunk
            await self._check_cancellation(f"chunk {i+1}/{len(chunks)} processing")
            
            try:
                chunk_summary = await llm_call_async(
                    model=self.summarization_model,
                    system_prompt=self.prompts['raw_content_summarizer_prompt'],
                    message=f"<Raw Content>{chunk}</Raw Content>\n\n<Research Topic>{research_topic}</Research Topic>"
                )
                chunk_summaries.append(f"## Segment {i+1} Summary\n{chunk_summary}")
                self.logger.debug(f"Successfully summarized chunk {i+1}/{len(chunks)}")
                
            except asyncio.CancelledError:
                self.logger.info(f"🛑 Hierarchical summarization cancelled during chunk {i+1}/{len(chunks)}")
                raise
            except Exception as e:
                self.logger.error(f"Failed to summarize chunk {i+1}: {e}")
                # Include truncated chunk as fallback
                truncated_chunk = self.token_counter.truncate_to_tokens(chunk, 2000, "...[truncated]")
                chunk_summaries.append(f"## Segment {i+1} (Processing Failed)\n{truncated_chunk}")
        
        # Check for cancellation before combining summaries
        await self._check_cancellation("combining chunk summaries")
        
        # Combine chunk summaries for meta-summarization
        combined_summaries = "\n\n".join(chunk_summaries)
        self.logger.debug(f"Combined {len(chunk_summaries)} chunk summaries for meta-summarization")
        
        try:
            meta_summary = await llm_call_async(
                model=self.summarization_model,
                system_prompt=self.prompts['meta_summarizer_prompt'],
                message=f"<Chunk Summaries>{combined_summaries}</Chunk Summaries>\n\n<Research Topic>{research_topic}</Research Topic>"
            )
            
            self.logger.info(f"✅ Successfully created meta-summary from {len(chunks)} chunks")
            return meta_summary
            
        except asyncio.CancelledError:
            self.logger.info("🛑 Meta-summarization cancelled")
            raise
        except Exception as e:
            self.logger.error(f"Meta-summarization failed: {e}")
            # Return combined summaries as fallback
            return combined_summaries

    def _split_content_intelligently(self, content: str, max_tokens_per_chunk: int) -> List[str]:
        """
        Split content into chunks that respect natural boundaries and token limits.
        
        Args:
            content: Content to split
            max_tokens_per_chunk: Maximum tokens per chunk
            
        Returns:
            List of content chunks
        """
        # First, try to split on natural boundaries (paragraphs, sections)
        # Look for common section markers
        section_markers = ['\n\n\n', '\n\n', '.\n', '\n']
        
        chunks = []
        remaining_content = content
        
        while remaining_content:
            # Check if remaining content fits in one chunk
            if self.token_counter.count_tokens(remaining_content) <= max_tokens_per_chunk:
                chunks.append(remaining_content)
                break
            
            # Find the best split point within token limit
            best_split_idx = 0
            
            # Try different boundary markers in order of preference
            for marker in section_markers:
                # Find all occurrences of this marker
                marker_positions = [i for i, c in enumerate(remaining_content) if remaining_content[i:i+len(marker)] == marker]
                
                # Find the largest chunk that fits within token limit
                for pos in marker_positions:
                    potential_chunk = remaining_content[:pos + len(marker)]
                    if self.token_counter.count_tokens(potential_chunk) <= max_tokens_per_chunk:
                        best_split_idx = pos + len(marker)
                    else:
                        break
                
                if best_split_idx > 0:
                    break
            
            # If no good boundary found, split at token limit
            if best_split_idx == 0:
                best_split_idx = len(self.token_counter.truncate_to_tokens(remaining_content, max_tokens_per_chunk, ""))
            
            # Create chunk and update remaining content
            chunk = remaining_content[:best_split_idx].strip()
            if chunk:
                chunks.append(chunk)
            
            remaining_content = remaining_content[best_split_idx:].strip()
        
        return chunks

    async def _search_engine_call_async(self, query: str) -> DeepResearchResults:
        """Async version of _search_engine_call for parallel processing"""
        if len(query) > 400:
            query = query[:400]
    
        # Use async tavily search with cancellation support
        response = await tavily_search_async(query, max_results=self.max_searchs)
    
        RAW_CONTENT_SUMMARIZER_PROMPT = self.prompts['raw_content_summarizer_prompt']
        formatted_results = []
        
        # Process each result sequentially using intelligent content processing
        for i, result in enumerate(response.results):
            try:
                # Use intelligent processing instead of crude truncation
                raw_content = result.raw_content or ""  # Handle None content
                
                # Intelligently process content (chunking + hierarchical summarization if needed)
                processed_content = await self._intelligently_process_long_content(raw_content, query)
                
                # If content was processed (chunked), use it directly as summary
                # Otherwise, run through normal summarization
                if processed_content != raw_content:
                    # Content was intelligently processed (chunked/summarized)
                    summarized_content = processed_content
                    self.logger.info(f"Successfully processed long content for {result.title} using hierarchical summarization")
                else:
                    
                    # Content is manageable, process with normal summarization
                    summarized_content = await llm_call_async(
                        model=self.summarization_model,
                        system_prompt=RAW_CONTENT_SUMMARIZER_PROMPT,
                        message=f"<Raw Content>{processed_content}</Raw Content>\n\n<Research Topic>{query}</Research Topic>"
                    )
                
                # Store the processed result immediately (keeps original raw_content for reference)
                formatted_results.append(
                    DeepResearchResult(
                        title=result.title,
                        link=result.link,
                        content=result.content,
                        raw_content=result.raw_content,  # Keep original for reference
                        summarized_content=summarized_content,
                    )
                )
                
            except asyncio.CancelledError:
                # Handle cancellation gracefully during processing
                self.logger.info(f"🛑 Search result processing cancelled for {result.title}")
                raise
            except Exception as e:
                self.logger.error(f"Failed to process result {result.title}: {e}")
                # Store result with truncated content as fallback
                fallback_content = self.token_counter.truncate_to_tokens(
                    result.raw_content or result.content or "", 2000, "...[truncated due to processing error]"
                )
                formatted_results.append(
                    DeepResearchResult(
                        title=result.title,
                        link=result.link,
                        content=result.content,
                        raw_content=result.raw_content,
                        summarized_content=fallback_content,
                    )
                )
    
        return DeepResearchResults(results=formatted_results)

    def evaluate_research_completeness(self, topic: str, results: DeepResearchResults, queries: List[str]) -> list[str]:
        # Clear previous context and build optimized context for planning
        self.context_manager.clear_context("planning")
        
        # Add context segments with appropriate priorities
        self.context_manager.add_context_segment(
            content=f"Research Topic: {topic}",
            segment_type="topic",
            priority=10  # Highest priority
        )
        
        self.context_manager.add_context_segment(
            content=f"Search Queries Used: {queries}",
            segment_type="queries", 
            priority=9   # High priority
        )
        
        # Create optimized summary of results for planning context
        results_summary = self.context_manager.create_research_summary(results, max_tokens=8000)
        self.context_manager.add_context_segment(
            content=f"Current Search Results:\n{results_summary}",
            segment_type="results",
            priority=8   # High priority but less than topic/queries
        )
        
        # Get optimized context that fits within token limits
        optimized_context = self.context_manager.get_planning_context(
            research_topic=topic,
            additional_tokens=2048  # Reserve for response
        )
        
        EVALUATION_PROMPT = self.prompts["evaluation_prompt"].format(
            number_of_queries=self.max_queries
        )
        
        self.logger.info(f"🔍 Evaluating research completeness with {self.token_counter.count_tokens(optimized_context):,} context tokens")
        
        # Enhanced error recovery for token limit issues
        max_retries = 3
        for attempt in range(max_retries):
            try:
                evaluation = llm_call(
                    model = self.planning_model,
                    system_prompt=EVALUATION_PROMPT,
                    message=optimized_context,
                )
                break  # Success, exit retry loop
                
            except Exception as e:
                error_str = str(e).lower()
                if "token" in error_str and "limit" in error_str and attempt < max_retries - 1:
                    self.logger.warning(f"🔄 Token limit error on attempt {attempt + 1}, trying reduced context...")
                    
                    # Use context manager's error recovery
                    optimized_context = self.context_manager.handle_token_limit_error(topic, str(e))
                    self.logger.info(f"🔄 Retry {attempt + 2} with {self.token_counter.count_tokens(optimized_context):,} tokens")
                    continue
                else:
                    if attempt == max_retries - 1:
                        self.logger.error(f"❌ Planning model failed after {max_retries} attempts: {e}")
                        # Return empty list as fallback
                        return []
                    raise
    
        EVALUATION_PARSING_PROMPT = self.prompts["evaluation_parsing_prompt"]
        response_json = llm_call(
            model = self.json_model,
            system_prompt=EVALUATION_PARSING_PROMPT,
            message=f"Evaluation to be parsed: {evaluation}",
            response_format={"type": "json_object", "schema": ResearchPlan.model_json_schema()},
        )
    
        evaluation = json.loads(response_json)
        return evaluation["queries"]

    async def evaluate_research_completeness_async(self, topic: str, results: DeepResearchResults, queries: List[str], progress_stage: str, progress_value: float) -> list[str]:
        """Async version of evaluate_research_completeness with progress tracking and timeout protection"""
        try:
            # Check for cancellation at start of evaluation
            await self._check_cancellation("evaluation start")
            
            await self._emit_progress(progress_stage, progress_value, "Analyzing research completeness...", {
                "current_results": len(results.results),
                "queries_used": len(queries)
            })
            
            # Add timeout protection for the entire evaluation process
            timeout_seconds = 120  # 2 minutes timeout
            
            # Clear previous context and build optimized context for planning
            self.context_manager.clear_context("planning")
            
            # Add context segments with appropriate priorities
            self.context_manager.add_context_segment(
                content=f"Research Topic: {topic}",
                segment_type="topic",
                priority=10  # Highest priority
            )
            
            self.context_manager.add_context_segment(
                content=f"Search Queries Used: {queries}",
                segment_type="queries", 
                priority=9   # High priority
            )
            
            # Create optimized summary of results for planning context
            results_summary = self.context_manager.create_research_summary(results, max_tokens=8000)
            self.context_manager.add_context_segment(
                content=f"Current Search Results:\n{results_summary}",
                segment_type="results",
                priority=8   # High priority but less than topic/queries
            )
            
            # Get optimized context that fits within token limits
            optimized_context = self.context_manager.get_planning_context(
                research_topic=topic,
                additional_tokens=2048  # Reserve for response
            )
            
            EVALUATION_PROMPT = self.prompts["evaluation_prompt"].format(
                number_of_queries=self.max_queries
            )
            
            await self._emit_progress(progress_stage, progress_value + 0.01, "Evaluating research gaps...", {
                "model": self.planning_model,
                "timeout": timeout_seconds,
                "context_tokens": self.token_counter.count_tokens(optimized_context)
            })
            
            self.logger.info(f"🔍 Async evaluating research completeness with {self.token_counter.count_tokens(optimized_context):,} context tokens")
            
            # Enhanced error recovery with timeout protection
            max_retries = 3
            evaluation = None
            
            for attempt in range(max_retries):
                try:
                    # Check for cancellation before each evaluation attempt
                    await self._check_cancellation(f"evaluation attempt {attempt+1}")
                    
                    evaluation_task = asyncio.create_task(asyncio.to_thread(
                        llm_call,
                        model=self.planning_model,
                        system_prompt=EVALUATION_PROMPT,
                        message=optimized_context,
                    ))
                    evaluation = await asyncio.wait_for(evaluation_task, timeout=timeout_seconds)
                    break  # Success, exit retry loop
                    
                except asyncio.TimeoutError:
                    if attempt < max_retries - 1:
                        self.logger.warning(f"⏰ Evaluation timed out on attempt {attempt + 1}, retrying with reduced context...")
                        # Reduce timeout and context for retry
                        timeout_seconds = max(60, timeout_seconds - 30)
                        optimized_context = self.context_manager.handle_token_limit_error(topic, "Timeout - reducing context")
                        await self._emit_progress(progress_stage, progress_value + 0.02, f"Retry {attempt + 2} with reduced context...", {
                            "retry_attempt": attempt + 2,
                            "new_timeout": timeout_seconds,
                            "context_tokens": self.token_counter.count_tokens(optimized_context)
                        })
                        continue
                    else:
                        self.logger.warning(f"⚠️ Evaluation LLM call timed out after {timeout_seconds}s and {max_retries} attempts, returning empty queries")
                        await self._emit_progress(progress_stage, progress_value + 0.04, "Evaluation timed out - proceeding with current results", {
                            "timeout": True,
                            "action": "skip_additional_queries"
                        })
                        return []
                        
                except Exception as e:
                    error_str = str(e).lower()
                    if "token" in error_str and "limit" in error_str and attempt < max_retries - 1:
                        self.logger.warning(f"🔄 Token limit error on attempt {attempt + 1}, trying reduced context...")
                        
                        # Use context manager's error recovery
                        optimized_context = self.context_manager.handle_token_limit_error(topic, str(e))
                        await self._emit_progress(progress_stage, progress_value + 0.02, f"Retry {attempt + 2} with reduced context...", {
                            "retry_attempt": attempt + 2,
                            "error_type": "token_limit",
                            "context_tokens": self.token_counter.count_tokens(optimized_context)
                        })
                        continue
                    else:
                        if attempt == max_retries - 1:
                            self.logger.error(f"❌ Planning model failed after {max_retries} attempts: {e}")
                            await self._emit_progress(progress_stage, progress_value + 0.04, "Planning model failed - proceeding without additional queries", {
                                "error": str(e),
                                "action": "skip_additional_queries"
                            })
                            return []
                        raise
            
            # This code should only run if we got a successful evaluation
            
            await self._emit_progress(progress_stage, progress_value + 0.02, "Parsing evaluation results...", {
                "model": self.json_model
            })
        
            EVALUATION_PARSING_PROMPT = self.prompts["evaluation_parsing_prompt"]
            
            # Wrap parsing call with timeout
            try:
                parsing_task = asyncio.create_task(asyncio.to_thread(
                    llm_call,
                    model=self.json_model,
                    system_prompt=EVALUATION_PARSING_PROMPT,
                    message=f"Evaluation to be parsed: {evaluation}",
                    response_format={"type": "json_object", "schema": ResearchPlan.model_json_schema()},
                ))
                response_json = await asyncio.wait_for(parsing_task, timeout=60)  # 1 minute timeout for parsing
            except asyncio.TimeoutError:
                self.logger.warning("⚠️ Evaluation parsing timed out, returning empty queries")
                await self._emit_progress(progress_stage, progress_value + 0.04, "Evaluation parsing timed out - proceeding with current results", {
                    "timeout": True,
                    "action": "skip_additional_queries"
                })
                return []
        
            evaluation_data = json.loads(response_json)
            additional_queries = evaluation_data.get("queries", [])
            
            await self._emit_progress(progress_stage, progress_value + 0.03, f"Found {len(additional_queries)} additional research areas", {
                "additional_queries": len(additional_queries),
                "new_queries": additional_queries[:3]  # Show first 3 queries
            })
            
            return additional_queries
            
        except Exception as e:
            self.logger.error(f"❌ Error in evaluation: {e}")
            await self._emit_progress(progress_stage, progress_value + 0.04, f"Evaluation failed: {str(e)[:100]} - continuing with current results", {
                "error": str(e)[:200],
                "action": "continue_with_current_results"
            })
            return []
    def _filter_source_quality(self, results: DeepResearchResults) -> DeepResearchResults:
        """Filter out sources with insufficient content or quality issues"""
        quality_filtered = []
        
        for result in results.results:
            # Check content sufficiency (minimum 50 meaningful words)
            if self._is_sufficient_content(result):
                quality_filtered.append(result)
            else:
                self.logger.info(f"🗑️ Filtered out insufficient source: {result.title[:50]}...")
        
        self.logger.info(f"📋 Source quality filtering: {len(results.results)} → {len(quality_filtered)} sources")
        return DeepResearchResults(results=quality_filtered)
    
    def _is_sufficient_content(self, result) -> bool:
        """Check if a source has sufficient content for analysis"""
        content_text = ""
        
        # Combine all available content
        if hasattr(result, 'content') and result.content:
            content_text += result.content
        if hasattr(result, 'raw_content') and result.raw_content:
            content_text += " " + result.raw_content
        if hasattr(result, 'summarized_content') and result.summarized_content:
            content_text += " " + result.summarized_content
        
        # Clean and count meaningful words
        clean_text = re.sub(r'[^\w\s]', ' ', content_text.lower())
        words = [word for word in clean_text.split() if len(word) > 2]  # Filter short words
        
        # Requirements for sufficient content (from config)
        min_word_count = self.config.get('research', 'min_content_words', default=50)
        min_char_count = self.config.get('research', 'min_content_chars', default=200)
        
        # Check for common insufficient content indicators
        insufficient_indicators = [
            'no content', 'content not available', 'page not found',
            'error', '404', 'access denied', 'subscription required',
            'login required', 'paywall', 'preview only'
        ]
        
        content_lower = content_text.lower()
        has_insufficient_indicators = any(indicator in content_lower for indicator in insufficient_indicators)
        
        return (len(words) >= min_word_count and 
                len(content_text.strip()) >= min_char_count and 
                not has_insufficient_indicators)

    def filter_results_with_rerank(self, topic: str, results: DeepResearchResults):
        # First apply source quality filtering to remove incomplete sources
        results = self._filter_source_quality(results)
        results = results.dedup()
        documents = [str(result) for result in results.results]
    
        rerank = llm_rerank(topic, documents)
        
        rerank_filtered = list(filter(lambda x: x.relevance_score >= self.rerank_score_threshold, rerank.results))
    
        filtered_links = set()
        for result in rerank_filtered:
            link_search = re.search('Link: (.*)', result.document).group(1)
            filtered_links.add(link_search)
    
        return DeepResearchResults(results=[r for r in results.results if r.link in filtered_links])

    async def filter_results_with_rerank_async(self, topic: str, results: DeepResearchResults, progress_stage: str, progress_value: float):
        """filter_results_with_rerank in a worker thread, with progress updates"""
        await self._check_cancellation("filtering start")
        await self._emit_progress(progress_stage, progress_value + 0.05, f"Ranking {len(results.results)} results by relevance...", {
            "rerank_threshold": self.rerank_score_threshold
        })

        filtered_results = await asyncio.to_thread(self.filter_results_with_rerank, topic, results)

        await self._emit_progress(progress_stage, progress_value + 0.15, f"Filtering complete - {len(filtered_results.results)} results kept", {
            "total_results": len(filtered_results.results),
            "removed_results": len(results.results) - len(filtered_results.results)
        })
        return filtered_results

    def _analyze_information_quality(self, topic: str, results: DeepResearchResults) -> str:
        """Analyze information quality and identify conflicts across any research domain"""
        if not results.results:
            return "No sources available for quality analysis."
        
        analysis_points = []
        
        # Check for potential conflicts in the data
        conflicts = self._detect_information_conflicts(results)
        if conflicts:
            analysis_points.append(f"CONFLICTING INFORMATION DETECTED: {conflicts}")
        
        # Assess source diversity
        source_count = len(results.results)
        unique_domains = len(set(self._extract_domain(result.link) for result in results.results if result.link))
        
        if source_count > 0:
            analysis_points.append(f"Source Analysis: {source_count} sources from {unique_domains} unique domains")
        
        # Check for recency if dates are available
        recent_sources = sum(1 for result in results.results if self._appears_recent(result))
        if recent_sources > 0:
            analysis_points.append(f"Recency: {recent_sources}/{source_count} sources appear to be recent")
        
        # General quality assessment
        high_quality_sources = sum(1 for result in results.results if self._assess_source_quality(result))
        analysis_points.append(f"Quality Assessment: {high_quality_sources}/{source_count} sources show high credibility indicators")
        
        if not analysis_points:
            analysis_points.append("Standard information quality - no significant conflicts detected")
        
        return "RESEARCH QUALITY ANALYSIS:\n" + "\n".join(f"- {point}" for point in analysis_points)
    
    def _detect_information_conflicts(self, results: DeepResearchResults) -> str:
        """Detect potential conflicts in information across any domain"""
        # Look for numerical conflicts (simple detection)
        numbers_found = []
        for result in results.results:
            content = f"{result.content} {result.summarized_content if result.summarized_content else ''}"
            # Extract numbers with context
            number_patterns = re.findall(r'(\b\d+(?:,\d{3})*(?:\.\d+)?(?:\s*(?:percent|%|billion|million|thousand|years?|months?|days?))?)', content.lower())
            numbers_found.extend(number_patterns)
        
        # Simple conflict detection - if we find very different numbers for similar concepts
        if len(set(numbers_found)) > len(numbers_found) * 0.8:  # High number diversity suggests potential conflicts
            return "Multiple differing numerical claims detected - reconciliation analysis recommended"
        
        return ""
    
    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL"""
        if not url:
            return "unknown"
        try:
            from urllib.parse import urlparse
            return urlparse(url).netloc.lower()
        except:
            return "unknown"
    
    def _appears_recent(self, result) -> bool:
        """Check if source appears to be recent (simple heuristic)"""
        content = f"{result.title} {result.content}"
        recent_indicators = ['2024', '2025', 'recent', 'latest', 'current', 'new', 'updated']
        return any(indicator in content.lower() for indicator in recent_indicators)
    
    def _assess_source_quality(self, result) -> bool:
        """Simple heuristic for source quality assessment"""
        if not result.link:
            return False
        
        domain = self._extract_domain(result.link)
        # High-quality domain indicators
        quality_indicators = [
            '.edu', '.gov', '.org',  # Institutional domains
            'scholar.google', 'pubmed', 'arxiv',  # Academic sources
            'nature.com', 'science.org', 'cell.com',  # Scientific journals
            'bbc.com', 'reuters.com', 'ap.org',  # Reputable news
        ]
        
        # Check if it's a well-known quality source
        is_quality_domain = any(indicator in domain for indicator in quality_indicators)
        
        # Check content length as quality indicator
        content_length = len(f"{result.content} {result.summarized_content if result.summarized_content else ''}")
        has_substantial_content = content_length > 500
        
        return is_quality_domain or has_substantial_content

    def generate_research_answer(self, topic: str, results: DeepResearchResults):
        formatted_results = str(results)
        
        # Analyze for information conflicts and generate quality insights
        quality_analysis = self._analyze_information_quality(topic, results)
        
        # Truncate results to prevent token limit errors
        # Estimate ~4 chars per token, leave room for topic and prompt
        max_chars = 120000  # ~30k tokens for results, leaving room for other content
        if len(formatted_results) > max_chars:
            formatted_results = formatted_results[:max_chars] + "\n\n[Content truncated due to length...]"
    
        # Enhanced prompt with quality analysis
        enhanced_message = f"Research Topic: {topic}\n\nQuality Analysis:\n{quality_analysis}\n\nSearch Results:\n{formatted_results}"
        
        ANSWER_PROMPT = self.prompts["answer_prompt"]
        answer = llm_call(
            model=self.answer_model,
            system_prompt=ANSWER_PROMPT,
            message=enhanced_message,
            max_completion_tokens=self.max_completion_token
        )
    
        if self.remove_thinking_token:
            answer = remove_thinking_tags(answer)
    
        if answer.lstrip().startswith("```"):
            first_linebreak = answer.find("\n", answer.find("```"))
            if first_linebreak != -1:
                answer = answer[first_linebreak + 1 :]
    
            if answer.rstrip().endswith("```"):
                answer = answer.rstrip()[:-3].rstrip()
    
        return answer.strip()

    async def generate_research_answer_async(self, topic: str, results: DeepResearchResults, progress_stage: str, progress_value: float):
        """Async version of generate_research_answer with progress tracking"""
        # Check for cancellation at start of report generation
        await self._check_cancellation("report generation start")
        
        await self._emit_progress(progress_stage, progress_value, "Preparing research data for report generation...", {
            "total_results": len(results.results),
            "model": self.answer_model
        })
        
        # Clear previous report context and build comprehensive context for report generation
        self.context_manager.clear_context("report")
        
        # Add context segments for report generation (more generous token limits)
        self.context_manager.add_context_segment(
            content=f"Research Topic: {topic}",
            segment_type="topic",
            priority=10  # Highest priority
        )
        
        await self._emit_progress(progress_stage, progress_value + 0.005, "Organizing research results for comprehensive report...", {
            "results_to_process": len(results.results)
        })
        
        # For report generation, use the full results but with intelligent organization
        # Add results in chunks to maintain priority ordering
        for i, result in enumerate(results.results):  # Use all rerank-filtered results
            # Use summarized content if available, fallback to regular content
            content_to_use = result.summarized_content or result.content or result.raw_content
            if content_to_use:
                result_text = f"Source {i+1}: {result.title}\nURL: {result.link}\nContent: {content_to_use}\n"
                
                # Assign priority based on result position (earlier results = higher priority)
                priority = max(7 - (i // 3), 5)  # Priority decreases as we go through results
                
                self.context_manager.add_context_segment(
                    content=result_text,
                    segment_type="results",
                    priority=priority,
                    relevance_score=getattr(result, 'relevance_score', 0.5)  # Use relevance if available
                )
        
        # Get optimized report context (much larger limit than planning context)
        optimized_context = self.context_manager.get_report_context(
            additional_tokens=self.max_completion_token  # Reserve space for response
        )
        
        context_tokens = self.token_counter.count_tokens(optimized_context)
        self.logger.info(f"📝 Async generating research report with {context_tokens:,} context tokens")
        
        await self._emit_progress(progress_stage, progress_value + 0.01, f"Context optimized: {context_tokens:,} tokens", {
            "context_tokens": context_tokens,
            "model": self.answer_model
        })
    
        # Using the imported async LLM function
        
        await self._emit_progress(progress_stage, progress_value + 0.015, "Sending research data to AI model for report generation...", {
            "model": self.answer_model,
            "max_tokens": self.max_completion_token
        })
        
        # Check for cancellation before the LLM call for report generation
        await self._check_cancellation("generating final report")
        
        ANSWER_PROMPT = self.prompts["answer_prompt"]
        answer = await llm_call_async(
            model=self.answer_model,
            system_prompt=ANSWER_PROMPT,
            message=optimized_context,
            max_completion_tokens=self.max_completion_token
        )
    
        await self._emit_progress(progress_stage, progress_value + 0.03, "AI model response received - processing content...", {
            "raw_response_length": len(answer)
        })
        
        if self.remove_thinking_token:
            answer = remove_thinking_tags(answer)
            await self._emit_progress(progress_stage, progress_value + 0.035, "Cleaned thinking tokens from response", {
                "cleaned_length": len(answer)
            })
        else:
            await self._emit_progress(progress_stage, progress_value + 0.035, "Preserved response format", {
                "response_length": len(answer)
            })
    
        if answer.lstrip().startswith("```"):
            first_linebreak = answer.find("\n", answer.find("```"))
            if first_linebreak != -1:
                answer = answer[first_linebreak + 1 :]
    
            if answer.rstrip().endswith("```"):
                answer = answer.rstrip()[:-3].rstrip()
            
            await self._emit_progress(progress_stage, progress_value + 0.04, "Removed code block formatting from response", {
                "formatted_length": len(answer)
            })
        else:
            await self._emit_progress(progress_stage, progress_value + 0.04, "Validated response format - no code blocks detected", {
                "response_length": len(answer)
            })
        
        final_answer = answer.strip()
        
        await self._emit_progress(progress_stage, 0.99, "Research report finalized successfully!", {
            "final_length": len(final_answer),
            "word_count": len(final_answer.split()),
            "character_count": len(final_answer)
        })
    
        return final_answer
