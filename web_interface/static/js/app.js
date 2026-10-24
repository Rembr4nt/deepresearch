/**
 * Deep Research - web interface
 * 
 * This application manages the frontend functionality for the Deep Research
 * web interface, including form handling, API communication, WebSocket
 * connections for real-time progress updates, and UI state management.
 */

class DeepResearchApp {
    constructor() {
        this.currentSession = null;
        this.websocket = null;
        this.startTime = null;
        this.defaultConfig = null;
        
        // Track answered questions to prevent duplicates from race conditions
        this.answeredQuestions = new Set();
        
        // Progress management system
        this.progressState = {
            currentProgress: 0,
            displayedProgress: 0,
            currentStage: '',
            currentMessage: '',
            lastUpdateTime: 0,
            pendingUpdates: [],
            isAnimating: false,
            // Track last known details to prevent intermittent "-" values
            lastKnownDetails: {
                current_iteration: null,
                total_iterations: null,
                results: null,
                topic: null
            }
        };
        
        // Progress bar update limits
        this.progressConfig = {
            maxUpdatesPerSecond: 15,
            smoothingEnabled: true,       // Enable smooth progress transitions
            minProgressIncrement: 0.3,   // percent
            interpolationSpeed: 0.15,    // Slightly faster interpolation for more responsive feel
            debounceDelay: 80           // Reduced debounce for more responsive progress updates
        };
        
        // Initialize the application
        this.init();
    }

    /**
     * Initialize the application
     */
    async init() {
        try {
            // Load default configuration
            await this.loadDefaultConfig();
            
            // Setup event listeners
            this.setupEventListeners();
            
            // Setup form validation
            this.setupFormValidation();
            
            // Load saved preferences
            this.loadPreferences();
            
            // Show initial section
            this.showSection('researchFormSection');
            
            console.debug('Deep Research App initialized successfully');
        } catch (error) {
            console.error('Failed to initialize app:', error);
            this.showNotification('Failed to initialize application', 'error');
        }
    }

    /**
     * Load default configuration from API
     */
    async loadDefaultConfig() {
        try {
            const response = await fetch('/api/research/config/defaults');
            if (response.ok) {
                this.defaultConfig = await response.json();
                this.populateAdvancedOptions();
            }
        } catch (error) {
            console.error('Failed to load default config:', error);
            // Use fallback defaults
            this.defaultConfig = {
                max_queries: 5,
                max_searchs: 5,
                max_iteration: 3,
                max_completion_token: 8192,
                rerank_score_threshold: 0.6,
                remove_thinking_token: true,
                interactive: false,
                use_async: true
            };
            this.populateAdvancedOptions();
        }
    }

    /**
     * Setup all event listeners
     */
    setupEventListeners() {
        // Research form
        const startBtn = document.getElementById('startResearchBtn');
        const cancelBtn = document.getElementById('cancelResearchBtn');
        const cancelProgressBtn = document.getElementById('cancelProgressBtn');
        const topicInput = document.getElementById('researchTopic');
        
        startBtn.addEventListener('click', () => this.startResearch());
        cancelBtn.addEventListener('click', () => {
            console.debug('Cancel button (cancelResearchBtn) clicked');
            this.cancelResearch();
        });
        cancelProgressBtn.addEventListener('click', () => {
            console.debug('Cancel progress button (cancelProgressBtn) clicked');
            this.cancelResearch();
        });
        topicInput.addEventListener('input', () => this.validateTopic());
        
        // Advanced options toggle
        const advancedToggle = document.getElementById('advancedToggle');
        advancedToggle.addEventListener('click', () => this.toggleAdvancedOptions());
        
        // Advanced options sliders
        this.setupAdvancedOptionsListeners();
        
        // Results actions
        const downloadBtn = document.getElementById('downloadBtn');
        const copyToClipboardBtn = document.getElementById('copyToClipboardBtn');
        const newResearchBtn = document.getElementById('newResearchBtn');
        const retryBtn = document.getElementById('retryBtn');
        
        downloadBtn.addEventListener('click', () => this.toggleDownloadMenu());
        copyToClipboardBtn.addEventListener('click', () => this.copyToClipboard());
        newResearchBtn.addEventListener('click', () => this.startNewResearch());
        retryBtn.addEventListener('click', () => this.retryResearch());
        
        // Format tabs
        const renderedTab = document.getElementById('renderedTab');
        const markdownTab = document.getElementById('markdownTab');
        
        renderedTab.addEventListener('click', () => this.showFormatTab('rendered'));
        markdownTab.addEventListener('click', () => this.showFormatTab('markdown'));
        
        // Download menu items
        document.addEventListener('click', (e) => {
            if (e.target.matches('.dropdown-item')) {
                const format = e.target.getAttribute('data-format');
                this.downloadResults(format);
                this.hideDownloadMenu();
            }
            
            // Close dropdown when clicking outside
            if (!e.target.closest('.download-dropdown')) {
                this.hideDownloadMenu();
            }
        });
        
        // Keyboard shortcuts
        document.addEventListener('keydown', (e) => this.handleKeyboardShortcuts(e));
        
        // Window beforeunload
        window.addEventListener('beforeunload', (e) => this.handlePageUnload(e));
    }

    /**
     * Setup advanced options event listeners
     */
    setupAdvancedOptionsListeners() {
        const sliders = [
            'maxQueries', 'maxSearchs', 'maxIteration', 'maxTokens', 'rerankThreshold'
        ];
        
        sliders.forEach(sliderId => {
            const slider = document.getElementById(sliderId);
            const valueDisplay = document.getElementById(`${sliderId}Value`);
            
            slider.addEventListener('input', () => {
                valueDisplay.textContent = slider.value;
                this.savePreferences();
            });
        });
        
        // Checkboxes
        const removeThinkingCheckbox = document.getElementById('removeThinkingToken');
        removeThinkingCheckbox.addEventListener('change', () => this.savePreferences());
        
        const interactiveCheckbox = document.getElementById('interactiveMode');
        interactiveCheckbox.addEventListener('change', () => this.savePreferences());
    }

    /**
     * Setup form validation
     */
    setupFormValidation() {
        const topicInput = document.getElementById('researchTopic');
        const charCount = document.getElementById('charCount');
        
        topicInput.addEventListener('input', () => {
            const length = topicInput.value.length;
            charCount.textContent = length;
            
            // Update character count color
            if (length > 900) {
                charCount.style.color = 'var(--error-color)';
            } else if (length > 700) {
                charCount.style.color = 'var(--warning-color)';
            } else {
                charCount.style.color = 'var(--text-muted)';
            }
        });
    }

    /**
     * Populate advanced options with default values
     */
    populateAdvancedOptions() {
        if (!this.defaultConfig) return;
        
        document.getElementById('maxQueries').value = this.defaultConfig.max_queries;
        document.getElementById('maxQueriesValue').textContent = this.defaultConfig.max_queries;
        
        document.getElementById('maxSearchs').value = this.defaultConfig.max_searchs;
        document.getElementById('maxSearchsValue').textContent = this.defaultConfig.max_searchs;
        
        document.getElementById('maxIteration').value = this.defaultConfig.max_iteration;
        document.getElementById('maxIterationValue').textContent = this.defaultConfig.max_iteration;
        
        document.getElementById('maxTokens').value = this.defaultConfig.max_completion_token;
        document.getElementById('maxTokensValue').textContent = this.defaultConfig.max_completion_token;
        
        document.getElementById('rerankThreshold').value = this.defaultConfig.rerank_score_threshold;
        document.getElementById('rerankThresholdValue').textContent = this.defaultConfig.rerank_score_threshold;
        
        document.getElementById('removeThinkingToken').checked = this.defaultConfig.remove_thinking_token;
        document.getElementById('interactiveMode').checked = this.defaultConfig.interactive;
    }

    /**
     * Toggle advanced options panel
     */
    toggleAdvancedOptions() {
        const toggle = document.getElementById('advancedToggle');
        const options = document.getElementById('advancedOptions');
        
        if (options.classList.contains('open')) {
            options.classList.remove('open');
            toggle.classList.remove('active');
        } else {
            options.classList.add('open');
            toggle.classList.add('active');
        }
    }

    /**
     * Validate research topic
     */
    async validateTopic() {
        const topicInput = document.getElementById('researchTopic');
        const validation = document.getElementById('topicValidation');
        const topic = topicInput.value.trim();
        
        if (!topic) {
            validation.style.display = 'none';
            return false;
        }
        
        if (topic.length < 3) {
            this.showTopicValidation('Topic must be at least 3 characters long', 'error');
            return false;
        }
        
        if (topic.length > 1000) {
            this.showTopicValidation('Topic is too long (maximum 1000 characters)', 'error');
            return false;
        }
        
        try {
            // Add timeout to prevent blocking UI
            const timeoutPromise = new Promise((_, reject) => {
                setTimeout(() => reject(new Error('Validation timeout')), 3000);
            });
            
            const validationPromise = fetch('/api/research/validate-topic', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ topic })
            });
            
            const response = await Promise.race([validationPromise, timeoutPromise]);
            const result = await response.json();
            
            if (result.valid) {
                this.showTopicValidation('Topic is valid and ready for research', 'success');
                return true;
            } else {
                this.showTopicValidation(result.message, 'error');
                return false;
            }
        } catch (error) {
            if (error.message === 'Validation timeout') {
                console.warn('Topic validation timed out, proceeding anyway');
                // Hide validation message on timeout
                document.getElementById('topicValidation').style.display = 'none';
            } else {
                console.error('Topic validation error:', error);
            }
            return true; // Allow if validation fails or times out
        }
    }

    /**
     * Show topic validation message
     */
    showTopicValidation(message, type) {
        const validation = document.getElementById('topicValidation');
        validation.textContent = message;
        validation.className = `topic-validation ${type}`;
        validation.style.display = 'block';
    }

    /**
     * Start research process
     */
    async startResearch() {
        const topic = document.getElementById('researchTopic').value.trim();
        
        if (!topic) {
            this.showNotification('Please enter a research topic', 'error');
            return;
        }
        
        // IMMEDIATE UI FEEDBACK: Show loading state right away
        this.showLoading(true);
        this.showNotification('Preparing research...', 'info');
        
        // Clear any previous answered questions for fresh session
        this.answeredQuestions.clear();
        
        // Reset progress state for new research session
        this.resetProgressState();
        
        try {
            // Basic client-side validation first (no API calls)
            if (topic.length < 3) {
                throw new Error('Topic must be at least 3 characters long');
            }
            if (topic.length > 1000) {
                throw new Error('Topic is too long (maximum 1000 characters)');
            }
            
            // Prepare research request
            const config = this.getResearchConfig();
            const request = {
                topic: topic,
                config: config
            };
            
            // Start research (backend will handle validation)
            const response = await fetch('/api/research/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(request)
            });
            
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.message || 'Failed to start research');
            }
            
            const result = await response.json();
            this.currentSession = result;
            this.startTime = new Date();
            
            // Setup WebSocket connection
            this.connectWebSocket(result.session_id);
            
            // Update UI
            this.showSection('progressSection');
            this.updateProgressUI('Initializing research...', 0, 'initialization');
            
            // Initialize persistent details with research topic
            this.progressState.lastKnownDetails.topic = topic;
            this.progressState.lastKnownDetails.current_iteration = null;  // Will be updated by backend
            this.progressState.lastKnownDetails.total_iterations = config.max_iteration;
            this.progressState.lastKnownDetails.results = 0;
            this.updateProgressDetails(topic, null, config.max_iteration, 0);
            
            // Enable cancel button
            document.getElementById('cancelResearchBtn').style.display = 'inline-flex';
            document.getElementById('startResearchBtn').style.display = 'none';
            
            this.showNotification('Research started successfully', 'success');
            
        } catch (error) {
            console.error('Start research error:', error);
            this.showNotification(error.message || 'Failed to start research', 'error');
            
            // Reset UI on error
            this.showSection('researchFormSection');
        } finally {
            this.showLoading(false);
        }
    }

    /**
     * Cancel current research
     */
    async cancelResearch() {
        console.debug('Cancel button pressed - cancelResearch() called');
        
        if (!this.currentSession) {
            console.debug('No current session, cancellation aborted');
            return;
        }
        
        console.debug('Current session found:', this.currentSession.session_id);
        
        const confirmed = confirm('Are you sure you want to cancel the current research?');
        console.debug('User confirmation result:', confirmed);
        
        if (!confirmed) {
            console.debug('User cancelled the cancellation dialog');
            return;
        }
        
        // Immediate UI feedback - show cancellation in progress
        console.debug('Showing cancellation in progress UI');
        this.showCancellationInProgress();
        
        try {
            // Set a timeout for the cancel operation (maximum 5 seconds)
            const cancelTimeout = 5000; // 5 seconds
            console.debug('Setting up cancel request with', cancelTimeout, 'ms timeout');
            
            const timeoutPromise = new Promise((_, reject) => {
                setTimeout(() => reject(new Error('Cancel request timed out')), cancelTimeout);
            });
            
            // Make the cancel request with timeout protection
            console.debug('Making DELETE request to /api/research/' + this.currentSession.session_id);
            const cancelPromise = fetch(`/api/research/${this.currentSession.session_id}`, {
                method: 'DELETE'
            });
            
            // Race between the cancel request and timeout
            console.debug('Racing cancel request against timeout');
            const response = await Promise.race([cancelPromise, timeoutPromise]);
            
            if (response.ok) {
                console.debug('Cancel request successful, response OK');
                this.showNotification('Research cancelled successfully', 'info');
                this.resetToForm();
            } else {
                console.debug('Cancel request failed with status:', response.status);
                const error = await response.json();
                console.debug('Cancel request error response:', error);
                throw new Error(error.message || 'Failed to cancel research');
            }
        } catch (error) {
            console.debug('Cancel request caught error:', error.message);
            
            if (error.message === 'Cancel request timed out') {
                console.debug('Cancel request timed out, assuming success');
                // If timeout occurred, assume cancellation was successful from user perspective
                // Clear loading state even when cancellation times out
                this.showLoading(false);
                this.showNotification('Research cancellation initiated - stopping in progress', 'info');
                this.resetToForm();
                
                // Send WebSocket cancel message as backup
                console.debug('Attempting WebSocket cancel backup');
                if (this.websocket && this.websocket.readyState === WebSocket.OPEN) {
                    try {
                        this.websocket.send(JSON.stringify({
                            type: 'cancel_request'
                        }));
                        console.debug('WebSocket cancel backup sent successfully');
                    } catch (wsError) {
                        console.debug('WebSocket cancel backup failed:', wsError);
                    }
                } else {
                    console.debug('WebSocket not available for cancel backup');
                }
            } else {
                console.error('Cancel research error (non-timeout):', error);
                this.showNotification(error.message || 'Failed to cancel research', 'error');
                this.hideCancellationInProgress();
            }
        }
    }

    /**
     * Show cancellation in progress UI feedback
     */
    showCancellationInProgress() {
        console.debug('showCancellationInProgress() called');
        
        // Update cancel buttons to show "Cancelling..." state
        const cancelBtns = [
            document.getElementById('cancelResearchBtn'),
            document.getElementById('cancelProgressBtn')
        ];
        
        cancelBtns.forEach((btn, index) => {
            const btnName = index === 0 ? 'cancelResearchBtn' : 'cancelProgressBtn';
            console.debug(`Processing ${btnName}, display: ${btn ? btn.style.display : 'null'}, exists: ${!!btn}`);
            
            if (btn && btn.style.display !== 'none') {
                // Defensive check: don't re-process if already cancelling
                if (!btn.classList.contains('cancelling')) {
                    console.debug(`Setting ${btnName} to cancelling state`);
                    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Cancelling...';
                    btn.disabled = true;
                    btn.classList.add('cancelling');
                } else {
                    console.debug(`${btnName} already in cancelling state`);
                }
            } else {
                console.debug(`${btnName} not visible or doesn't exist`);
            }
        });
        
        // Update progress message
        const stageMessage = document.getElementById('stageMessage');
        if (stageMessage && !stageMessage.textContent.includes('Cancelling')) {
            stageMessage.textContent = 'Cancelling research operation...';
        }
        
        // Update stage title and icon
        const stageTitle = document.getElementById('stageTitle');
        const stageIcon = document.getElementById('stageIcon');
        if (stageTitle && !stageTitle.textContent.includes('Cancelling')) {
            stageTitle.textContent = 'Cancelling Research';
        }
        if (stageIcon && !stageIcon.innerHTML.includes('stop-circle')) {
            stageIcon.innerHTML = '<i class="fas fa-stop-circle"></i>';
        }
    }

    /**
     * Hide cancellation in progress UI feedback
     */
    hideCancellationInProgress() {
        console.debug('hideCancellationInProgress() called');
        
        // Restore cancel buttons to normal state
        const cancelBtns = [
            document.getElementById('cancelResearchBtn'),
            document.getElementById('cancelProgressBtn')
        ];
        
        cancelBtns.forEach((btn, index) => {
            const btnName = index === 0 ? 'cancelResearchBtn' : 'cancelProgressBtn';
            console.debug(`Restoring ${btnName} to normal state`);
            
            if (btn) {
                btn.innerHTML = '<i class="fas fa-stop"></i> Cancel Research';
                btn.disabled = false;
                btn.classList.remove('cancelling');
                console.debug(`${btnName} restored to normal state`);
            } else {
                console.debug(`${btnName} not found for restoration`);
            }
        });
    }

    /**
     * Get research configuration from form
     */
    getResearchConfig() {
        return {
            max_queries: parseInt(document.getElementById('maxQueries').value),
            max_searchs: parseInt(document.getElementById('maxSearchs').value),
            max_iteration: parseInt(document.getElementById('maxIteration').value),
            max_completion_token: parseInt(document.getElementById('maxTokens').value),
            rerank_score_threshold: parseFloat(document.getElementById('rerankThreshold').value),
            remove_thinking_token: document.getElementById('removeThinkingToken').checked,
            interactive: document.getElementById('interactiveMode').checked,
            use_async: true // Always use async for better performance
        };
    }

    /**
     * Connect to WebSocket for progress updates
     */
    connectWebSocket(sessionId) {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/${sessionId}`;
        
        this.websocket = new WebSocket(wsUrl);
        
        this.websocket.onopen = () => {
            console.debug('WebSocket connected');
        };
        
        this.websocket.onmessage = (event) => {
            try {
                const message = JSON.parse(event.data);
                this.handleWebSocketMessage(message);
            } catch (error) {
                console.error('WebSocket message parse error:', error);
            }
        };
        
        this.websocket.onclose = (event) => {
            console.debug('WebSocket closed:', event.code, event.reason);
            if (this.currentSession && this.currentSession.status !== 'completed') {
                // Try to reconnect if research is still ongoing
                this.reconnectionTimer = setTimeout(() => {
                    if (this.currentSession) {
                        this.connectWebSocket(sessionId);
                    }
                }, 5000);
            }
        };
        
        this.websocket.onerror = (error) => {
            console.error('WebSocket error:', error);
        };
    }

    /**
     * Handle WebSocket messages
     */
    handleWebSocketMessage(message) {
        switch (message.type) {
            case 'progress_update':
                this.handleProgressUpdate(message.data);
                break;
            case 'session_update':
                this.handleSessionUpdate(message.data);
                break;
            case 'initial_status':
                this.handleInitialStatus(message.data);
                break;
            case 'cancellation_confirmed':
                this.handleCancellationConfirmed();
                break;
            case 'error':
                this.showNotification(message.data.message, 'error');
                break;
            // Interactive Q&A message handlers
            case 'clarification_start':
                console.debug('Received clarification_start message:', message.data);
                this.handleClarificationStart(message.data);
                break;
            case 'clarification_question':
                console.debug('Received clarification_question message:', message.data);
                this.handleClarificationQuestion(message.data);
                break;
            case 'clarification_complete':
                console.debug('Received clarification_complete message:', message.data);
                this.handleClarificationComplete(message.data);
                break;
            case 'answer_received':
                console.debug('Received answer_received message:', message.data);
                this.handleAnswerReceived(message.data);
                break;
            default:
                console.debug('Unknown WebSocket message type:', message.type);
        }
    }

    /**
     * Handle progress updates
     */
    handleProgressUpdate(data) {
        const progress = Math.round(data.progress * 100);
        this.updateProgressUI(data.message, progress, data.stage);
        
        // Merge incoming details with persistent state
        this.mergeProgressDetails(data.details);
        
        // Always update details display with persistent values
        const persistentDetails = this.progressState.lastKnownDetails;
        this.updateProgressDetails(
            persistentDetails.topic || this.currentSession?.topic || '-',
            persistentDetails.current_iteration || '-',
            persistentDetails.total_iterations || '-',
            persistentDetails.results || '-'
        );
    }

    /**
     * Merge progress details with persistent state (prevents intermittent "-" values)
     */
    mergeProgressDetails(incomingDetails) {
        if (!incomingDetails) {
            // No incoming details - keep existing persistent values
            return;
        }
        
        const persistent = this.progressState.lastKnownDetails;
        
        // Extract current iteration from various possible field names
        const current_iteration = incomingDetails.current_iteration || 
                                 incomingDetails.iteration || 
                                 incomingDetails.iteration_number;
        
        // Extract total iterations
        const total_iterations = incomingDetails.total_iterations;
        
        // Extract results from various possible field names  
        const results = incomingDetails.total_results || 
                       incomingDetails.results_found || 
                       incomingDetails.filtered_results ||
                       incomingDetails.search_results;
        
        // Extract topic
        const topic = incomingDetails.topic || incomingDetails.current_topic;
        
        // STICKY DETAILS LOGIC: Only update if we have valid new values (with validation)
        const validatedCurrentIteration = this.validateDetailValue(current_iteration, 'iteration');
        if (validatedCurrentIteration !== null) {
            persistent.current_iteration = validatedCurrentIteration;
        }
        
        const validatedTotalIterations = this.validateDetailValue(total_iterations, 'iteration');
        if (validatedTotalIterations !== null) {
            persistent.total_iterations = validatedTotalIterations;
        }
        
        const validatedResults = this.validateDetailValue(results, 'results');
        if (validatedResults !== null) {
            persistent.results = validatedResults;
        }
        
        const validatedTopic = this.validateDetailValue(topic, 'topic');
        if (validatedTopic !== null) {
            persistent.topic = validatedTopic;
        }
        
        // Debug logging for detail persistence tracking
        console.debug('Detail persistence update:', {
            incoming: incomingDetails,
            persistent: persistent,
            extracted: { 
                current_iteration, 
                total_iterations, 
                results, 
                topic,
                validated_current: validatedCurrentIteration,
                validated_total: validatedTotalIterations,
                validated_results: validatedResults
            }
        });
    }

    /**
     * Validate and sanitize detail values to prevent invalid display
     */
    validateDetailValue(value, fieldName) {
        // Handle null, undefined, empty string cases
        if (value === null || value === undefined || value === '') {
            return null;
        }
        
        // Handle numeric fields (iteration, results)
        if (fieldName === 'iteration' || fieldName === 'results') {
            const numValue = parseInt(value);
            if (isNaN(numValue) || numValue < 0) {
                console.warn(`Invalid ${fieldName} value:`, value);
                return null;
            }
            return numValue;
        }
        
        // Handle string fields (topic)
        if (fieldName === 'topic') {
            const strValue = String(value).trim();
            if (strValue.length === 0 || strValue === '-') {
                return null;
            }
            return strValue;
        }
        
        return value;
    }

    /**
     * Handle session updates
     */
    handleSessionUpdate(data) {
        if (data.status) {
            const session = data.status;
            
            if (session.status === 'completed' && session.result) {
                this.handleResearchCompleted(session);
            } else if (session.status === 'failed') {
                this.handleResearchFailed(session.error_message);
            } else if (session.status === 'cancelled') {
                this.handleCancellationConfirmed();
            }
        }
    }

    /**
     * Handle initial status
     */
    handleInitialStatus(data) {
        const session = data.status;
        
        if (session.status === 'completed' && session.result) {
            this.handleResearchCompleted(session);
        } else if (session.status === 'failed') {
            this.handleResearchFailed(session.error_message);
        }
    }

    /**
     * Handle research completion
     */
    handleResearchCompleted(session) {
        this.currentSession = session;
        
        // Close WebSocket
        if (this.websocket) {
            this.websocket.close();
            this.websocket = null;
        }
        
        // Show results
        this.showSection('resultsSection');
        this.displayResults(session);
        
        this.showNotification('Research completed successfully!', 'success');
    }

    /**
     * Handle research failure
     */
    handleResearchFailed(errorMessage) {
        // Close WebSocket
        if (this.websocket) {
            this.websocket.close();
            this.websocket = null;
        }
        
        // Show error
        this.showSection('errorSection');
        document.getElementById('errorMessage').textContent = 
            errorMessage || 'An unexpected error occurred during research';
        
        this.showNotification('Research failed', 'error');
    }

    /**
     * Handle cancellation confirmation
     */
    handleCancellationConfirmed() {
        console.debug('handleCancellationConfirmed() called - WebSocket cancellation confirmed');
        
        // Clear loading overlay immediately
        console.debug('Clearing loading overlay');
        this.showLoading(false);
        
        // Ensure cancellation UI state is properly hidden first
        console.debug('Hiding cancellation in progress UI');
        this.hideCancellationInProgress();
        
        // Then reset to form state
        console.debug('Resetting to form state');
        this.resetToForm();
        this.showNotification('Research cancelled', 'info');
        console.debug('Cancellation confirmation handling complete');
    }

    /**
     * Update progress UI with enhanced debouncing and smoothing
     */
    updateProgressUI(message, progress, stage) {
        // Progress update with debouncing and validation
        this.enqueueProgressUpdate(message, progress, stage);
    }

    /**
     * Enqueue progress update for debounced processing
     */
    enqueueProgressUpdate(message, progress, stage) {
        const now = Date.now();
        const newUpdate = {
            message,
            progress: Math.max(0, Math.min(100, progress)), // Clamp between 0-100
            stage,
            timestamp: now
        };
        
        // Validate progress (ensure forward movement only)
        if (this.validateProgressUpdate(newUpdate)) {
            // Add to pending updates
            this.progressState.pendingUpdates.push(newUpdate);
            
            // Process updates with debouncing
            this.processProgressUpdates();
        }
    }

    /**
     * Validate progress update to prevent backward movement
     */
    validateProgressUpdate(update) {
        // Skip validation for certain stages that might legitimately reset
        const resetStages = ['initialization', 'cancelling', 'error'];
        if (resetStages.includes(update.stage)) {
            return true;
        }
        
        // Validate the incoming progress value
        // Ensure progress only moves forward (with tolerance for rounding and stage transitions)
        const tolerance = 0.5; // percent
        if (update.progress < this.progressState.currentProgress - tolerance) {
            console.warn('Progress validation failed: backward movement detected', {
                current: this.progressState.currentProgress,
                new: update.progress,
                stage: update.stage,
                message: update.message
            });
            return false;
        }
        
        // Allow completion updates (100%) regardless of increment size
        if (update.progress >= 100) {
            return true;
        }
        
        // Skip updates that are too small to be meaningful (but allow stage changes)
        const minIncrement = this.progressConfig.minProgressIncrement;
        const progressDiff = update.progress - this.progressState.currentProgress;
        
        // Allow updates if stage has changed (even with small progress increment)  
        const stageChanged = update.stage !== this.progressState.currentStage;
        if (progressDiff < minIncrement && !stageChanged) {
            return false;
        }
        
        // Additional validation: prevent progress jumps that are too large
        const maxJump = 15; // Maximum 15% progress jump at once (prevents unrealistic leaps)
        if (progressDiff > maxJump && update.progress < 100) {
            console.warn('Progress validation: Large jump detected, capping increment', {
                current: this.progressState.currentProgress,
                requested: update.progress,
                diff: progressDiff,
                stage: update.stage
            });
            // Cap the progress to prevent unrealistic jumps
            update.progress = this.progressState.currentProgress + maxJump;
        }
        
        return true;
    }

    /**
     * Process pending progress updates with debouncing
     */
    processProgressUpdates() {
        const now = Date.now();
        const timeSinceLastUpdate = now - this.progressState.lastUpdateTime;
        const minInterval = 1000 / this.progressConfig.maxUpdatesPerSecond;
        
        if (timeSinceLastUpdate < minInterval && this.progressState.pendingUpdates.length === 1) {
            // Debounce: wait for minimum interval
            if (!this.progressUpdateTimer) {
                this.progressUpdateTimer = setTimeout(() => {
                    this.processProgressUpdates();
                    this.progressUpdateTimer = null;
                }, minInterval - timeSinceLastUpdate);
            }
            return;
        }
        
        // Get the latest update from pending queue
        if (this.progressState.pendingUpdates.length === 0) {
            return;
        }
        
        const latestUpdate = this.progressState.pendingUpdates[this.progressState.pendingUpdates.length - 1];
        this.progressState.pendingUpdates = []; // Clear queue
        
        // Apply the update
        this.applyProgressUpdate(latestUpdate);
        this.progressState.lastUpdateTime = now;
    }

    /**
     * Apply progress update to DOM with smooth animation
     */
    applyProgressUpdate(update) {
        // Update internal state
        this.progressState.currentProgress = update.progress;
        this.progressState.currentStage = update.stage;
        this.progressState.currentMessage = update.message;
        
        // Apply smooth transition if enabled
        if (this.progressConfig.smoothingEnabled) {
            this.animateProgressTransition(update);
        } else {
            this.setProgressValues(update);
        }
        
        // Update stage information immediately (no smoothing needed)
        const stageInfo = this.getStageInfo(update.stage);
        document.getElementById('stageTitle').textContent = stageInfo.title;
        document.getElementById('stageIcon').innerHTML = stageInfo.icon;
        document.getElementById('stageMessage').textContent = update.message;
    }

    /**
     * Animate smooth progress transition
     */
    animateProgressTransition(targetUpdate) {
        if (this.progressState.isAnimating) {
            // Cancel previous animation
            if (this.progressAnimationFrame) {
                cancelAnimationFrame(this.progressAnimationFrame);
            }
        }
        
        this.progressState.isAnimating = true;
        const startProgress = this.progressState.displayedProgress;
        const endProgress = targetUpdate.progress;
        const startTime = performance.now();
        const duration = Math.abs(endProgress - startProgress) * 20; // 20ms per percentage point
        
        const animate = (currentTime) => {
            const elapsed = currentTime - startTime;
            const progress = Math.min(elapsed / duration, 1);
            
            // Use ease-out function for smooth deceleration
            const easeOut = 1 - Math.pow(1 - progress, 3);
            const currentValue = startProgress + (endProgress - startProgress) * easeOut;
            
            this.progressState.displayedProgress = currentValue;
            this.setProgressValues({
                ...targetUpdate,
                progress: currentValue
            });
            
            if (progress < 1) {
                this.progressAnimationFrame = requestAnimationFrame(animate);
            } else {
                this.progressState.isAnimating = false;
                this.progressState.displayedProgress = endProgress;
                this.progressAnimationFrame = null;
            }
        };
        
        this.progressAnimationFrame = requestAnimationFrame(animate);
    }

    /**
     * Set progress values in DOM
     */
    setProgressValues(update) {
        const progressFill = document.getElementById('progressFill');
        const progressPercentage = document.getElementById('progressPercentage');
        
        if (progressFill) {
            progressFill.style.width = `${update.progress}%`;
        }
        
        if (progressPercentage) {
            progressPercentage.textContent = `${Math.round(update.progress)}%`;
        }
    }

    /**
     * Reset progress state (called when starting new research)
     */
    resetProgressState() {
        // Cancel any ongoing animations
        if (this.progressAnimationFrame) {
            cancelAnimationFrame(this.progressAnimationFrame);
            this.progressAnimationFrame = null;
        }
        
        // Clear timers
        if (this.progressUpdateTimer) {
            clearTimeout(this.progressUpdateTimer);
            this.progressUpdateTimer = null;
        }
        
        // Reset state
        this.progressState = {
            currentProgress: 0,
            displayedProgress: 0,
            currentStage: '',
            currentMessage: '',
            lastUpdateTime: 0,
            pendingUpdates: [],
            isAnimating: false,
            // Reset detail tracking for new research session
            lastKnownDetails: {
                current_iteration: null,
                total_iterations: null,
                results: null,
                topic: null
            }
        };
    }

    /**
     * Get stage information
     */
    getStageInfo(stage) {
        const stages = {
            initialization: {
                title: 'Initializing Research',
                icon: '<i class="fas fa-cog fa-spin"></i>'
            },
            clarification: {
                title: 'Interactive Clarification',
                icon: '<i class="fas fa-question-circle"></i>'
            },
            query_generation: {
                title: 'Generating Search Queries',
                icon: '<i class="fas fa-brain"></i>'
            },
            search: {
                title: 'Searching Information',
                icon: '<i class="fas fa-search fa-spin"></i>'
            },
            evaluation: {
                title: 'Evaluating Results',
                icon: '<i class="fas fa-analyze-chart"></i>'
            },
            additional_search: {
                title: 'Additional Search',
                icon: '<i class="fas fa-search-plus fa-spin"></i>'
            },
            filtering: {
                title: 'Filtering & Ranking',
                icon: '<i class="fas fa-filter"></i>'
            },
            report_generation: {
                title: 'Generating Report',
                icon: '<i class="fas fa-file-alt fa-spin"></i>'
            },
            complete: {
                title: 'Research Complete',
                icon: '<i class="fas fa-check"></i>'
            }
        };
        
        return stages[stage] || {
            title: 'Processing',
            icon: '<i class="fas fa-spinner fa-spin"></i>'
        };
    }

    /**
     * Update progress details
     */
    updateProgressDetails(topic, current_iteration, total_iterations, results) {
        console.debug('updateProgressDetails called with:', { topic, current_iteration, total_iterations, results });
        
        document.getElementById('currentTopic').textContent = topic;
        
        // Display iteration in "X/Y" format - handle both null and numeric values properly  
        if (current_iteration !== null && current_iteration !== '-' && current_iteration !== undefined &&
            total_iterations !== null && total_iterations !== '-' && total_iterations !== undefined) {
            // Convert to numbers and display properly
            const current = parseInt(current_iteration, 10);
            const total = parseInt(total_iterations, 10);
            if (!isNaN(current) && !isNaN(total)) {
                const iterationText = `${current}/${total}`;
                document.getElementById('currentIteration').textContent = iterationText;
                console.debug('Setting iteration display to:', iterationText);
            } else {
                document.getElementById('currentIteration').textContent = '-';
                console.debug('Setting iteration display to "-" due to NaN values:', { current, total });
            }
        } else {
            document.getElementById('currentIteration').textContent = '-';
            console.debug('Setting iteration display to "-" due to null/undefined values');
        }
        
        document.getElementById('resultsFound').textContent = results !== null && results !== undefined ? results : '-';
    }

    /**
     * Display research results
     */
    displayResults(session) {
        // Update summary
        document.getElementById('resultTopic').textContent = session.topic;
        document.getElementById('completedTime').textContent = 
            new Date(session.completed_at).toLocaleString();
        
        if (this.startTime) {
            const duration = new Date(session.completed_at) - this.startTime;
            document.getElementById('processingTime').textContent = 
                this.formatDuration(duration);
        }
        
        // Store the raw markdown content
        this.rawMarkdownContent = session.result;
        
        // Render HTML content
        // The report is model output built from web pages, so strip scripts and event handlers
        const renderedContent = DOMPurify.sanitize(marked.parse(session.result));
        document.getElementById('researchContentRendered').innerHTML = renderedContent;
        
        // Display raw markdown content with syntax highlighting
        document.getElementById('markdownSource').textContent = session.result;
        
        // Apply syntax highlighting
        if (window.Prism) {
            Prism.highlightElement(document.getElementById('markdownSource'));
        }
        
        // Reset to rendered view
        this.showFormatTab('rendered');
        
        // Scroll to top of results
        document.getElementById('resultsSection').scrollIntoView({
            behavior: 'smooth'
        });
    }

    /**
     * Format duration in human readable format
     */
    formatDuration(ms) {
        const seconds = Math.floor(ms / 1000);
        const minutes = Math.floor(seconds / 60);
        const hours = Math.floor(minutes / 60);
        
        if (hours > 0) {
            return `${hours}h ${minutes % 60}m ${seconds % 60}s`;
        } else if (minutes > 0) {
            return `${minutes}m ${seconds % 60}s`;
        } else {
            return `${seconds}s`;
        }
    }

    /**
     * Download research results in specified format
     */
    downloadResults(format = 'markdown') {
        if (!this.currentSession || !this.currentSession.result) {
            this.showNotification('No results to download', 'error');
            return;
        }
        
        const baseName = this.createSafeFilename(this.currentSession.topic);
        let content, filename, mimeType;
        
        switch (format) {
            case 'markdown':
                content = this.currentSession.result;
                filename = `${baseName}.md`;
                mimeType = 'text/markdown';
                break;
                
            case 'txt':
                // Convert markdown to plain text (simple conversion)
                content = this.markdownToText(this.currentSession.result);
                filename = `${baseName}.txt`;
                mimeType = 'text/plain';
                break;
                
            case 'json':
                // Create JSON structure with metadata
                const jsonData = {
                    topic: this.currentSession.topic,
                    completed_at: this.currentSession.completed_at,
                    config: this.currentSession.config,
                    result: this.currentSession.result,
                    format: 'markdown',
                    generated_by: 'Deep Research'
                };
                content = JSON.stringify(jsonData, null, 2);
                filename = `${baseName}.json`;
                mimeType = 'application/json';
                break;
                
            case 'pdf':
                this.downloadPDF(baseName);
                return;
                
            default:
                this.showNotification('Unsupported format', 'error');
                return;
        }
        
        const blob = new Blob([content], { type: mimeType });
        const url = URL.createObjectURL(blob);
        
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        
        this.showNotification(`Downloaded as ${format.toUpperCase()}`, 'success');
    }

    /**
     * Create safe filename from topic
     */
    createSafeFilename(topic) {
        return topic
            .toLowerCase()
            .replace(/[^\w\s-]/g, '_')
            .replace(/[\s_]+/g, '_')
            .replace(/^_+|_+$/g, '')
            .substring(0, 100);
    }

    /**
     * Convert markdown to plain text (simple implementation)
     */
    markdownToText(markdown) {
        return markdown
            // Remove headers
            .replace(/^#{1,6}\s+/gm, '')
            // Remove bold/italic
            .replace(/\*\*(.+?)\*\*/g, '$1')
            .replace(/\*(.+?)\*/g, '$1')
            .replace(/__(.+?)__/g, '$1')
            .replace(/_(.+?)_/g, '$1')
            // Remove links but keep text
            .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
            // Remove code blocks
            .replace(/```[\s\S]*?```/g, '')
            .replace(/`([^`]+)`/g, '$1')
            // Remove blockquotes
            .replace(/^>\s+/gm, '')
            // Clean up multiple newlines
            .replace(/\n{3,}/g, '\n\n')
            .trim();
    }

    /**
     * Download as PDF using jsPDF
     */
    downloadPDF(baseName) {
        // The jsPDF UMD build exposes window.jspdf (lower case)
        if (!window.jspdf) {
            this.showNotification('PDF generation not available', 'error');
            return;
        }

        try {
            const doc = new window.jspdf.jsPDF();
            let y = 20;
            // Wrap to the page width and start a new page when the text reaches the bottom
            const write = (text, fontSize, lineHeight) => {
                doc.setFontSize(fontSize);
                for (const line of doc.splitTextToSize(text, 170)) {
                    if (y > 280) {
                        doc.addPage();
                        y = 20;
                    }
                    doc.text(line, 20, y);
                    y += lineHeight;
                }
            };

            write(this.currentSession.topic, 16, 8);
            write(`Generated: ${new Date(this.currentSession.completed_at).toLocaleString()}`, 10, 6);
            y += 6;
            write(this.markdownToText(this.currentSession.result), 12, 6);

            doc.save(`${baseName}.pdf`);
            this.showNotification('Downloaded as PDF', 'success');
        } catch (error) {
            console.error('PDF generation failed:', error);
            this.showNotification('PDF generation failed', 'error');
        }
    }

    /**
     * Toggle download menu visibility
     */
    toggleDownloadMenu() {
        const dropdown = document.querySelector('.download-dropdown');
        dropdown.classList.toggle('active');
    }

    /**
     * Hide download menu
     */
    hideDownloadMenu() {
        const dropdown = document.querySelector('.download-dropdown');
        dropdown.classList.remove('active');
    }

    /**
     * Show specific format tab
     */
    showFormatTab(format) {
        // Update tab buttons
        document.querySelectorAll('.format-tab').forEach(tab => {
            tab.classList.remove('active');
        });
        document.getElementById(format === 'rendered' ? 'renderedTab' : 'markdownTab').classList.add('active');
        
        // Update content display
        const renderedContent = document.getElementById('researchContentRendered');
        const markdownContent = document.getElementById('researchContentMarkdown');
        
        if (format === 'rendered') {
            renderedContent.classList.add('active');
            markdownContent.classList.remove('active');
        } else {
            renderedContent.classList.remove('active');
            markdownContent.classList.add('active');
        }
    }

    /**
     * Copy current content to clipboard
     */
    async copyToClipboard() {
        if (!this.currentSession || !this.currentSession.result) {
            this.showNotification('No content to copy', 'error');
            return;
        }

        try {
            // Get the currently active format
            const isMarkdownView = document.getElementById('markdownTab').classList.contains('active');
            const content = isMarkdownView ? this.currentSession.result : this.markdownToText(this.currentSession.result);
            
            await navigator.clipboard.writeText(content);
            
            // Show visual feedback
            const copyBtn = document.getElementById('copyToClipboardBtn');
            copyBtn.classList.add('copy-success');
            setTimeout(() => {
                copyBtn.classList.remove('copy-success');
            }, 2000);
            
            this.showNotification('Copied to clipboard', 'success');
        } catch (error) {
            console.error('Copy failed:', error);
            this.showNotification('Copy failed', 'error');
        }
    }

    /**
     * Start new research
     */
    startNewResearch() {
        this.resetToForm();
        document.getElementById('researchTopic').focus();
    }

    /**
     * Retry failed research
     */
    retryResearch() {
        this.resetToForm();
        // Auto-fill with previous topic if available
        if (this.currentSession && this.currentSession.topic) {
            document.getElementById('researchTopic').value = this.currentSession.topic;
        }
    }

    /**
     * Reset to form state
     */
    resetToForm() {
        // Clear loading overlay FIRST before any other UI changes
        this.showLoading(false);
        
        // Reset progress state when resetting to form
        this.resetProgressState();
        
        // ENHANCED WEBSOCKET CLEANUP: Force immediate closure and prevent reconnections
        if (this.websocket) {
            // Remove event listeners to prevent reconnection attempts
            this.websocket.onclose = null;
            this.websocket.onerror = null;
            this.websocket.onmessage = null;
            
            // Force close if not already closed
            if (this.websocket.readyState === WebSocket.OPEN || 
                this.websocket.readyState === WebSocket.CONNECTING) {
                this.websocket.close(1000, 'Session reset');
            }
            
            this.websocket = null;
        }
        
        // Clear any pending reconnection timers
        if (this.reconnectionTimer) {
            clearTimeout(this.reconnectionTimer);
            this.reconnectionTimer = null;
        }
        
        // Reset session immediately (prevents conflicts with new sessions)
        this.currentSession = null;
        this.startTime = null;
        
        // Reset UI
        this.showSection('researchFormSection');
        document.getElementById('startResearchBtn').style.display = 'inline-flex';
        document.getElementById('cancelResearchBtn').style.display = 'none';
        
        // Reset cancel button states properly
        const cancelBtns = [
            document.getElementById('cancelResearchBtn'),
            document.getElementById('cancelProgressBtn')
        ];
        
        cancelBtns.forEach(btn => {
            if (btn) {
                // Reset button content and state
                btn.innerHTML = '<i class="fas fa-stop"></i> Cancel Research';
                btn.disabled = false;
                btn.classList.remove('cancelling');
            }
        });
        
        // DEFENSIVE UI RESET: Clear all progress content and stage information
        document.getElementById('progressFill').style.width = '0%';
        document.getElementById('progressPercentage').textContent = '0%';
        
        // Clear stage information that might cause "Initializing AI Research..." to persist
        const stageMessage = document.getElementById('stageMessage');
        const stageTitle = document.getElementById('stageTitle');
        const stageIcon = document.getElementById('stageIcon');
        
        if (stageMessage) stageMessage.textContent = '';
        if (stageTitle) stageTitle.textContent = '';
        if (stageIcon) stageIcon.innerHTML = '';
        
        // Clear progress details
        const currentTopic = document.getElementById('currentTopic');
        const currentIteration = document.getElementById('currentIteration');
        const resultsFound = document.getElementById('resultsFound');
        
        if (currentTopic) currentTopic.textContent = '';
        if (currentIteration) currentIteration.textContent = '';
        if (resultsFound) resultsFound.textContent = '';
        
        // Clear validation
        document.getElementById('topicValidation').style.display = 'none';
    }

    /**
     * Show/hide sections
     */
    showSection(sectionId) {
        const sections = [
            'researchFormSection',
            'progressSection', 
            'resultsSection',
            'errorSection'
        ];
        
        sections.forEach(id => {
            const element = document.getElementById(id);
            if (element) {
                element.style.display = id === sectionId ? 'block' : 'none';
            }
        });
    }

    /**
     * Show loading overlay
     */
    showLoading(show) {
        const overlay = document.getElementById('loadingOverlay');
        overlay.style.display = show ? 'flex' : 'none';
    }

    /**
     * Show notification
     */
    showNotification(message, type = 'info') {
        const container = document.getElementById('notificationContainer');
        
        const notification = document.createElement('div');
        notification.className = `notification ${type}`;
        
        const icon = type === 'success' ? 'check' : 
                    type === 'error' ? 'exclamation-triangle' : 
                    type === 'info' ? 'info-circle' : 'bell';
        
        notification.innerHTML = `<i class="fas fa-${icon}"></i><span></span>`;
        notification.querySelector('span').textContent = message;
        
        container.appendChild(notification);
        
        // Auto remove after 5 seconds
        setTimeout(() => {
            if (notification.parentNode) {
                notification.parentNode.removeChild(notification);
            }
        }, 5000);
    }

    /**
     * Handle keyboard shortcuts
     */
    handleKeyboardShortcuts(e) {
        // Ctrl/Cmd + Enter to start research
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
            if (document.getElementById('researchFormSection').style.display !== 'none') {
                this.startResearch();
            }
        }
        
        // Escape to cancel or close
        if (e.key === 'Escape') {
            console.debug('Escape key pressed');
            if (this.currentSession) {
                console.debug('Current session exists, calling cancelResearch()');
                this.cancelResearch();
            } else {
                console.debug('No current session, ignoring Escape key');
            }
        }
    }

    /**
     * Handle page unload
     */
    handlePageUnload(e) {
        if (this.currentSession && 
            ['pending', 'running'].includes(this.currentSession.status)) {
            e.preventDefault();
            e.returnValue = 'Research is in progress. Are you sure you want to leave?';
            return e.returnValue;
        }
    }

    /**
     * Save user preferences
     */
    savePreferences() {
        const preferences = {
            maxQueries: document.getElementById('maxQueries').value,
            maxSearchs: document.getElementById('maxSearchs').value,
            maxIteration: document.getElementById('maxIteration').value,
            maxTokens: document.getElementById('maxTokens').value,
            rerankThreshold: document.getElementById('rerankThreshold').value,
            removeThinkingToken: document.getElementById('removeThinkingToken').checked,
            interactiveMode: document.getElementById('interactiveMode').checked
        };
        
        localStorage.setItem('deepResearchPreferences', JSON.stringify(preferences));
    }

    /**
     * Load user preferences
     */
    loadPreferences() {
        try {
            const saved = localStorage.getItem('deepResearchPreferences');
            if (saved) {
                const preferences = JSON.parse(saved);
                
                // Apply saved preferences
                Object.keys(preferences).forEach(key => {
                    const element = document.getElementById(key);
                    if (element) {
                        if (element.type === 'checkbox') {
                            element.checked = preferences[key];
                        } else {
                            element.value = preferences[key];
                            // Update value display
                            const valueDisplay = document.getElementById(`${key}Value`);
                            if (valueDisplay) {
                                valueDisplay.textContent = preferences[key];
                            }
                        }
                    }
                });
            }
        } catch (error) {
            console.error('Failed to load preferences:', error);
        }
    }
}

/**
 * Modal functions
 */
function showModal(title, content) {
    document.getElementById('modalTitle').textContent = title;
    document.getElementById('modalContent').innerHTML = content;
    document.getElementById('modalOverlay').style.display = 'flex';
}

function closeModal() {
    document.getElementById('modalOverlay').style.display = 'none';
}

function showAbout() {
    const content = `
        <h4>Deep Research</h4>
        <p>Plans search queries, reads the web, searches again for what is missing, and writes a cited report.</p>
        <br>
        <h5>Features:</h5>
        <ul>
            <li>Clarifying questions and query planning</li>
            <li>Multi-iteration research with gap analysis</li>
            <li>Real-time progress tracking</li>
            <li>Relevance filtering with a reranker</li>
            <li>Markdown report with source links</li>
        </ul>
        <br>
        <h5>Technology Stack:</h5>
        <ul>
            <li>Planning: Llama-4-Maverick-17B</li>
            <li>Summarization: Llama-3.3-70B</li>
            <li>JSON parsing: Llama-3.1-70B</li>
            <li>Answer Generation: DeepSeek-R1</li>
            <li>Web Search: Tavily API</li>
            <li>Reranking: Voyage AI</li>
        </ul>
    `;
    showModal('About Deep Research', content);
}

function showHelp() {
    const content = `
        <h4>How to Use Deep Research</h4>
        <br>
        <h5>Getting Started:</h5>
        <ol>
            <li>Enter your research topic in the text area</li>
            <li>Optionally adjust advanced options for customization</li>
            <li>Click "Start Research" to begin the process</li>
            <li>Monitor real-time progress updates</li>
            <li>Read, copy or download the report</li>
        </ol>
        <br>
        <h5>Advanced Options:</h5>
        <ul>
            <li><strong>Max Queries:</strong> Number of search queries to generate</li>
            <li><strong>Max Results:</strong> Search results per query</li>
            <li><strong>Max Iterations:</strong> Research depth and thoroughness</li>
            <li><strong>Max Tokens:</strong> Maximum output tokens per model call</li>
            <li><strong>Relevance Threshold:</strong> Minimum quality score for sources</li>
        </ul>
        <br>
        <h5>Tips:</h5>
        <ul>
            <li>Be specific in your research topic for better results</li>
            <li>Higher iterations provide more thorough research</li>
            <li>Use the cancel button to stop research at any time</li>
            <li>Download the report before you close the page: the server keeps it in memory only</li>
        </ul>
    `;
    showModal('Help & Guide', content);
}

// ============================================
// Interactive Q&A Methods
// ============================================

/**
 * Handle clarification start signal
 */
DeepResearchApp.prototype.handleClarificationStart = function(data) {
    console.debug('Starting interactive clarification phase...', data);
    
    // Progress will be controlled by backend during research phase
    
    // Show notification
    this.showNotification('AI is analyzing your topic for clarification questions...', 'info');
};

/**
 * Handle clarification question from WebSocket
 */
DeepResearchApp.prototype.handleClarificationQuestion = function(data) {
    console.debug('Received clarification question:', data);
    
    // Check if we already answered this question (prevent race condition duplicates)
    if (this.answeredQuestions.has(data.question_id)) {
        console.debug('Ignoring duplicate question ID:', data.question_id, 'Already answered');
        return; // Don't show duplicate questions due to backend race condition
    }
    
    console.debug('Showing new question ID:', data.question_id);
    
    // Store current question data
    this.currentQuestion = data;
    
    // Progress will be controlled by backend during research phase
    
    // Show Q&A modal
    this.showQAModal(data);
};

/**
 * Show Q&A modal with question and options
 */
DeepResearchApp.prototype.showQAModal = function(questionData) {
    // Clear any existing hide timeout when showing new question
    if (this.qaModalHideTimeout) {
        clearTimeout(this.qaModalHideTimeout);
        this.qaModalHideTimeout = null;
    }
    
    const modal = document.getElementById('qaModalOverlay');
    const questionText = document.getElementById('qaQuestionText');
    const optionsContainer = document.getElementById('qaOptions');
    const loadingDiv = document.getElementById('qaLoading');
    const currentQuestion = document.getElementById('qaCurrentQuestion');
    const totalQuestions = document.getElementById('qaTotalQuestions');
    const progressFill = document.getElementById('qaProgressFill');
    
    // Reset display states for clean question display
    // Ensure loading state is hidden and options are visible for new question
    loadingDiv.style.display = 'none';
    optionsContainer.style.display = 'flex';
    
    // Reset loading text for new question
    const loadingText = loadingDiv.querySelector('span');
    if (loadingText) {
        loadingText.textContent = 'Processing your answer...';
    }
    
    // Remove any previous selections
    const allOptions = document.querySelectorAll('.qa-option');
    allOptions.forEach(option => option.classList.remove('selected'));
    
    // Update question info
    questionText.textContent = questionData.question;
    questionText.style.display = 'block'; // Ensure question text is visible for new questions
    currentQuestion.textContent = questionData.question_num;
    totalQuestions.textContent = questionData.total_questions;
    
    // Update progress bar
    const progressPercent = (questionData.question_num / questionData.total_questions) * 100;
    progressFill.style.width = `${progressPercent}%`;
    
    // Create option buttons
    optionsContainer.innerHTML = '';
    questionData.options.forEach((option) => {
        const optionButton = document.createElement('div');
        optionButton.className = 'qa-option';
        optionButton.textContent = option;
        optionButton.setAttribute('data-option', option);
        
        // Highlight default option
        if (option === questionData.default) {
            optionButton.classList.add('selected');
        }
        
        // Add click handler
        optionButton.addEventListener('click', () => {
            this.selectQAOption(optionButton, option);
        });
        
        optionsContainer.appendChild(optionButton);
    });
    
    // Show modal
    modal.style.display = 'flex';
    
    // Keep progress section visible during clarification (Q&A modal overlays it)
    const progressSection = document.getElementById('progressSection');
    if (progressSection) {
        progressSection.style.display = 'block';
    }
};

/**
 * Handle option selection in Q&A modal
 */
DeepResearchApp.prototype.selectQAOption = function(selectedButton, selectedOption) {
    // Update UI - remove selected class from all options
    const allOptions = document.querySelectorAll('.qa-option');
    allOptions.forEach(option => option.classList.remove('selected'));
    
    // Add selected class to clicked option
    selectedButton.classList.add('selected');
    
    // Track that we answered this question to prevent duplicates
    if (this.currentQuestion && this.currentQuestion.question_id) {
        this.answeredQuestions.add(this.currentQuestion.question_id);
        console.debug('Marked question as answered:', this.currentQuestion.question_id);
    }
    
    // Show loading state
    const loadingDiv = document.getElementById('qaLoading');
    const optionsContainer = document.getElementById('qaOptions');
    const questionText = document.getElementById('qaQuestionText');
    
    optionsContainer.style.display = 'none';
    loadingDiv.style.display = 'flex';
    
    // Hide question text during loading to prevent showing previous question
    if (questionText) {
        questionText.style.display = 'none';
    }
    
    // Send answer via WebSocket
    this.sendQAAnswer(this.currentQuestion.question_id, selectedOption);
    
    // TIMEOUT PROTECTION: Set timeout for answer processing
    this.qaAnswerTimeout = setTimeout(() => {
        console.warn('Q&A answer processing timed out');
        
        // Show error message
        const loadingText = loadingDiv.querySelector('span');
        if (loadingText) {
            loadingText.textContent = 'Processing timed out. Please try again.';
        }
        
        // Add retry button
        this.showQARetryOption(selectedOption);
        
    }, 10000); // 10 second timeout
    
    // Clear any existing hide timeout (but don't set a new one)
    // Let the modal stay visible for potential next questions
    if (this.qaModalHideTimeout) {
        clearTimeout(this.qaModalHideTimeout);
        this.qaModalHideTimeout = null;
    }
    
    // Modal will be hidden when clarification_complete is received
    // This allows multiple questions to display in sequence
};

/**
 * Send Q&A answer via WebSocket
 */
DeepResearchApp.prototype.sendQAAnswer = function(questionId, selectedOption) {
    if (this.websocket && this.websocket.readyState === WebSocket.OPEN) {
        const message = {
            type: 'clarification_answer',
            data: {
                question_id: questionId,
                selected_option: selectedOption
            }
        };
        
        this.websocket.send(JSON.stringify(message));
        console.debug('Sent Q&A answer:', selectedOption);
    } else {
        console.error('WebSocket not available for sending Q&A answer');
    }
};

/**
 * Hide Q&A modal
 */
DeepResearchApp.prototype.handleClarificationComplete = function(data) {
    console.debug('Clarification phase completed:', data);
    
    // Clear answered questions set for fresh state
    this.answeredQuestions.clear();
    console.debug('Cleared answered questions set - ready for next research session');
    
    // Clear any pending hide timeout
    if (this.qaModalHideTimeout) {
        clearTimeout(this.qaModalHideTimeout);
        this.qaModalHideTimeout = null;
    }
    
    // Hide Q&A modal if still visible
    this.hideQAModal();
    
    // Progress will be controlled by backend when research begins
    
    // Show notification with refined topic
    const message = `Research scope refined! Proceeding with: "${data.refined_topic}"`;
    this.showNotification(message, 'success');
    
    // Clear current question data
    this.currentQuestion = null;
};

/**
 * Show retry option when answer processing fails or times out
 */
DeepResearchApp.prototype.showQARetryOption = function(lastSelectedOption) {
    const loadingDiv = document.getElementById('qaLoading');
    const optionsContainer = document.getElementById('qaOptions');
    
    if (!loadingDiv || !optionsContainer) return;
    
    // Create retry interface
    loadingDiv.innerHTML = `
        <div style="text-align: center;">
            <i class="fas fa-exclamation-triangle" style="color: #ff6b6b; font-size: 24px; margin-bottom: 10px;"></i>
            <p style="margin: 10px 0;">Processing timed out. Please try again.</p>
            <div style="display: flex; gap: 10px; justify-content: center; margin-top: 15px;">
                <button id="qaRetryBtn" class="btn-primary" style="padding: 8px 16px;">
                    <i class="fas fa-redo"></i> Retry Same Answer
                </button>
                <button id="qaChooseAgainBtn" class="btn-secondary" style="padding: 8px 16px;">
                    <i class="fas fa-arrow-left"></i> Choose Again
                </button>
            </div>
        </div>
    `;
    
    // Add event listeners
    document.getElementById('qaRetryBtn').onclick = () => {
        // Reset to loading state and retry
        loadingDiv.innerHTML = `
            <div style="text-align: center;">
                <i class="fas fa-spinner fa-spin" style="font-size: 24px; margin-bottom: 10px;"></i>
                <span>Retrying... Processing your answer...</span>
            </div>
        `;
        
        // Retry sending the same answer
        this.sendQAAnswer(this.currentQuestion.question_id, lastSelectedOption);
        
        // Set new timeout
        this.qaAnswerTimeout = setTimeout(() => {
            this.showQARetryOption(lastSelectedOption);
        }, 10000);
    };
    
    document.getElementById('qaChooseAgainBtn').onclick = () => {
        // Go back to options
        loadingDiv.style.display = 'none';
        optionsContainer.style.display = 'flex';
        
        // Show question text again when going back to options
        const questionText = document.getElementById('qaQuestionText');
        if (questionText) {
            questionText.style.display = 'block';
        }
        
        // Reset loading div content
        loadingDiv.innerHTML = `
            <div style="text-align: center;">
                <i class="fas fa-spinner fa-spin" style="font-size: 24px; margin-bottom: 10px;"></i>
                <span>Processing your answer...</span>
            </div>
        `;
        
        // Clear timeout
        if (this.qaAnswerTimeout) {
            clearTimeout(this.qaAnswerTimeout);
            this.qaAnswerTimeout = null;
        }
    };
};

/**
 * Handle answer received acknowledgment from backend
 */
DeepResearchApp.prototype.handleAnswerReceived = function(data) {
    console.debug('Answer received acknowledgment:', data);
    
    // Clear any pending timeout
    if (this.qaAnswerTimeout) {
        clearTimeout(this.qaAnswerTimeout);
        this.qaAnswerTimeout = null;
    }
    
    // Show success feedback and keep it visible
    const loadingDiv = document.getElementById('qaLoading');
    const questionText = document.getElementById('qaQuestionText');
    
    if (loadingDiv) {
        const loadingText = loadingDiv.querySelector('span');
        if (loadingText) {
            loadingText.textContent = 'Answer processed successfully!';
        }
    }
    
    // Ensure question text remains hidden during success state
    if (questionText) {
        questionText.style.display = 'none';
    }
    
    // Don't automatically reset modal state
    // Keep the modal in "Answer processed successfully!" state to prevent showing duplicate questions
    // The modal will be properly handled when either:
    // 1. A NEW question (different question_id) arrives via handleClarificationQuestion
    // 2. Clarification is complete via handleClarificationComplete
    console.debug('Answer processed, keeping modal in success state to prevent duplicates');
};

/**
 * Hide Q&A modal
 */
DeepResearchApp.prototype.hideQAModal = function() {
    const modal = document.getElementById('qaModalOverlay');
    const loadingDiv = document.getElementById('qaLoading');
    const optionsContainer = document.getElementById('qaOptions');
    
    // Clear any pending timeouts
    if (this.qaAnswerTimeout) {
        clearTimeout(this.qaAnswerTimeout);
        this.qaAnswerTimeout = null;
    }
    
    // Reset modal state
    loadingDiv.style.display = 'none';
    optionsContainer.style.display = 'flex';
    
    // Reset question text visibility
    const questionText = document.getElementById('qaQuestionText');
    if (questionText) {
        questionText.style.display = 'block';
    }
    
    // Reset loading text
    const loadingText = loadingDiv.querySelector('span');
    if (loadingText) {
        loadingText.textContent = 'Processing your answer...';
    }
    
    // Hide modal
    modal.style.display = 'none';
    
    // Show progress section again
    const progressSection = document.getElementById('progressSection');
    if (progressSection) {
        progressSection.style.display = 'block';
    }
};



// Initialize the application when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    window.deepResearchApp = new DeepResearchApp();
});

// Handle modal clicks
document.addEventListener('click', (e) => {
    if (e.target === document.getElementById('modalOverlay')) {
        closeModal();
    }
});