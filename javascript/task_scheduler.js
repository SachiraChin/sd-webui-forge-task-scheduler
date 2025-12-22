/**
 * Task Scheduler JavaScript for injecting Queue buttons
 * and handling task queue UI interactions.
 */

(function() {
    'use strict';

    // State tracking for smart refresh
    let lastTasksHash = '';
    let lastStatusHash = '';
    let refreshInterval = null;
    let lastTabWasQueue = false;

    // Wait for DOM to be ready
    function onReady(callback) {
        if (document.readyState === 'complete' || document.readyState === 'interactive') {
            setTimeout(callback, 100);
        } else {
            document.addEventListener('DOMContentLoaded', callback);
        }
    }

    // Inject Queue button next to Generate button
    function injectQueueButton(tabName) {
        const generateBtn = document.getElementById(`${tabName}_generate`);
        if (!generateBtn) {
            console.log(`[TaskScheduler] Generate button not found for ${tabName}`);
            return false;
        }

        // Check if Queue button already exists
        if (document.getElementById(`${tabName}_queue`)) {
            return true;
        }

        // Create Queue button - copy styling from Generate button
        const queueBtn = document.createElement('button');
        queueBtn.id = `${tabName}_queue`;
        queueBtn.className = generateBtn.className.replace('primary', 'secondary');
        queueBtn.textContent = 'Queue';
        queueBtn.title = 'Add current settings to task queue';
        queueBtn.style.marginLeft = '8px';
        queueBtn.style.minWidth = '80px';

        // Insert after Generate button
        generateBtn.parentNode.insertBefore(queueBtn, generateBtn.nextSibling);

        // Add click handler
        queueBtn.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            queueTask(tabName);
        });

        console.log(`[TaskScheduler] Queue button injected for ${tabName}`);
        return true;
    }

    // Queue a task
    function queueTask(tabName) {
        const queueBtn = document.getElementById(`${tabName}_queue`);
        const originalText = queueBtn ? queueBtn.textContent : 'Queue';
        if (queueBtn) {
            queueBtn.textContent = 'Queuing...';
            queueBtn.disabled = true;
        }

        const params = collectParams(tabName);

        fetch('/task-scheduler/queue/' + tabName, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(params)
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showNotification('Task queued successfully!', 'success');
                refreshTaskList(); // Direct API refresh
            } else {
                showNotification('Failed to queue task: ' + (data.error || 'Unknown error'), 'error');
            }
        })
        .catch(error => {
            console.error('[TaskScheduler] Error queuing task:', error);
            showNotification('Error queuing task. Check console for details.', 'error');
        })
        .finally(() => {
            if (queueBtn) {
                queueBtn.textContent = originalText;
                queueBtn.disabled = false;
            }
        });
    }

    // Collect parameters from UI
    function collectParams(tabName) {
        const params = { extra_params: {} };

        const promptEl = document.querySelector(`#${tabName}_prompt textarea`);
        if (promptEl) params.prompt = promptEl.value || '';

        const negPromptEl = document.querySelector(`#${tabName}_neg_prompt textarea`);
        if (negPromptEl) params.negative_prompt = negPromptEl.value || '';

        let stepsEl = document.querySelector(`#${tabName}_steps input[type="number"]`);
        if (!stepsEl) stepsEl = document.querySelector(`#${tabName}_steps input`);
        if (stepsEl) params.steps = parseInt(stepsEl.value) || 20;

        let cfgEl = document.querySelector(`#${tabName}_cfg_scale input[type="number"]`);
        if (!cfgEl) cfgEl = document.querySelector(`#${tabName}_cfg_scale input`);
        if (cfgEl) params.cfg_scale = parseFloat(cfgEl.value) || 7.0;

        let widthEl = document.querySelector(`#${tabName}_width input[type="number"]`);
        if (!widthEl) widthEl = document.querySelector(`#${tabName}_width input`);
        if (widthEl) params.width = parseInt(widthEl.value) || 512;

        let heightEl = document.querySelector(`#${tabName}_height input[type="number"]`);
        if (!heightEl) heightEl = document.querySelector(`#${tabName}_height input`);
        if (heightEl) params.height = parseInt(heightEl.value) || 512;

        let batchSizeEl = document.querySelector(`#${tabName}_batch_size input[type="number"]`);
        if (!batchSizeEl) batchSizeEl = document.querySelector(`#${tabName}_batch_size input`);
        if (batchSizeEl) params.batch_size = parseInt(batchSizeEl.value) || 1;

        let batchCountEl = document.querySelector(`#${tabName}_batch_count input[type="number"]`);
        if (!batchCountEl) batchCountEl = document.querySelector(`#${tabName}_batch_count input`);
        if (batchCountEl) params.n_iter = parseInt(batchCountEl.value) || 1;

        let seedEl = document.querySelector(`#${tabName}_seed input[type="number"]`);
        if (!seedEl) seedEl = document.querySelector(`#${tabName}_seed input`);
        if (seedEl) params.seed = parseInt(seedEl.value) || -1;

        const samplerEl = document.querySelector(`#${tabName}_sampling select, #${tabName}_sampler select`);
        if (samplerEl) params.sampler_name = samplerEl.value || 'Euler';

        const schedulerEl = document.querySelector(`#${tabName}_scheduler select`);
        if (schedulerEl) params.scheduler = schedulerEl.value || 'automatic';

        if (tabName === 'img2img') {
            let denoisingEl = document.querySelector(`#${tabName}_denoising_strength input`);
            if (denoisingEl) params.extra_params.denoising_strength = parseFloat(denoisingEl.value) || 0.75;
        }

        return params;
    }

    // Show notification toast
    function showNotification(message, type) {
        document.querySelectorAll('.task-scheduler-notification').forEach(el => el.remove());

        const notification = document.createElement('div');
        notification.className = `task-scheduler-notification ${type}`;
        notification.textContent = message;
        notification.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 15px 25px;
            border-radius: 8px;
            z-index: 10000;
            animation: taskSchedulerSlideIn 0.3s ease;
            background: ${type === 'success' ? '#4CAF50' : type === 'error' ? '#f44336' : '#2196F3'};
            color: white;
            font-weight: 500;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        `;

        document.body.appendChild(notification);

        setTimeout(() => {
            notification.style.animation = 'taskSchedulerSlideOut 0.3s ease';
            setTimeout(() => notification.remove(), 300);
        }, 3000);
    }

    // Generate simple hash for change detection
    function simpleHash(str) {
        let hash = 0;
        for (let i = 0; i < str.length; i++) {
            const char = str.charCodeAt(i);
            hash = ((hash << 5) - hash) + char;
            hash = hash & hash;
        }
        return hash.toString();
    }

    // Render task list HTML
    function renderTaskList(tasks) {
        if (!tasks || tasks.length === 0) {
            return "<div class='task-empty'>No tasks in queue. Use the Queue button next to Generate to add tasks.</div>";
        }

        const statusIcons = {
            'pending': '⏳',
            'running': '🔄',
            'completed': '✅',
            'failed': '❌',
            'cancelled': '🚫'
        };

        let html = "<div class='task-list'>";

        tasks.forEach((task, i) => {
            const statusClass = `status-${task.status}`;
            const statusIcon = statusIcons[task.status] || '';
            const prompt = (task.name || '').substring(0, 60) + ((task.name || '').length > 60 ? '...' : '');
            const promptEscaped = (task.name || '').replace(/"/g, '&quot;').replace(/'/g, '&#39;');

            let actionsHtml = '';
            actionsHtml += `<button class="task-btn task-btn-info" onclick='taskSchedulerAction("info", "${task.id}")' title="View task details">ℹ️</button>`;
            if (task.status === 'failed' || task.status === 'cancelled') {
                actionsHtml += `<button class="task-btn task-btn-retry" onclick='taskSchedulerAction("retry", "${task.id}")' title="Retry this task">↻</button>`;
            }
            if (task.status !== 'running') {
                actionsHtml += `<button class="task-btn task-btn-delete" onclick='taskSchedulerAction("delete", "${task.id}")' title="Delete this task">🗑️</button>`;
            }

            html += `
            <div class='task-item ${statusClass}' data-task-id='${task.id}'>
                <div class='task-index'>${i + 1}</div>
                <div class='task-info'>
                    <div class='task-type'>${task.task_type}</div>
                    <div class='task-prompt' title="${promptEscaped}">${prompt}</div>
                    <div class='task-checkpoint'>Model: ${task.checkpoint || 'Default'}</div>
                </div>
                <div class='task-status'><span class='status-badge'>${statusIcon} ${task.status}</span></div>
                <div class='task-actions'>${actionsHtml}</div>
            </div>
            `;
        });

        html += "</div>";
        return html;
    }

    // Render queue status HTML
    function renderQueueStatus(status) {
        const stats = status.queue_stats || {};
        let runningStatus, statusClass;

        if (status.is_running) {
            if (status.is_paused) {
                runningStatus = 'Paused';
                statusClass = 'paused';
            } else if (stats.pending === 0 && stats.running === 0) {
                runningStatus = 'Idle (no pending tasks)';
                statusClass = 'idle';
            } else {
                runningStatus = 'Processing';
                statusClass = 'active';
            }
        } else {
            runningStatus = 'Stopped';
            statusClass = 'inactive';
        }

        let current = '';
        if (status.current_task) {
            let taskName = status.current_task.name || '';
            if (!taskName && status.current_task.params) {
                let params = status.current_task.params;
                if (typeof params === 'string') {
                    try { params = JSON.parse(params); } catch(e) { params = {}; }
                }
                taskName = (params.prompt || 'Unknown').substring(0, 30) + '...';
            }
            current = `<br><small>Current: ${taskName}</small>`;
        }

        return `
        <div class='queue-status ${statusClass}'>
            <span class='status-indicator ${statusClass}'></span>
            <div class='status-text'>
                <strong>Queue: ${runningStatus}</strong>${current}
            </div>
            <div class='status-stats'>
                <span class='stat pending'>⏳ ${stats.pending || 0} pending</span>
                <span class='stat running'>🔄 ${stats.running || 0} running</span>
                <span class='stat completed'>✅ ${stats.completed || 0} completed</span>
                <span class='stat failed'>❌ ${stats.failed || 0} failed</span>
            </div>
        </div>
        `;
    }

    // Fetch and update task list via API
    async function refreshTaskList(force = false) {
        if (!isTaskQueueTabVisible() && !force) return;

        try {
            // Fetch tasks and status in parallel
            const [tasksResponse, statusResponse] = await Promise.all([
                fetch('/task-scheduler/queue'),
                fetch('/task-scheduler/status')
            ]);

            const tasksData = await tasksResponse.json();
            const statusData = await statusResponse.json();

            if (!tasksData.success || !statusData.success) return;

            // Check if data changed using hash
            const newTasksHash = simpleHash(JSON.stringify(tasksData.tasks));
            const newStatusHash = simpleHash(JSON.stringify(statusData));

            const tasksChanged = newTasksHash !== lastTasksHash;
            const statusChanged = newStatusHash !== lastStatusHash;

            // Update DOM only if changed
            if (tasksChanged) {
                lastTasksHash = newTasksHash;
                const taskListEl = document.getElementById('task_queue_list');
                if (taskListEl) {
                    // Find the actual HTML container inside Gradio's wrapper
                    const htmlContainer = taskListEl.querySelector('.prose') || taskListEl;
                    htmlContainer.innerHTML = renderTaskList(tasksData.tasks);
                }
            }

            if (statusChanged) {
                lastStatusHash = newStatusHash;
                const statusEl = document.getElementById('task_queue_status');
                if (statusEl) {
                    const htmlContainer = statusEl.querySelector('.prose') || statusEl;
                    htmlContainer.innerHTML = renderQueueStatus(statusData);
                }
            }

            if (tasksChanged || statusChanged) {
                console.log('[TaskScheduler] UI updated via API');
            }

        } catch (error) {
            console.error('[TaskScheduler] Error refreshing task list:', error);
        }
    }

    // Show task details modal
    async function showTaskDetails(taskId) {
        try {
            const response = await fetch(`/task-scheduler/queue/${taskId}`);
            const data = await response.json();

            if (!data.success || !data.task) {
                showNotification('Failed to load task details', 'error');
                return;
            }

            const task = data.task;
            let params = task.params;
            if (typeof params === 'string') {
                try { params = JSON.parse(params); } catch(e) { params = {}; }
            }

            // Parse result_images if it's a JSON string
            let resultImages = task.result_images;
            if (typeof resultImages === 'string') {
                try { resultImages = JSON.parse(resultImages); } catch(e) { resultImages = []; }
            }
            if (!Array.isArray(resultImages)) {
                resultImages = [];
            }

            // Create modal
            const modal = document.createElement('div');
            modal.className = 'task-details-modal';
            modal.innerHTML = `
                <div class="task-details-backdrop" onclick="this.parentElement.remove()"></div>
                <div class="task-details-content">
                    <div class="task-details-header">
                        <h3>Task Details</h3>
                        <button class="task-details-close" onclick="this.closest('.task-details-modal').remove()">✕</button>
                    </div>
                    <div class="task-details-body">
                        <div class="task-details-section">
                            <h4>General</h4>
                            <table class="task-details-table">
                                <tr><td>ID</td><td><code>${task.id}</code></td></tr>
                                <tr><td>Type</td><td>${task.task_type}</td></tr>
                                <tr><td>Status</td><td><span class="status-badge-mini status-${task.status}">${task.status}</span></td></tr>
                                <tr><td>Checkpoint</td><td>${task.checkpoint || 'Default'}</td></tr>
                                <tr><td>Created</td><td>${task.created_at || 'Unknown'}</td></tr>
                                ${task.completed_at ? `<tr><td>Completed</td><td>${task.completed_at}</td></tr>` : ''}
                            </table>
                        </div>
                        <div class="task-details-section">
                            <h4>Parameters</h4>
                            <table class="task-details-table">
                                <tr><td>Prompt</td><td class="task-prompt-cell">${params.prompt || ''}</td></tr>
                                <tr><td>Negative Prompt</td><td class="task-prompt-cell">${params.negative_prompt || ''}</td></tr>
                                <tr><td>Size</td><td>${params.width || 512} × ${params.height || 512}</td></tr>
                                <tr><td>Steps</td><td>${params.steps || 20}</td></tr>
                                <tr><td>CFG Scale</td><td>${params.cfg_scale || 7}</td></tr>
                                <tr><td>Sampler</td><td>${params.sampler_name || 'Euler'}</td></tr>
                                <tr><td>Scheduler</td><td>${params.scheduler || 'automatic'}</td></tr>
                                <tr><td>Seed</td><td>${params.seed || -1}</td></tr>
                                <tr><td>Batch Size</td><td>${params.batch_size || 1}</td></tr>
                                <tr><td>Batch Count</td><td>${params.n_iter || 1}</td></tr>
                                ${params.denoising_strength !== undefined ? `<tr><td>Denoising</td><td>${params.denoising_strength}</td></tr>` : ''}
                                ${params.enable_hr ? `<tr><td>Hires Fix</td><td>Enabled (${params.hr_scale}x)</td></tr>` : ''}
                            </table>
                        </div>
                        ${task.error ? `
                        <div class="task-details-section task-error-section">
                            <h4>Error</h4>
                            <pre class="task-error-text">${task.error}</pre>
                        </div>
                        ` : ''}
                        ${resultImages && resultImages.length > 0 ? `
                        <div class="task-details-section">
                            <h4>Results</h4>
                            <div class="task-results-list">
                                ${resultImages.map(img => `<div class="task-result-path">${img}</div>`).join('')}
                            </div>
                        </div>
                        ` : ''}
                    </div>
                </div>
            `;

            document.body.appendChild(modal);

        } catch (error) {
            console.error('[TaskScheduler] Error loading task details:', error);
            showNotification('Error loading task details', 'error');
        }
    }

    // Handle task actions
    window.taskSchedulerAction = function(action, taskId) {
        if (action === 'info') {
            showTaskDetails(taskId);
        } else if (action === 'delete') {
            if (confirm('Delete this task?')) {
                fetch(`/task-scheduler/queue/${taskId}`, { method: 'DELETE' })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        showNotification('Task deleted', 'success');
                        refreshTaskList(true);
                    } else {
                        showNotification('Failed to delete task: ' + (data.error || 'Unknown error'), 'error');
                    }
                })
                .catch(error => {
                    console.error('[TaskScheduler] Error deleting task:', error);
                    showNotification('Error deleting task', 'error');
                });
            }
        } else if (action === 'retry') {
            fetch(`/task-scheduler/queue/${taskId}/retry`, { method: 'POST' })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    showNotification('Task requeued', 'success');
                    refreshTaskList(true);
                } else {
                    showNotification('Failed to retry task', 'error');
                }
            })
            .catch(error => {
                console.error('[TaskScheduler] Error retrying task:', error);
                showNotification('Error retrying task', 'error');
            });
        }
    };

    // Check if task queue tab is visible
    function isTaskQueueTabVisible() {
        const tabButton = document.querySelector('button[role="tab"][aria-selected="true"]');
        if (tabButton && tabButton.textContent.includes('Task Queue')) {
            return true;
        }

        const queueStatus = document.getElementById('task_queue_status');
        if (queueStatus && queueStatus.offsetParent !== null && queueStatus.offsetHeight > 0) {
            return true;
        }

        const taskQueueTab = document.getElementById('task_queue_tab');
        if (taskQueueTab && taskQueueTab.offsetParent !== null && taskQueueTab.offsetHeight > 0) {
            return true;
        }

        return false;
    }

    // Start background refresh
    function startAutoRefresh() {
        if (refreshInterval) return;

        setupTabChangeDetection();

        // Use API-based refresh every 2 seconds (lighter than button clicking)
        refreshInterval = setInterval(() => {
            if (isTaskQueueTabVisible()) {
                refreshTaskList();
            }
        }, 2000);
    }

    // Set up tab change detection
    function setupTabChangeDetection() {
        const selectors = ['.tabs', '[role="tablist"]', '.tab-nav', '#tabs'];
        let tabsContainer = null;
        for (const sel of selectors) {
            tabsContainer = document.querySelector(sel);
            if (tabsContainer) break;
        }

        if (!tabsContainer) {
            setTimeout(setupTabChangeDetection, 1000);
            return;
        }

        const observer = new MutationObserver(() => {
            const isQueueTabNow = isTaskQueueTabVisible();
            if (isQueueTabNow && !lastTabWasQueue) {
                console.log('[TaskScheduler] Switched to Task Queue tab');
                refreshTaskList(true);
            }
            lastTabWasQueue = isQueueTabNow;
        });

        observer.observe(tabsContainer, {
            attributes: true,
            subtree: true,
            attributeFilter: ['aria-selected', 'class']
        });

        // Add click handlers to tab buttons
        const addTabClickHandlers = () => {
            document.querySelectorAll('button[role="tab"], .tab-nav button').forEach(tab => {
                if (tab.dataset.taskSchedulerHandler) return;
                tab.dataset.taskSchedulerHandler = 'true';
                tab.addEventListener('click', () => {
                    setTimeout(() => {
                        const isQueueTabNow = isTaskQueueTabVisible();
                        if (isQueueTabNow && !lastTabWasQueue) {
                            refreshTaskList(true);
                        }
                        lastTabWasQueue = isQueueTabNow;
                    }, 200);
                });
            });
        };

        addTabClickHandlers();
        setInterval(addTabClickHandlers, 5000);
    }

    // Initialize
    function init() {
        console.log('[TaskScheduler] Initializing...');

        let attempts = 0;
        const maxAttempts = 60;

        function tryInject() {
            attempts++;
            const txt2imgSuccess = injectQueueButton('txt2img');
            const img2imgSuccess = injectQueueButton('img2img');

            if (txt2imgSuccess && img2imgSuccess) {
                console.log('[TaskScheduler] All buttons injected successfully');
                startAutoRefresh();
            } else if (attempts < maxAttempts) {
                setTimeout(tryInject, 500);
            } else {
                console.log('[TaskScheduler] Some buttons could not be injected after max attempts');
                startAutoRefresh();
            }
        }

        tryInject();

        // Add CSS for modal and animations
        const style = document.createElement('style');
        style.textContent = `
            @keyframes taskSchedulerSlideIn {
                from { transform: translateX(100%); opacity: 0; }
                to { transform: translateX(0); opacity: 1; }
            }
            @keyframes taskSchedulerSlideOut {
                from { transform: translateX(0); opacity: 1; }
                to { transform: translateX(100%); opacity: 0; }
            }
            #txt2img_queue, #img2img_queue {
                min-width: 80px !important;
            }

            /* Task Details Modal */
            .task-details-modal {
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                z-index: 10001;
                display: flex;
                align-items: center;
                justify-content: center;
            }
            .task-details-backdrop {
                position: absolute;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background: rgba(0,0,0,0.6);
            }
            .task-details-content {
                position: relative;
                background: var(--background-fill-primary, #1f2937);
                border-radius: 12px;
                max-width: 700px;
                max-height: 80vh;
                width: 90%;
                overflow: hidden;
                box-shadow: 0 20px 40px rgba(0,0,0,0.4);
            }
            .task-details-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 16px 20px;
                border-bottom: 1px solid var(--border-color-primary, #374151);
            }
            .task-details-header h3 {
                margin: 0;
                font-size: 1.2em;
            }
            .task-details-close {
                background: transparent;
                border: none;
                font-size: 1.5em;
                cursor: pointer;
                color: var(--body-text-color, #fff);
                padding: 0 8px;
            }
            .task-details-close:hover {
                color: #f44336;
            }
            .task-details-body {
                padding: 20px;
                overflow-y: auto;
                max-height: calc(80vh - 60px);
            }
            .task-details-section {
                margin-bottom: 20px;
            }
            .task-details-section h4 {
                margin: 0 0 10px 0;
                font-size: 0.9em;
                text-transform: uppercase;
                color: var(--body-text-color-subdued, #9ca3af);
                letter-spacing: 0.5px;
            }
            .task-details-table {
                width: 100%;
                border-collapse: collapse;
            }
            .task-details-table td {
                padding: 8px 12px;
                border-bottom: 1px solid var(--border-color-primary, #374151);
                vertical-align: top;
            }
            .task-details-table td:first-child {
                font-weight: 500;
                width: 120px;
                color: var(--body-text-color-subdued, #9ca3af);
            }
            .task-prompt-cell {
                word-break: break-word;
                max-width: 400px;
            }
            .task-error-section {
                background: rgba(244, 67, 54, 0.1);
                border-radius: 8px;
                padding: 12px;
            }
            .task-error-text {
                background: rgba(0,0,0,0.2);
                padding: 10px;
                border-radius: 4px;
                font-size: 0.85em;
                overflow-x: auto;
                white-space: pre-wrap;
                margin: 0;
            }
            .task-results-list {
                display: flex;
                flex-direction: column;
                gap: 4px;
            }
            .task-result-path {
                font-family: monospace;
                font-size: 0.85em;
                background: rgba(0,0,0,0.2);
                padding: 6px 10px;
                border-radius: 4px;
                word-break: break-all;
            }
            .status-badge-mini {
                display: inline-block;
                padding: 2px 8px;
                border-radius: 10px;
                font-size: 0.85em;
                font-weight: 500;
            }
            .status-badge-mini.status-pending { background: rgba(33, 150, 243, 0.2); color: #2196F3; }
            .status-badge-mini.status-running { background: rgba(255, 152, 0, 0.2); color: #FF9800; }
            .status-badge-mini.status-completed { background: rgba(76, 175, 80, 0.2); color: #4CAF50; }
            .status-badge-mini.status-failed { background: rgba(244, 67, 54, 0.2); color: #f44336; }
            .status-badge-mini.status-cancelled { background: rgba(158, 158, 158, 0.2); color: #9E9E9E; }
            code {
                background: rgba(0,0,0,0.2);
                padding: 2px 6px;
                border-radius: 4px;
                font-size: 0.85em;
            }
        `;
        document.head.appendChild(style);
    }

    onReady(init);
})();
