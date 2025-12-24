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
    let lastSettingsHash = '';

    // Wait for DOM to be ready
    function onReady(callback) {
        if (document.readyState === 'complete' || document.readyState === 'interactive') {
            setTimeout(callback, 100);
        } else {
            document.addEventListener('DOMContentLoaded', callback);
        }
    }

    // Queue buttons are now created via Gradio in task_scheduler_ui.py
    // This provides proper binding to all 185+ generation inputs
    // The JavaScript below handles task list updates, notifications, etc.

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

    // Render a single task item
    function renderTaskItem(task, index) {
        const statusIcons = {
            'pending': '⏳',
            'running': '🔄',
            'completed': '✅',
            'failed': '❌',
            'cancelled': '🚫'
        };

        const statusClass = `status-${task.status}`;
        const statusIcon = statusIcons[task.status] || '';
        const prompt = (task.name || '').substring(0, 60) + ((task.name || '').length > 60 ? '...' : '');
        const promptEscaped = (task.name || '').replace(/"/g, '&quot;').replace(/'/g, '&#39;');

        // Calculate total images (batch_size * n_iter)
        const batchSize = task.batch_size || 1;
        const nIter = task.n_iter || 1;
        const totalImages = batchSize * nIter;

        let actionsHtml = '';
        actionsHtml += `<button class="task-btn task-btn-info" onclick='taskSchedulerAction("info", "${task.id}")' title="View task details"><span class="btn-icon">ℹ️</span><span class="btn-text">Info</span></button>`;
        actionsHtml += `<button class="task-btn task-btn-load" onclick='taskSchedulerAction("loadToUI", "${task.id}", "${task.task_type}")' title="Load to UI"><span class="btn-icon">📋</span><span class="btn-text">Load</span></button>`;
        if (task.status === 'completed' || task.status === 'failed' || task.status === 'cancelled') {
            actionsHtml += `<button class="task-btn task-btn-retry" onclick='taskSchedulerAction("retry", "${task.id}")' title="Requeue this task"><span class="btn-icon">↻</span><span class="btn-text">Retry</span></button>`;
        }
        if (task.status !== 'running') {
            actionsHtml += `<button class="task-btn task-btn-delete" onclick='taskSchedulerAction("delete", "${task.id}")' title="Delete this task"><span class="btn-icon">🗑️</span><span class="btn-text">Delete</span></button>`;
        }

        return `
        <div class='task-item ${statusClass}' data-task-id='${task.id}'>
            <div class='task-index'>${index}</div>
            <div class='task-info'>
                <div class='task-type'>${task.task_type}</div>
                <div class='task-prompt' title="${promptEscaped}">${prompt}</div>
                <div class='task-meta'>
                    <span class='task-checkpoint'>Model: ${task.checkpoint || 'Default'}</span>
                    <span class='task-images'>${totalImages} image${totalImages !== 1 ? 's' : ''}</span>
                </div>
            </div>
            <div class='task-status'><span class='status-badge'>${statusIcon} ${task.status}</span></div>
            <div class='task-actions'>${actionsHtml}</div>
        </div>
        `;
    }

    // Render task list HTML with separate Active and History sections
    function renderTaskList(tasks) {
        if (!tasks || tasks.length === 0) {
            return "<div class='task-empty'>No tasks in queue. Use the Queue button next to Generate to add tasks.</div>";
        }

        // Separate active (pending/running) from history (completed/failed/cancelled)
        const activeTasks = tasks.filter(t => t.status === 'pending' || t.status === 'running');
        const historyTasks = tasks.filter(t => t.status === 'completed' || t.status === 'failed' || t.status === 'cancelled');

        let html = '';

        // Active Tasks Section
        html += "<div class='task-section task-section-active'>";
        html += "<h3 class='task-section-header'>Active Tasks</h3>";
        if (activeTasks.length > 0) {
            html += "<div class='task-list'>";
            activeTasks.forEach((task, i) => {
                html += renderTaskItem(task, i + 1);
            });
            html += "</div>";
        } else {
            html += "<div class='task-empty-small'>No active tasks</div>";
        }
        html += "</div>";

        // History Section (collapsible)
        html += "<div class='task-section task-section-history'>";
        html += `<details class='task-history-details' ${activeTasks.length === 0 ? 'open' : ''}>`;
        html += `<summary class='task-section-header task-history-summary'>History (${historyTasks.length} tasks)</summary>`;
        if (historyTasks.length > 0) {
            html += "<div class='task-list task-list-history'>";
            historyTasks.forEach((task, i) => {
                html += renderTaskItem(task, i + 1);
            });
            html += "</div>";
        } else {
            html += "<div class='task-empty-small'>No history</div>";
        }
        html += "</details>";
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

    // Update button enabled/disabled states via JavaScript
    function updateButtonStates(states) {
        console.log('[TaskScheduler] Updating button states:', states);

        const buttonMap = {
            'start': 'task_queue_start_btn',
            'stop': 'task_queue_stop_btn',
            'pause': 'task_queue_pause_btn',
            'clear': 'task_queue_clear_btn'
        };

        for (const [key, enabled] of Object.entries(states)) {
            const btnId = buttonMap[key];
            if (!btnId) continue;

            const container = document.getElementById(btnId);
            if (!container) {
                console.warn(`[TaskScheduler] Button container not found: ${btnId}`);
                continue;
            }

            // Find the actual button element inside Gradio's wrapper
            const btn = container.querySelector('button') || container;
            console.log(`[TaskScheduler] Button ${key}: container=${container.tagName}, btn=${btn.tagName}, enabled=${enabled}`);

            if (enabled) {
                btn.removeAttribute('disabled');
                btn.classList.remove('disabled');
                container.classList.remove('disabled');
                // Also try removing Gradio-specific disabled styles
                btn.style.pointerEvents = '';
                btn.style.opacity = '';
            } else {
                btn.setAttribute('disabled', 'disabled');
                btn.classList.add('disabled');
                container.classList.add('disabled');
            }
        }
    }

    // Render settings status HTML for top right corner
    function renderSettingsStatus(settings) {
        const controlnetEnabled = settings.enable_controlnet;
        const statusClass = controlnetEnabled ? 'enabled' : 'disabled';
        const statusText = controlnetEnabled ? 'Enabled' : 'Disabled';

        return `
        <div class='settings-status ${statusClass}'>
            <span class='settings-label'>ControlNet Capture:</span>
            <span class='settings-value'>${statusText}</span>
            <span class='settings-hint'>(Edit in Settings tab)</span>
        </div>
        `;
    }

    // Fetch and update settings display
    async function refreshSettings(force = false) {
        if (!isTaskQueueTabVisible() && !force) return;

        try {
            const response = await fetch('/task-scheduler/settings');
            const data = await response.json();

            if (!data.success) return;

            const newSettingsHash = simpleHash(JSON.stringify(data.settings));
            if (newSettingsHash === lastSettingsHash && !force) return;

            lastSettingsHash = newSettingsHash;
            const settingsEl = document.getElementById('task_queue_settings_status');
            if (settingsEl) {
                const htmlContainer = settingsEl.querySelector('.prose') || settingsEl;
                htmlContainer.innerHTML = renderSettingsStatus(data.settings);
            }

            console.log('[TaskScheduler] Settings updated via API');
        } catch (error) {
            console.error('[TaskScheduler] Error refreshing settings:', error);
        }
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

            // Always update button states (not just when status changes)
            if (statusData.button_states) {
                updateButtonStates(statusData.button_states);
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

            // Parse script_args if it's a JSON string
            let scriptArgs = task.script_args;
            if (typeof scriptArgs === 'string') {
                try { scriptArgs = JSON.parse(scriptArgs); } catch(e) { scriptArgs = []; }
            }
            if (!Array.isArray(scriptArgs)) {
                scriptArgs = [];
            }
            // Store parsed version for use in template
            task.script_args = scriptArgs;

            // Determine which action buttons to show
            const showRetry = ['completed', 'failed', 'cancelled'].includes(task.status);

            // Create modal
            const modal = document.createElement('div');
            modal.className = 'task-details-modal';
            modal.innerHTML = `
                <div class="task-details-backdrop" onclick="this.parentElement.remove()"></div>
                <div class="task-details-content">
                    <div class="task-details-header">
                        <h3>Task Details</h3>
                        <div class="task-details-header-actions">
                            <button class="task-details-action-btn" onclick="taskSchedulerAction('loadToUI', '${task.id}', '${task.task_type}'); this.closest('.task-details-modal').remove();" title="Load parameters to UI">📋 Load to UI</button>
                            ${showRetry ? `<button class="task-details-action-btn" onclick="taskSchedulerAction('retry', '${task.id}'); this.closest('.task-details-modal').remove();" title="Requeue this task">↻ Requeue</button>` : ''}
                            <button class="task-details-close" onclick="this.closest('.task-details-modal').remove()">✕</button>
                        </div>
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
                                ${params.styles && params.styles.length > 0 ? `<tr><td>Styles</td><td>${params.styles.join(', ')}</td></tr>` : ''}
                                <tr><td>Size</td><td>${params.width || 512} × ${params.height || 512}</td></tr>
                                <tr><td>Steps</td><td>${params.steps || 20}</td></tr>
                                <tr><td>CFG Scale</td><td>${params.cfg_scale || 7}</td></tr>
                                ${params.distilled_cfg_scale !== undefined && params.distilled_cfg_scale !== null ? `<tr><td>Distilled CFG</td><td>${params.distilled_cfg_scale}</td></tr>` : ''}
                                <tr><td>Sampler</td><td>${params.sampler_name || 'Euler'}</td></tr>
                                <tr><td>Scheduler</td><td>${params.scheduler || 'automatic'}</td></tr>
                                <tr><td>Seed</td><td>${params.seed || -1}</td></tr>
                                ${params.subseed !== undefined && params.subseed !== -1 ? `<tr><td>Subseed</td><td>${params.subseed} (strength: ${params.subseed_strength || 0})</td></tr>` : ''}
                                <tr><td>Batch Size</td><td>${params.batch_size || 1}</td></tr>
                                <tr><td>Batch Count</td><td>${params.n_iter || 1}</td></tr>
                                ${params.denoising_strength !== undefined ? `<tr><td>Denoising</td><td>${params.denoising_strength}</td></tr>` : ''}
                                ${params.restore_faces ? `<tr><td>Restore Faces</td><td>Yes</td></tr>` : ''}
                                ${params.tiling ? `<tr><td>Tiling</td><td>Yes</td></tr>` : ''}
                            </table>
                        </div>
                        ${params.override_settings && Object.keys(params.override_settings).length > 0 ? `
                        <div class="task-details-section">
                            <h4>Model Overrides</h4>
                            <table class="task-details-table">
                                ${Object.entries(params.override_settings).map(([key, value]) => {
                                    const displayKey = key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
                                    let displayValue = value;
                                    if (value === null || value === undefined) {
                                        displayValue = '<span class="arg-null">None</span>';
                                    } else if (typeof value === 'boolean') {
                                        displayValue = value ? 'Yes' : 'No';
                                    } else if (typeof value === 'object') {
                                        displayValue = JSON.stringify(value);
                                    }
                                    return `<tr><td>${displayKey}</td><td>${displayValue}</td></tr>`;
                                }).join('')}
                            </table>
                        </div>
                        ` : ''}
                        ${params.ui_settings && Object.keys(params.ui_settings).length > 0 ? `
                        <div class="task-details-section">
                            <h4>UI Settings</h4>
                            <table class="task-details-table">
                                ${Object.entries(params.ui_settings).map(([key, value]) => {
                                    // Format setting name to be more readable
                                    const displayKey = key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
                                    let displayValue = value;
                                    if (value === null || value === undefined) {
                                        displayValue = '<span class="arg-null">None</span>';
                                    } else if (typeof value === 'boolean') {
                                        displayValue = value ? 'Yes' : 'No';
                                    } else if (typeof value === 'object') {
                                        displayValue = JSON.stringify(value);
                                    }
                                    return `<tr><td>${displayKey}</td><td>${displayValue}</td></tr>`;
                                }).join('')}
                            </table>
                        </div>
                        ` : ''}
                        ${params.enable_hr ? `
                        <div class="task-details-section">
                            <h4>Hires Fix</h4>
                            <table class="task-details-table">
                                <tr><td>Enabled</td><td>Yes</td></tr>
                                <tr><td>Scale</td><td>${params.hr_scale || 2}x</td></tr>
                                <tr><td>Upscaler</td><td>${params.hr_upscaler || 'Latent'}</td></tr>
                                <tr><td>Steps</td><td>${params.hr_second_pass_steps || 0}</td></tr>
                                ${params.hr_resize_x ? `<tr><td>Resize To</td><td>${params.hr_resize_x} × ${params.hr_resize_y}</td></tr>` : ''}
                                ${params.hr_sampler_name ? `<tr><td>Sampler</td><td>${params.hr_sampler_name}</td></tr>` : ''}
                                ${params.hr_prompt ? `<tr><td>HR Prompt</td><td class="task-prompt-cell">${params.hr_prompt}</td></tr>` : ''}
                            </table>
                        </div>
                        ` : ''}
                        ${params.extra_generation_params && Object.keys(params.extra_generation_params).length > 0 ? `
                        <div class="task-details-section">
                            <h4>Extension Parameters</h4>
                            <table class="task-details-table">
                                ${Object.entries(params.extra_generation_params).map(([key, value]) => {
                                    let displayValue = value;
                                    if (typeof value === 'object') {
                                        displayValue = JSON.stringify(value, null, 2);
                                    }
                                    return `<tr><td>${key}</td><td class="task-prompt-cell">${displayValue}</td></tr>`;
                                }).join('')}
                            </table>
                        </div>
                        ` : ''}
                        ${task.script_args && task.script_args.length > 0 ? `
                        <div class="task-details-section">
                            <h4>Script Arguments (${task.script_args.length} total)</h4>
                            <details class="script-args-expander">
                                <summary class="script-args-summary">Click to expand all script arguments</summary>
                                <div class="script-args-list">
                                    ${(() => {
                                        // Check for labeled format in params._script_args_labeled
                                        const labeledArgs = params._script_args_labeled;
                                        const hasLabeledFormat = labeledArgs && Array.isArray(labeledArgs) && labeledArgs.length > 0;

                                        if (hasLabeledFormat) {
                                            // Group by script
                                            const byScript = {};
                                            labeledArgs.forEach(arg => {
                                                const scriptName = arg.script || 'Core';
                                                if (!byScript[scriptName]) byScript[scriptName] = [];
                                                byScript[scriptName].push(arg);
                                            });

                                            return Object.entries(byScript).map(([scriptName, args]) => {
                                                const argsHtml = args.map(arg => {
                                                    let valueDisplay = '';
                                                    const val = arg.value;
                                                    if (val === null || val === undefined) {
                                                        valueDisplay = '<span class="arg-null">null</span>';
                                                    } else if (typeof val === 'boolean') {
                                                        valueDisplay = '<span class="arg-bool">' + val + '</span>';
                                                    } else if (typeof val === 'number') {
                                                        valueDisplay = '<span class="arg-number">' + val + '</span>';
                                                    } else if (typeof val === 'string' && val.length > 100) {
                                                        valueDisplay = '<span class="arg-value">' + val.substring(0, 100).replace(/</g, '&lt;') + '...</span>';
                                                    } else if (typeof val === 'object') {
                                                        let json = JSON.stringify(val, null, 2);
                                                        if (json.length > 200) json = json.substring(0, 200) + '...';
                                                        valueDisplay = '<pre class="arg-json">' + json.replace(/</g, '&lt;') + '</pre>';
                                                    } else {
                                                        valueDisplay = '<span class="arg-value">' + String(val).replace(/</g, '&lt;') + '</span>';
                                                    }

                                                    return '<div class="arg-item">' +
                                                        '<span class="arg-index">[' + arg.index + ']</span>' +
                                                        '<span class="arg-name" title="' + (arg.name || '').replace(/"/g, '&quot;') + '">' + (arg.label || arg.name || 'Unknown') + '</span>' +
                                                        '<span class="arg-value-container">' + valueDisplay + '</span>' +
                                                        '</div>';
                                                }).join('');

                                                return '<div class="script-group">' +
                                                    '<div class="script-group-header">' + scriptName + ' (' + args.length + ' args)</div>' +
                                                    '<div class="script-group-args">' + argsHtml + '</div>' +
                                                    '</div>';
                                            }).join('');
                                        } else {
                                            // Raw format - just show raw values
                                            return task.script_args.map((item, idx) => {
                                                let rawJson;
                                                try {
                                                    rawJson = JSON.stringify(item, null, 2);
                                                    if (rawJson.length > 500) rawJson = rawJson.substring(0, 500) + '...';
                                                } catch(e) {
                                                    rawJson = '[Cannot serialize]';
                                                }
                                                const escapedRaw = rawJson.replace(/</g, '&lt;').replace(/>/g, '&gt;');
                                                return '<div class="arg-item"><span class="arg-index">[' + idx + ']</span><pre class="arg-raw">' + escapedRaw + '</pre></div>';
                                            }).join('');
                                        }
                                    })()}
                                </div>
                            </details>
                        </div>
                        ` : ''}
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
    window.taskSchedulerAction = function(action, taskId, taskType) {
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
        } else if (action === 'loadToUI') {
            loadTaskToUI(taskId, taskType);
        }
    };

    // Build generation info string from task params (PNG metadata format)
    function buildGenerationInfo(params, taskType, checkpoint) {
        let info = params.prompt || '';

        // Add negative prompt
        if (params.negative_prompt) {
            info += `\nNegative prompt: ${params.negative_prompt}`;
        }

        // Build settings line
        let settings = [];
        if (params.steps) settings.push(`Steps: ${params.steps}`);
        if (params.sampler_name) settings.push(`Sampler: ${params.sampler_name}`);
        if (params.scheduler && params.scheduler !== 'automatic') settings.push(`Schedule type: ${params.scheduler}`);
        if (params.cfg_scale) settings.push(`CFG scale: ${params.cfg_scale}`);
        if (params.distilled_cfg_scale !== undefined && params.distilled_cfg_scale !== null) {
            settings.push(`Distilled CFG Scale: ${params.distilled_cfg_scale}`);
        }
        if (params.seed !== undefined) settings.push(`Seed: ${params.seed}`);
        if (params.width && params.height) settings.push(`Size: ${params.width}x${params.height}`);

        // Model/Checkpoint
        if (checkpoint) {
            settings.push(`Model: ${checkpoint}`);
        }

        // Settings from shared.opts (VAE, eta, clip skip, etc.)
        const uiSettings = params.ui_settings || {};
        if (uiSettings.sd_vae && uiSettings.sd_vae !== 'Automatic' && uiSettings.sd_vae !== 'None') {
            settings.push(`VAE: ${uiSettings.sd_vae}`);
        }
        if (uiSettings.CLIP_stop_at_last_layers && uiSettings.CLIP_stop_at_last_layers > 1) {
            settings.push(`Clip skip: ${uiSettings.CLIP_stop_at_last_layers}`);
        }
        if (uiSettings.eta_noise_seed_delta) {
            settings.push(`ENSD: ${uiSettings.eta_noise_seed_delta}`);
        }
        if (uiSettings.eta_ancestral !== undefined && uiSettings.eta_ancestral !== null && uiSettings.eta_ancestral !== 1) {
            settings.push(`Eta: ${uiSettings.eta_ancestral}`);
        }
        if (uiSettings.eta_ddim !== undefined && uiSettings.eta_ddim !== null && uiSettings.eta_ddim !== 0) {
            settings.push(`Eta DDIM: ${uiSettings.eta_ddim}`);
        }
        if (uiSettings.s_churn) settings.push(`Sigma churn: ${uiSettings.s_churn}`);
        if (uiSettings.s_tmin) settings.push(`Sigma tmin: ${uiSettings.s_tmin}`);
        if (uiSettings.s_tmax && uiSettings.s_tmax !== Infinity) settings.push(`Sigma tmax: ${uiSettings.s_tmax}`);
        if (uiSettings.s_noise && uiSettings.s_noise !== 1) settings.push(`Sigma noise: ${uiSettings.s_noise}`);

        // Hires fix
        if (params.enable_hr) {
            settings.push(`Hires upscale: ${params.hr_scale || 2}`);
            if (params.hr_upscaler) settings.push(`Hires upscaler: ${params.hr_upscaler}`);
            if (params.hr_second_pass_steps) settings.push(`Hires steps: ${params.hr_second_pass_steps}`);
            if (params.denoising_strength) settings.push(`Denoising strength: ${params.denoising_strength}`);
        }

        // img2img denoising
        if (taskType === 'img2img' && params.denoising_strength !== undefined) {
            settings.push(`Denoising strength: ${params.denoising_strength}`);
        }

        // Add extra_generation_params (contains extension settings like ControlNet, ADetailer, etc.)
        if (params.extra_generation_params) {
            for (const [key, value] of Object.entries(params.extra_generation_params)) {
                if (value !== null && value !== undefined && value !== '') {
                    settings.push(`${key}: ${value}`);
                }
            }
        }

        if (settings.length > 0) {
            info += `\n${settings.join(', ')}`;
        }

        return info;
    }

    // Load task parameters to the UI using paste functionality
    async function loadTaskToUI(taskId, taskType) {
        try {
            const response = await fetch(`/task-scheduler/queue/${taskId}`);
            const data = await response.json();

            if (!data.success || !data.task) {
                showNotification('Failed to load task', 'error');
                return;
            }

            const task = data.task;
            let params = task.params;
            if (typeof params === 'string') {
                try { params = JSON.parse(params); } catch(e) { params = {}; }
            }

            const tabPrefix = taskType === 'img2img' ? 'img2img' : 'txt2img';

            // Switch to the correct tab
            const tabButton = document.querySelector(`#tabs > div > button[id$="${tabPrefix}_tab"]`) ||
                              document.querySelector(`button[data-tab="${tabPrefix}"]`) ||
                              Array.from(document.querySelectorAll('#tabs button')).find(b => b.textContent.toLowerCase().includes(tabPrefix));
            if (tabButton) {
                tabButton.click();
                await new Promise(resolve => setTimeout(resolve, 200));
            }

            // Build generation info string
            const genInfo = buildGenerationInfo(params, taskType, task.checkpoint);
            console.log('[TaskScheduler] Generation info to paste:', genInfo);

            // Use the paste functionality (same approach as civitai-browser-plus)
            const promptTextarea = gradioApp().querySelector(`#${tabPrefix}_prompt textarea`);
            const pasteButton = gradioApp().querySelector('#paste');

            if (promptTextarea && pasteButton) {
                // Set the generation info in the prompt textarea
                promptTextarea.value = genInfo;
                promptTextarea.dispatchEvent(new Event('input', { bubbles: true }));

                // Small delay then click paste to parse and populate all fields
                await new Promise(resolve => setTimeout(resolve, 100));
                pasteButton.click();

                // Wait for paste to complete
                await new Promise(resolve => setTimeout(resolve, 300));

                // Handle checkpoint and VAE separately (paste doesn't switch these)
                await setCheckpointAndVAE(task.checkpoint, params.ui_settings);

                showNotification(`Loaded ${taskType} parameters to UI`, 'success');
            } else {
                // Fallback: try direct field setting for basic params
                console.warn('[TaskScheduler] Paste button not found, using fallback method');
                await loadTaskToUIFallback(params, taskType, tabPrefix);
            }

            console.log('[TaskScheduler] Loaded task params to UI:', params);

        } catch (error) {
            console.error('[TaskScheduler] Error loading task to UI:', error);
            showNotification('Error loading task to UI', 'error');
        }
    }

    // Set checkpoint and VAE using WebUI's internal functions
    async function setCheckpointAndVAE(checkpoint, uiSettings) {
        try {
            let needsChange = false;

            // Use WebUI's selectCheckpoint function
            if (checkpoint) {
                if (typeof selectCheckpoint === 'function') {
                    selectCheckpoint(checkpoint);
                    needsChange = true;
                    console.log('[TaskScheduler] Called selectCheckpoint:', checkpoint);
                } else {
                    console.warn('[TaskScheduler] selectCheckpoint function not available');
                }
            }

            // Use WebUI's selectVAE function
            if (uiSettings && uiSettings.sd_vae && uiSettings.sd_vae !== 'Automatic' && uiSettings.sd_vae !== 'None') {
                if (typeof selectVAE === 'function') {
                    selectVAE(uiSettings.sd_vae);
                    needsChange = true;
                    console.log('[TaskScheduler] Called selectVAE:', uiSettings.sd_vae);
                } else {
                    console.warn('[TaskScheduler] selectVAE function not available');
                }
            }

            // The change_checkpoint button triggers the actual switch
            // selectCheckpoint already clicks it, but if only VAE changed we need to trigger it
            if (needsChange && !checkpoint) {
                const changeBtn = gradioApp().getElementById('change_checkpoint');
                if (changeBtn) {
                    changeBtn.click();
                    console.log('[TaskScheduler] Clicked change_checkpoint button');
                } else {
                    console.warn('[TaskScheduler] change_checkpoint button not found');
                }
            }

            // Wait for model loading to complete
            await new Promise(resolve => setTimeout(resolve, 500));
        } catch (error) {
            console.warn('[TaskScheduler] Error setting checkpoint/VAE:', error);
        }
    }

    // Fallback method for loading params if paste button is not available
    async function loadTaskToUIFallback(params, taskType, tabPrefix) {
        const setGradioValue = (elemId, value) => {
            if (value === undefined || value === null) return;
            const container = document.getElementById(elemId);
            if (!container) return;

            const textarea = container.querySelector('textarea');
            if (textarea) {
                textarea.value = value;
                textarea.dispatchEvent(new Event('input', { bubbles: true }));
                return;
            }

            const input = container.querySelector('input');
            if (input) {
                if (input.type === 'checkbox') {
                    input.checked = !!value;
                    input.dispatchEvent(new Event('change', { bubbles: true }));
                } else {
                    input.value = value;
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                }
                return;
            }
        };

        setGradioValue(`${tabPrefix}_prompt`, params.prompt || '');
        setGradioValue(`${tabPrefix}_neg_prompt`, params.negative_prompt || '');
        setGradioValue(`${tabPrefix}_steps`, params.steps);
        setGradioValue(`${tabPrefix}_cfg_scale`, params.cfg_scale);
        setGradioValue(`${tabPrefix}_width`, params.width);
        setGradioValue(`${tabPrefix}_height`, params.height);
        setGradioValue(`${tabPrefix}_seed`, params.seed);

        showNotification(`Loaded basic ${taskType} parameters (paste unavailable)`, 'info');
    }

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
                refreshSettings(true);
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
                            refreshSettings(true);
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
        console.log('[TaskScheduler] Initializing JavaScript (Queue buttons created via Gradio)...');

        // Start auto-refresh for task list
        startAutoRefresh();

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
            /* Gradio Queue buttons styling */
            #txt2img_queue, #img2img_queue {
                min-width: 80px !important;
                white-space: nowrap !important;
                font-weight: 500 !important;
            }
            /* Responsive: stack vertically on very small screens */
            @media (max-width: 600px) {
                #txt2img_queue, #img2img_queue {
                    margin-top: 8px !important;
                    width: 100% !important;
                }
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
                width: 80%;
                height: 80%;
                overflow: hidden;
                box-shadow: 0 20px 40px rgba(0,0,0,0.4);
                display: flex;
                flex-direction: column;
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
            .task-details-header-actions {
                display: flex;
                align-items: center;
                gap: 8px;
            }
            .task-details-action-btn {
                background: var(--button-secondary-background-fill, #374151);
                border: 1px solid var(--button-secondary-border-color, #4b5563);
                border-radius: 6px;
                padding: 6px 12px;
                cursor: pointer;
                color: var(--body-text-color, #fff);
                font-size: 0.9em;
                transition: background 0.2s;
            }
            .task-details-action-btn:hover {
                background: var(--button-secondary-background-fill-hover, #4b5563);
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
                flex: 1;
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
            /* Script Args Expander */
            .script-args-expander {
                background: rgba(33, 150, 243, 0.05);
                border: 1px solid rgba(33, 150, 243, 0.2);
                border-radius: 8px;
                overflow: hidden;
            }
            .script-args-summary {
                padding: 12px 16px;
                cursor: pointer;
                color: #2196F3;
                font-weight: 500;
                user-select: none;
                transition: background 0.2s;
            }
            .script-args-summary:hover {
                background: rgba(33, 150, 243, 0.1);
            }
            .script-args-list {
                max-height: 400px;
                overflow-y: auto;
                padding: 8px;
                background: rgba(0,0,0,0.1);
            }
            .arg-item {
                display: flex;
                gap: 10px;
                padding: 8px 12px;
                margin-bottom: 4px;
                background: rgba(0,0,0,0.15);
                border-radius: 4px;
                align-items: flex-start;
            }
            .arg-index {
                color: #9ca3af;
                min-width: 45px;
                flex-shrink: 0;
                font-family: monospace;
            }
            .arg-raw {
                flex: 1;
                margin: 0;
                padding: 4px 8px;
                background: rgba(0,0,0,0.2);
                border-radius: 4px;
                font-size: 0.9em;
                white-space: pre-wrap;
                word-break: break-word;
                max-height: 150px;
                overflow-y: auto;
            }
            .arg-name {
                color: #60a5fa;
                min-width: 180px;
                max-width: 220px;
                flex-shrink: 0;
                font-weight: 500;
                word-break: break-word;
            }
            .arg-value {
                flex: 1;
                word-break: break-word;
                color: #e5e7eb;
            }
            .arg-null { color: #9ca3af; font-style: italic; }
            .arg-bool { color: #f59e0b; }
            .arg-number { color: #10b981; }
            .arg-image { color: #8b5cf6; }
            .arg-converted { color: #ec4899; }
            .arg-error { color: #ef4444; }
            .arg-json {
                margin: 0;
                padding: 4px;
                background: rgba(0,0,0,0.2);
                border-radius: 3px;
                font-size: 0.9em;
                white-space: pre-wrap;
                max-height: 100px;
                overflow-y: auto;
            }
            .arg-value-container {
                flex: 1;
                min-width: 0;
            }
            /* Script groups for labeled args */
            .script-group {
                margin-bottom: 12px;
                border: 1px solid rgba(255,255,255,0.1);
                border-radius: 6px;
                overflow: hidden;
            }
            .script-group-header {
                background: rgba(33, 150, 243, 0.15);
                padding: 8px 12px;
                font-weight: 600;
                color: #60a5fa;
                font-size: 0.9em;
            }
            .script-group-args {
                padding: 4px;
            }
            .script-group .arg-item {
                display: grid;
                grid-template-columns: 50px 180px 1fr;
                gap: 8px;
                padding: 6px 10px;
                margin: 2px 0;
                background: rgba(0,0,0,0.1);
                border-radius: 4px;
                align-items: start;
            }
            .script-group .arg-name {
                color: #60a5fa;
                font-weight: 500;
                word-break: break-word;
                font-size: 0.9em;
            }
            /* Task sections */
            .task-section {
                margin-bottom: 16px;
            }
            .task-section-header {
                font-size: 1em;
                font-weight: 600;
                margin: 0 0 8px 0;
                padding: 8px 12px;
                background: var(--block-background-fill, #1f2937);
                border-radius: 6px;
                color: var(--body-text-color, #fff);
            }
            .task-section-active .task-section-header {
                background: linear-gradient(135deg, rgba(33, 150, 243, 0.15), rgba(76, 175, 80, 0.15));
                border-left: 3px solid #2196F3;
            }
            .task-history-details {
                background: var(--block-background-fill, #1f2937);
                border-radius: 8px;
                overflow: hidden;
            }
            .task-history-summary {
                cursor: pointer;
                user-select: none;
                margin: 0;
                background: rgba(158, 158, 158, 0.1);
                border-left: 3px solid #9E9E9E;
            }
            .task-history-summary:hover {
                background: rgba(158, 158, 158, 0.2);
            }
            .task-list-history {
                padding-top: 8px;
            }
            .task-list-history .task-item {
                opacity: 0.8;
            }
            .task-empty-small {
                text-align: center;
                padding: 16px;
                color: var(--body-text-color-subdued, #9ca3af);
                font-size: 0.9em;
            }
            /* Settings status in top right corner */
            .settings-status {
                display: flex;
                align-items: center;
                gap: 8px;
                padding: 8px 12px;
                border-radius: 6px;
                background: var(--block-background-fill, #1f2937);
                border: 1px solid var(--border-color-primary, #374151);
            }
            .settings-status.enabled {
                border-color: rgba(76, 175, 80, 0.5);
                background: rgba(76, 175, 80, 0.1);
            }
            .settings-status.disabled {
                border-color: rgba(158, 158, 158, 0.5);
                background: rgba(158, 158, 158, 0.1);
            }
            .settings-label {
                color: var(--body-text-color-subdued, #9ca3af);
            }
            .settings-value {
                font-weight: 600;
            }
            .settings-status.enabled .settings-value {
                color: #4CAF50;
            }
            .settings-status.disabled .settings-value {
                color: #9E9E9E;
            }
            .settings-hint {
                color: var(--body-text-color-subdued, #9ca3af);
                font-style: italic;
            }
            /* Header row with title on left and settings on right */
            .task-queue-header-row {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 10px;
            }
            .task-queue-header-row h2 {
                margin: 0;
            }
        `;
        document.head.appendChild(style);
    }

    onReady(init);
})();
