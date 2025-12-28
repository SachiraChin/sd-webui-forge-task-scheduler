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

    // Selection mode state for each list
    let selectionMode = {
        active: false,
        history: false
    };
    let selectedTasks = {
        active: new Set(),
        history: new Set()
    };

    // Current tab in task list (active, history, bookmarks)
    let currentTaskTab = 'active';

    // Bookmarks cache
    let bookmarksCache = [];
    let bookmarksLoaded = false;
    let bookmarkPromptName = false;

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

    // Track if any task is currently running
    let isAnyTaskRunning = false;

    // Large batch warning settings
    let largeBatchWarningThreshold = 1;
    let bypassLargeBatchWarning = false;

    // Render a single task item
    function renderTaskItem(task, index, listType) {
        const statusIcons = {
            'pending': '⏳',
            'running': '🔄',
            'completed': '✅',
            'failed': '❌',
            'cancelled': '🚫',
            'stopped': '⏹️',
            'paused': '⏸️'
        };

        const statusClass = `status-${task.status}`;
        const statusIcon = statusIcons[task.status] || '';

        // Calculate total images (batch_size * n_iter)
        const batchSize = task.batch_size || 1;
        const nIter = task.n_iter || 1;
        const totalImages = batchSize * nIter;

        // Image size info
        const width = task.width || 512;
        const height = task.height || 512;
        let sizeInfo = `${width}×${height}`;
        if (task.enable_hr && task.upscaled_width && task.upscaled_height) {
            sizeInfo += ` → ${task.upscaled_width}×${task.upscaled_height}`;
        }

        // Checkpoint - extract just the filename from path
        let checkpointName = task.checkpoint || 'Default';
        if (checkpointName.includes('/') || checkpointName.includes('\\')) {
            checkpointName = checkpointName.split(/[/\\]/).pop();
        }
        // Remove extension if present
        checkpointName = checkpointName.replace(/\.(safetensors|ckpt|pt)$/i, '');

        // VAE - already just filename from API
        const vaeInfo = task.vae ? task.vae.replace(/\.(safetensors|ckpt|pt)$/i, '') : '';

        // Sampler info
        let samplerInfo = task.sampler_name || 'Euler';
        if (task.scheduler && task.scheduler !== 'automatic') {
            samplerInfo += ` / ${task.scheduler}`;
        }

        // Date formatting: yyyy-MM-dd hh:mm am/pm
        const formatDate = (isoString) => {
            if (!isoString) return '';
            const date = new Date(isoString);
            const yyyy = date.getFullYear();
            const MM = String(date.getMonth() + 1).padStart(2, '0');
            const dd = String(date.getDate()).padStart(2, '0');
            let hh = date.getHours();
            const mm = String(date.getMinutes()).padStart(2, '0');
            const ampm = hh >= 12 ? 'PM' : 'AM';
            hh = hh % 12 || 12;
            return `${yyyy}-${MM}-${dd} ${hh}:${mm} ${ampm}`;
        };

        // Dates for display
        const createdDate = formatDate(task.created_at);
        const completedDate = formatDate(task.completed_at);

        // Build date display based on list type
        let dateHtml = '';
        if (listType === 'active') {
            dateHtml = createdDate ? `<span class='task-date' title="Created">${createdDate}</span>` : '';
        } else {
            // History - show both dates
            let dates = [];
            if (createdDate) dates.push(`Created: ${createdDate}`);
            if (completedDate) dates.push(`${task.status === 'completed' ? 'Completed' : task.status === 'failed' ? 'Failed' : 'Ended'}: ${completedDate}`);
            dateHtml = dates.length ? `<span class='task-date'>${dates.join(' | ')}</span>` : '';
        }

        // Checkbox for selection mode
        const inSelectionMode = selectionMode[listType];
        const isSelected = selectedTasks[listType].has(task.id);
        const checkboxHtml = inSelectionMode
            ? `<div class='task-checkbox'><input type='checkbox' ${isSelected ? 'checked' : ''} onclick='event.stopPropagation()' onchange='taskSchedulerToggleSelect("${listType}", "${task.id}", this.checked)' /></div>`
            : '';

        // Show "Requeued" badge for history tasks that have been requeued
        const requeuedBadge = (listType === 'history' && task.requeued_task_id)
            ? '<span class="requeued-badge">Requeued</span>'
            : '';

        let actionsHtml = '';

        // Only show individual action buttons when NOT in selection mode
        if (!inSelectionMode) {
            // Run button for pending tasks (disabled if any task is running)
            if (task.status === 'pending') {
                const runDisabled = isAnyTaskRunning ? 'disabled' : '';
                const runClass = isAnyTaskRunning ? 'task-btn-disabled' : 'task-btn-run';
                actionsHtml += `<button class="task-btn ${runClass}" onclick='taskSchedulerAction("run", "${task.id}")' title="Run this task now" ${runDisabled}><span class="btn-icon">▶️</span><span class="btn-text">Run</span></button>`;
            }

            actionsHtml += `<button class="task-btn task-btn-info" onclick='taskSchedulerAction("info", "${task.id}")' title="View task details"><span class="btn-icon">ℹ️</span><span class="btn-text">Info</span></button>`;
            actionsHtml += `<button class="task-btn task-btn-load" onclick='taskSchedulerAction("loadToUI", "${task.id}", "${task.task_type}")' title="Load to UI"><span class="btn-icon">📋</span><span class="btn-text">Load</span></button>`;
            if (task.status === 'completed' || task.status === 'failed' || task.status === 'cancelled' || task.status === 'stopped') {
                actionsHtml += `<button class="task-btn task-btn-retry" onclick='taskSchedulerAction("retry", "${task.id}")' title="Requeue this task"><span class="btn-icon">↻</span><span class="btn-text">Retry</span></button>`;
            }
            if (task.status !== 'running' && task.status !== 'paused') {
                actionsHtml += `<button class="task-btn task-btn-delete" onclick='taskSchedulerAction("delete", "${task.id}")' title="Delete this task"><span class="btn-icon">🗑️</span><span class="btn-text">Delete</span></button>`;
            }
        }

        return `
        <div class='task-item ${statusClass} ${isSelected ? 'selected' : ''}' data-task-id='${task.id}'>
            ${checkboxHtml}
            <div class='task-index'>${index}</div>
            <div class='task-info'>
                <div class='task-header'>
                    <span class='task-type'>${task.task_type.toUpperCase()} ${requeuedBadge}</span>
                    <span class='task-size'>${sizeInfo}</span>
                    <span class='task-images'>${totalImages} img</span>
                    <span class='task-checkpoint' title="${task.checkpoint || ''}">${checkpointName}</span>
                    ${vaeInfo ? `<span class='task-vae' title="${task.vae}">${vaeInfo}</span>` : ''}
                </div>
                <div class='task-meta'>
                    <span class='task-sampler'>${samplerInfo}</span>
                    ${dateHtml}
                </div>
            </div>
            <div class='task-status'><span class='status-badge'>${statusIcon} ${task.status}</span></div>
            <div class='task-actions'>${actionsHtml}</div>
        </div>
        `;
    }

    // Render selection header buttons for a list type
    function renderSelectionHeader(listType, count) {
        const inSelectionMode = selectionMode[listType];
        const selectedCount = selectedTasks[listType].size;

        if (inSelectionMode) {
            // Show action buttons based on list type
            let actionButtons = '';
            if (listType === 'active') {
                actionButtons = `
                    <button class="section-btn section-btn-start" onclick='event.stopPropagation(); taskSchedulerBatchAction("active", "start")' title="Start selected tasks">
                        <span class="btn-icon">▶️</span> Start (${selectedCount})
                    </button>
                    <button class="section-btn section-btn-delete" onclick='event.stopPropagation(); taskSchedulerBatchAction("active", "delete")' title="Delete selected tasks">
                        <span class="btn-icon">🗑️</span> Delete (${selectedCount})
                    </button>
                `;
            } else {
                actionButtons = `
                    <button class="section-btn section-btn-requeue" onclick='event.stopPropagation(); taskSchedulerBatchAction("history", "requeue")' title="Requeue selected tasks">
                        <span class="btn-icon">↻</span> Requeue (${selectedCount})
                    </button>
                    <button class="section-btn section-btn-delete" onclick='event.stopPropagation(); taskSchedulerBatchAction("history", "delete")' title="Delete selected tasks">
                        <span class="btn-icon">🗑️</span> Delete (${selectedCount})
                    </button>
                `;
            }

            return `
                <div class="section-actions">
                    <button class="section-btn section-btn-cancel" onclick='event.stopPropagation(); taskSchedulerExitSelectionMode("${listType}")' title="Cancel selection">
                        Cancel
                    </button>
                    <button class="section-btn section-btn-select-all" onclick='event.stopPropagation(); taskSchedulerSelectAll("${listType}")' title="Select all">
                        Select All
                    </button>
                    ${actionButtons}
                </div>
            `;
        } else {
            return `
                <div class="section-actions">
                    <button class="section-btn section-btn-select" onclick='event.stopPropagation(); taskSchedulerEnterSelectionMode("${listType}")' title="Select multiple tasks">
                        Select
                    </button>
                </div>
            `;
        }
    }

    // Render task list HTML with tabbed interface (Active, History, Bookmarks)
    function renderTaskList(tasks) {
        // Separate active (pending/running/paused) from history (completed/failed/cancelled/stopped)
        const activeTasks = tasks ? tasks.filter(t => t.status === 'pending' || t.status === 'running' || t.status === 'paused') : [];
        const historyTasks = tasks ? tasks.filter(t => t.status === 'completed' || t.status === 'failed' || t.status === 'cancelled' || t.status === 'stopped') : [];

        // Clean up selected tasks that no longer exist
        const activeIds = new Set(activeTasks.map(t => t.id));
        const historyIds = new Set(historyTasks.map(t => t.id));
        selectedTasks.active = new Set([...selectedTasks.active].filter(id => activeIds.has(id)));
        selectedTasks.history = new Set([...selectedTasks.history].filter(id => historyIds.has(id)));

        let html = '';

        // Tab header
        html += "<div class='ts-tabs'>";
        html += `<button class='ts-tab ${currentTaskTab === 'active' ? 'active' : ''}' onclick='window.switchTaskTab("active")'>
            <span class='ts-tab-icon'>📋</span>
            <span class='ts-tab-label'>Active</span>
            <span class='ts-tab-count'>${activeTasks.length}</span>
        </button>`;
        html += `<button class='ts-tab ${currentTaskTab === 'history' ? 'active' : ''}' onclick='window.switchTaskTab("history")'>
            <span class='ts-tab-icon'>📜</span>
            <span class='ts-tab-label'>History</span>
            <span class='ts-tab-count'>${historyTasks.length}</span>
        </button>`;
        html += `<button class='ts-tab ${currentTaskTab === 'bookmarks' ? 'active' : ''}' onclick='window.switchTaskTab("bookmarks")'>
            <span class='ts-tab-icon'>⭐</span>
            <span class='ts-tab-label'>Bookmarks</span>
            <span class='ts-tab-count'>${bookmarksCache.length}</span>
        </button>`;
        html += "</div>";

        // Tab content
        html += "<div class='ts-tab-content'>";

        // Active tab content
        if (currentTaskTab === 'active') {
            html += "<div class='ts-tab-panel'>";
            if (activeTasks.length > 0) {
                html += `<div class='ts-panel-header'>
                    ${renderSelectionHeader('active', activeTasks.length)}
                </div>`;
                html += "<div class='task-list'>";
                activeTasks.forEach((task, i) => {
                    html += renderTaskItem(task, i + 1, 'active');
                });
                html += "</div>";
            } else {
                html += "<div class='task-empty'>No active tasks. Use the Queue button next to Generate to add tasks.</div>";
            }
            html += "</div>";
        }

        // History tab content
        if (currentTaskTab === 'history') {
            html += "<div class='ts-tab-panel'>";
            if (historyTasks.length > 0) {
                html += `<div class='ts-panel-header'>
                    ${renderSelectionHeader('history', historyTasks.length)}
                </div>`;
                html += "<div class='task-list task-list-history'>";
                historyTasks.forEach((task, i) => {
                    html += renderTaskItem(task, i + 1, 'history');
                });
                html += "</div>";
            } else {
                html += "<div class='task-empty'>No completed tasks yet.</div>";
            }
            html += "</div>";
        }

        // Bookmarks tab content
        if (currentTaskTab === 'bookmarks') {
            html += "<div class='ts-tab-panel'>";
            if (bookmarksCache.length > 0) {
                html += "<div class='task-list'>";
                bookmarksCache.forEach((bookmark, i) => {
                    html += renderBookmarkItem(bookmark, i + 1);
                });
                html += "</div>";
            } else {
                html += "<div class='task-empty'>";
                html += "<div class='ts-coming-soon'>";
                html += "<span class='ts-coming-soon-icon'>⭐</span>";
                html += "<h3>No Bookmarks Yet</h3>";
                html += "<p>Right-click the Queue button and select 'Bookmark' to save configurations.</p>";
                html += "</div>";
                html += "</div>";
            }
            html += "</div>";
        }

        html += "</div>";

        return html;
    }

    // Switch between task tabs
    window.switchTaskTab = function(tab) {
        currentTaskTab = tab;
        // Exit selection mode when switching tabs
        selectionMode.active = false;
        selectionMode.history = false;
        selectedTasks.active.clear();
        selectedTasks.history.clear();

        // Fetch bookmarks when switching to bookmarks tab
        if (tab === 'bookmarks') {
            fetchBookmarks().then(() => refreshTaskList(true));
        } else {
            refreshTaskList(true);
        }
    };

    // Render a bookmark item
    function renderBookmarkItem(bookmark, index) {
        const params = bookmark.params || {};
        const taskType = bookmark.task_type || 'txt2img';
        const checkpoint = bookmark.checkpoint || '';
        const shortCheckpoint = checkpoint.split(/[/\\]/).pop()?.replace(/\.[^.]+$/, '') || 'No model';

        // Extract display info
        const width = params.width || 512;
        const height = params.height || 512;
        const sampler = params.sampler_name || 'Euler';
        const scheduler = params.scheduler || 'automatic';

        // Format created date
        let createdDate = '';
        if (bookmark.created_at) {
            const date = new Date(bookmark.created_at);
            createdDate = date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
        }

        // Display name or model name as title
        const displayName = bookmark.name || shortCheckpoint;

        return `
        <div class='task-item bookmark-item' data-bookmark-id='${bookmark.id}'>
            <div class='task-info'>
                <div class='task-header'>
                    <span class='bookmark-icon'>⭐</span>
                    <span class='bookmark-name'>${displayName}</span>
                    <span class='task-type'>${taskType}</span>
                </div>
                <div class='bookmark-details'>
                    <span class='bookmark-detail'><strong>Model:</strong> ${shortCheckpoint}</span>
                    <span class='bookmark-detail'><strong>Size:</strong> ${width}×${height}</span>
                    <span class='bookmark-detail'><strong>Sampler:</strong> ${sampler} / ${scheduler}</span>
                    <span class='bookmark-detail'><strong>Created:</strong> ${createdDate}</span>
                </div>
            </div>
            <div class='task-actions'>
                <button class='task-btn task-btn-info' onclick='window.bookmarkAction("info", "${bookmark.id}")' title='View Details'>ℹ️</button>
                <button class='task-btn task-btn-load' onclick='window.bookmarkAction("load", "${bookmark.id}", "${taskType}")' title='Send to ${taskType}'>📤</button>
                <button class='task-btn task-btn-delete' onclick='window.bookmarkAction("delete", "${bookmark.id}")' title='Delete'>🗑️</button>
            </div>
        </div>
        `;
    }

    // Fetch bookmarks from API
    async function fetchBookmarks() {
        try {
            const response = await fetch('/task-scheduler/bookmarks');
            const data = await response.json();
            if (data.success) {
                bookmarksCache = data.bookmarks || [];
                bookmarksLoaded = true;
            }
        } catch (error) {
            console.error('[TaskScheduler] Error fetching bookmarks:', error);
        }
    }

    // Handle bookmark actions
    window.bookmarkAction = function(action, bookmarkId, taskType) {
        if (action === 'info') {
            showBookmarkDetails(bookmarkId);
        } else if (action === 'load') {
            loadBookmarkToUI(bookmarkId, taskType);
        } else if (action === 'delete') {
            showConfirmModal({
                icon: '🗑️',
                title: 'Delete Bookmark',
                message: 'Are you sure you want to delete this bookmark?',
                confirmText: 'Delete',
                confirmClass: 'ts-confirm-btn-delete',
                onConfirm: () => {
                    deleteBookmark(bookmarkId);
                }
            });
        }
    };

    // Delete a bookmark
    async function deleteBookmark(bookmarkId) {
        try {
            const response = await fetch(`/task-scheduler/bookmarks/${bookmarkId}`, {
                method: 'DELETE'
            });
            const data = await response.json();
            if (data.success) {
                showNotification('Bookmark deleted', 'success');
                await fetchBookmarks();
                refreshTaskList(true);
            } else {
                showNotification('Failed to delete bookmark: ' + (data.error || 'Unknown error'), 'error');
            }
        } catch (error) {
            console.error('[TaskScheduler] Error deleting bookmark:', error);
            showNotification('Error deleting bookmark', 'error');
        }
    }

    // Load bookmark to UI (reuses loadTaskToUI logic)
    async function loadBookmarkToUI(bookmarkId, taskType) {
        try {
            const response = await fetch(`/task-scheduler/bookmarks/${bookmarkId}`);
            const data = await response.json();

            if (!data.success || !data.bookmark) {
                showNotification('Failed to load bookmark', 'error');
                return;
            }

            const bookmark = data.bookmark;
            let params = bookmark.params;
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
            const genInfo = buildGenerationInfo(params, taskType, bookmark.checkpoint);

            // Use the paste functionality
            const promptTextarea = gradioApp().querySelector(`#${tabPrefix}_prompt textarea`);
            const pasteButton = gradioApp().querySelector('#paste');

            if (promptTextarea && pasteButton) {
                promptTextarea.value = genInfo;
                promptTextarea.dispatchEvent(new Event('input', { bubbles: true }));

                await new Promise(resolve => setTimeout(resolve, 100));
                pasteButton.click();

                await new Promise(resolve => setTimeout(resolve, 300));

                // Handle checkpoint and VAE
                let vae = '';
                const forgeModules = params.ui_settings && params.ui_settings.forge_additional_modules;
                if (forgeModules && forgeModules.length > 0) {
                    const modulePath = forgeModules[0];
                    vae = modulePath.split(/[/\\]/).pop() || '';
                }
                if (!vae) {
                    vae = (params.override_settings && params.override_settings.sd_vae) ||
                          (params.ui_settings && params.ui_settings.sd_vae) || '';
                }
                await setCheckpointAndVAE(bookmark.checkpoint, vae);

                showNotification(`Loaded bookmark to ${taskType}`, 'success');
            } else {
                showNotification('Failed to load - paste button not found', 'error');
            }

        } catch (error) {
            console.error('[TaskScheduler] Error loading bookmark to UI:', error);
            showNotification('Error loading bookmark', 'error');
        }
    }

    // Show bookmark details modal
    async function showBookmarkDetails(bookmarkId) {
        try {
            const response = await fetch(`/task-scheduler/bookmarks/${bookmarkId}`);
            const data = await response.json();

            if (!data.success || !data.bookmark) {
                showNotification('Failed to load bookmark details', 'error');
                return;
            }

            const bookmark = data.bookmark;
            let params = bookmark.params;
            if (typeof params === 'string') {
                try { params = JSON.parse(params); } catch(e) { params = {}; }
            }

            // Reuse showTaskDetails modal structure
            const existingModal = document.querySelector('.task-details-modal');
            if (existingModal) existingModal.remove();

            const modal = document.createElement('div');
            modal.className = 'task-details-modal';

            const width = params.width || 512;
            const height = params.height || 512;
            const steps = params.steps || 20;

            modal.innerHTML = `
                <div class='task-details-backdrop' onclick='this.parentElement.remove()'></div>
                <div class='task-details-content'>
                    <div class='task-details-header'>
                        <h3>⭐ ${bookmark.name || 'Untitled Bookmark'}</h3>
                        <div class='task-details-header-actions'>
                            <button class='task-details-action-btn' onclick='window.bookmarkAction("load", "${bookmark.id}", "${bookmark.task_type}")'>📤 Send to UI</button>
                            <button class='task-details-close' onclick='this.closest(".task-details-modal").remove()'>×</button>
                        </div>
                    </div>
                    <div class='task-details-body'>
                        <div class='task-details-section'>
                            <h4>Basic Info</h4>
                            <table class='task-details-table'>
                                <tr><td>Type</td><td>${bookmark.task_type}</td></tr>
                                <tr><td>Checkpoint</td><td>${bookmark.checkpoint || 'Not set'}</td></tr>
                                <tr><td>Created</td><td>${bookmark.created_at || 'Unknown'}</td></tr>
                            </table>
                        </div>
                        <div class='task-details-section'>
                            <h4>Prompt</h4>
                            <div class='task-prompt-cell'>${params.prompt || '<em>No prompt</em>'}</div>
                        </div>
                        ${params.negative_prompt ? `
                        <div class='task-details-section'>
                            <h4>Negative Prompt</h4>
                            <div class='task-prompt-cell'>${params.negative_prompt}</div>
                        </div>
                        ` : ''}
                        <div class='task-details-section'>
                            <h4>Generation Settings</h4>
                            <table class='task-details-table'>
                                <tr><td>Size</td><td>${width} × ${height}</td></tr>
                                <tr><td>Steps</td><td>${steps}</td></tr>
                                <tr><td>CFG Scale</td><td>${params.cfg_scale || 7}</td></tr>
                                <tr><td>Sampler</td><td>${params.sampler_name || 'Euler'}</td></tr>
                                <tr><td>Scheduler</td><td>${params.scheduler || 'automatic'}</td></tr>
                                <tr><td>Seed</td><td>${params.seed || -1}</td></tr>
                            </table>
                        </div>
                    </div>
                </div>
            `;

            document.body.appendChild(modal);

        } catch (error) {
            console.error('[TaskScheduler] Error loading bookmark details:', error);
            showNotification('Error loading bookmark details', 'error');
        }
    }

    // Render queue status HTML
    function renderQueueStatus(status) {
        const stats = status.queue_stats || {};
        let runningStatus, statusClass;

        if (status.is_stopping) {
            runningStatus = 'Stopping...';
            statusClass = 'stopping';
        } else if (status.is_running) {
            if (status.is_paused) {
                // Check for specific pause mode in status_text
                if (status.status_text === 'pausing_image') {
                    runningStatus = 'Pausing after current image...';
                    statusClass = 'pausing';
                } else if (status.status_text === 'pausing_task') {
                    runningStatus = 'Pausing after current task...';
                    statusClass = 'pausing';
                } else {
                    runningStatus = 'Paused';
                    statusClass = 'paused';
                }
            } else if (stats.pending === 0 && stats.running === 0 && stats.paused === 0) {
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
                ${stats.paused ? `<span class='stat paused'>⏸️ ${stats.paused} paused</span>` : ''}
                <span class='stat completed'>✅ ${stats.completed || 0} completed</span>
                ${stats.stopped ? `<span class='stat stopped'>⏹️ ${stats.stopped} stopped</span>` : ''}
                <span class='stat failed'>❌ ${stats.failed || 0} failed</span>
            </div>
        </div>
        `;
    }

    // Update button enabled/disabled states via JavaScript
    function updateButtonStates(states) {
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
            if (!container) continue;

            // Find the actual button element inside Gradio's wrapper
            const btn = container.querySelector('button') || container;

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

            // Update isAnyTaskRunning based on queue stats
            const stats = statusData.queue_stats || {};
            isAnyTaskRunning = (stats.running || 0) > 0;

            // Update DOM if changed OR if forced (e.g., selection mode changed)
            if (tasksChanged || force) {
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
            showConfirmModal({
                icon: '🗑️',
                title: 'Delete Task',
                message: 'Are you sure you want to delete this task?',
                confirmText: 'Delete',
                confirmClass: 'ts-confirm-btn-delete',
                onConfirm: () => {
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
            });
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
        } else if (action === 'run') {
            fetch(`/task-scheduler/queue/${taskId}/run`, { method: 'POST' })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    showNotification('Task started', 'success');
                    refreshTaskList(true);
                } else {
                    showNotification('Failed to run task: ' + (data.error || 'Unknown error'), 'error');
                }
            })
            .catch(error => {
                console.error('[TaskScheduler] Error running task:', error);
                showNotification('Error running task', 'error');
            });
        }
    };

    // Selection mode functions
    window.taskSchedulerEnterSelectionMode = function(listType) {
        selectionMode[listType] = true;
        selectedTasks[listType].clear();
        refreshTaskList(true);
    };

    window.taskSchedulerExitSelectionMode = function(listType) {
        selectionMode[listType] = false;
        selectedTasks[listType].clear();
        refreshTaskList(true);
    };

    window.taskSchedulerToggleSelect = function(listType, taskId, isSelected) {
        if (isSelected) {
            selectedTasks[listType].add(taskId);
        } else {
            selectedTasks[listType].delete(taskId);
        }

        // Update just the task item's selected state (no full re-render)
        const taskItem = document.querySelector(`.task-item[data-task-id="${taskId}"]`);
        if (taskItem) {
            taskItem.classList.toggle('selected', isSelected);
        }

        // Update just the button counts in the section header
        const selectedCount = selectedTasks[listType].size;
        const section = listType === 'active' ? '.task-section-active' : '.task-section-history';
        const sectionEl = document.querySelector(section);
        if (sectionEl) {
            // Update Start/Delete buttons for active, Requeue/Delete for history
            const buttons = sectionEl.querySelectorAll('.section-btn');
            buttons.forEach(btn => {
                const text = btn.textContent;
                if (text.includes('Start') || text.includes('Delete') || text.includes('Requeue')) {
                    // Update the count in parentheses
                    btn.innerHTML = btn.innerHTML.replace(/\(\d+\)/, `(${selectedCount})`);
                }
            });
        }
    };

    window.taskSchedulerSelectAll = function(listType) {
        // Get all task IDs from the current list
        const listEl = document.querySelector(listType === 'active' ? '.task-section-active .task-list' : '.task-list-history');
        if (listEl) {
            const taskItems = listEl.querySelectorAll('.task-item');
            taskItems.forEach(item => {
                const taskId = item.dataset.taskId;
                if (taskId) {
                    selectedTasks[listType].add(taskId);
                    item.classList.add('selected');
                    // Check the checkbox
                    const checkbox = item.querySelector('input[type="checkbox"]');
                    if (checkbox) checkbox.checked = true;
                }
            });

            // Update button counts
            const selectedCount = selectedTasks[listType].size;
            const section = listType === 'active' ? '.task-section-active' : '.task-section-history';
            const sectionEl = document.querySelector(section);
            if (sectionEl) {
                const buttons = sectionEl.querySelectorAll('.section-btn');
                buttons.forEach(btn => {
                    const text = btn.textContent;
                    if (text.includes('Start') || text.includes('Delete') || text.includes('Requeue')) {
                        btn.innerHTML = btn.innerHTML.replace(/\(\d+\)/, `(${selectedCount})`);
                    }
                });
            }
        }
    };

    // Helper function to execute batch action
    async function executeBatchAction(listType, action, taskIds) {
        let successCount = 0;
        let errorCount = 0;

        // Process each task
        for (const taskId of taskIds) {
            try {
                let response;
                if (action === 'delete') {
                    response = await fetch(`/task-scheduler/queue/${taskId}`, { method: 'DELETE' });
                } else if (action === 'requeue') {
                    response = await fetch(`/task-scheduler/queue/${taskId}/retry`, { method: 'POST' });
                } else if (action === 'start') {
                    response = await fetch(`/task-scheduler/queue/${taskId}/run`, { method: 'POST' });
                    // Only one task can be started at a time, so break after first success
                    const data = await response.json();
                    if (data.success) {
                        successCount++;
                        showNotification('Task started', 'success');
                        break;
                    } else {
                        errorCount++;
                    }
                    continue;
                }

                const data = await response.json();
                if (data.success) {
                    successCount++;
                } else {
                    errorCount++;
                }
            } catch (error) {
                console.error(`[TaskScheduler] Error processing task ${taskId}:`, error);
                errorCount++;
            }
        }

        // Show result notification
        if (action !== 'start') {
            if (errorCount === 0) {
                showNotification(`${successCount} task(s) ${action === 'delete' ? 'deleted' : 'requeued'}`, 'success');
            } else if (successCount > 0) {
                showNotification(`${successCount} succeeded, ${errorCount} failed`, 'warning');
            } else {
                showNotification(`Failed to ${action} tasks`, 'error');
            }
        }

        // Exit selection mode and refresh
        selectionMode[listType] = false;
        selectedTasks[listType].clear();
        refreshTaskList(true);
    }

    window.taskSchedulerBatchAction = function(listType, action) {
        const taskIds = Array.from(selectedTasks[listType]);

        if (taskIds.length === 0) {
            showNotification('No tasks selected', 'warning');
            return;
        }

        // Confirm for delete action with styled modal
        if (action === 'delete') {
            showConfirmModal({
                icon: '🗑️',
                title: 'Delete Tasks',
                message: `Are you sure you want to delete <strong>${taskIds.length}</strong> selected task(s)?`,
                confirmText: 'Delete All',
                confirmClass: 'ts-confirm-btn-delete',
                onConfirm: () => {
                    executeBatchAction(listType, action, taskIds);
                }
            });
            return;
        }

        // For other actions, execute directly
        executeBatchAction(listType, action, taskIds);
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
                // VAE priority: forge_additional_modules > override_settings > ui_settings
                let vae = '';
                const forgeModules = params.ui_settings && params.ui_settings.forge_additional_modules;
                if (forgeModules && forgeModules.length > 0) {
                    // Extract filename from full path
                    const modulePath = forgeModules[0];
                    vae = modulePath.split(/[/\\]/).pop() || '';
                }
                if (!vae) {
                    vae = (params.override_settings && params.override_settings.sd_vae) ||
                          (params.ui_settings && params.ui_settings.sd_vae) || '';
                }
                await setCheckpointAndVAE(task.checkpoint, vae);

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
    async function setCheckpointAndVAE(checkpoint, vae) {
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
            if (vae && vae !== 'Automatic' && vae !== 'None') {
                if (typeof selectVAE === 'function') {
                    selectVAE(vae);
                    needsChange = true;
                    console.log('[TaskScheduler] Called selectVAE:', vae);
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

    // =====================================================
    // Large Batch Warning Interceptor
    // =====================================================

    // Fetch large batch warning setting
    async function fetchSettings() {
        try {
            const response = await fetch('/task-scheduler/settings');
            const data = await response.json();
            if (data.success && data.settings) {
                largeBatchWarningThreshold = data.settings.large_batch_warning || 0;
                bookmarkPromptName = data.settings.bookmark_prompt_name || false;
            }
        } catch (error) {
            console.error('[TaskScheduler] Error fetching settings:', error);
        }
    }

    // Alias for backwards compatibility
    const fetchLargeBatchSetting = fetchSettings;

    // Get total images from UI (batch_count * batch_size)
    function getTotalImages(isImg2Img) {
        const prefix = isImg2Img ? 'img2img' : 'txt2img';

        // Find batch_count and batch_size inputs
        const batchCountEl = document.querySelector(`#${prefix}_batch_count input[type="number"]`);
        const batchSizeEl = document.querySelector(`#${prefix}_batch_size input[type="number"]`);

        const batchCount = batchCountEl ? parseInt(batchCountEl.value) || 1 : 1;
        const batchSize = batchSizeEl ? parseInt(batchSizeEl.value) || 1 : 1;

        return batchCount * batchSize;
    }

    // Show large batch confirmation modal
    function showLargeBatchModal(totalImages, isImg2Img, onGenerate, onQueue, onCancel) {
        // Remove existing modal if any
        const existing = document.querySelector('.ts-batch-modal-overlay');
        if (existing) existing.remove();

        const modalHtml = `
            <div class="ts-batch-modal-overlay">
                <div class="ts-batch-modal">
                    <div class="ts-batch-modal-header">
                        <span class="ts-batch-modal-icon">⚠️</span>
                        <h3>Large Batch Warning</h3>
                    </div>
                    <div class="ts-batch-modal-body">
                        <p>You are about to generate <strong>${totalImages} images</strong>.</p>
                        <p>This may take a while. What would you like to do?</p>
                    </div>
                    <div class="ts-batch-modal-actions">
                        <button class="ts-batch-btn ts-batch-btn-generate">Generate Now</button>
                        <button class="ts-batch-btn ts-batch-btn-queue">Queue Instead</button>
                        <button class="ts-batch-btn ts-batch-btn-cancel">Cancel</button>
                    </div>
                </div>
            </div>
        `;

        document.body.insertAdjacentHTML('beforeend', modalHtml);

        const overlay = document.querySelector('.ts-batch-modal-overlay');
        const generateBtn = overlay.querySelector('.ts-batch-btn-generate');
        const queueBtn = overlay.querySelector('.ts-batch-btn-queue');
        const cancelBtn = overlay.querySelector('.ts-batch-btn-cancel');

        const closeModal = () => overlay.remove();

        generateBtn.addEventListener('click', () => {
            closeModal();
            onGenerate();
        });

        queueBtn.addEventListener('click', () => {
            closeModal();
            onQueue();
        });

        cancelBtn.addEventListener('click', () => {
            closeModal();
            onCancel();
        });

        // Close on overlay click
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) {
                closeModal();
                onCancel();
            }
        });

        // Close on Escape
        const escHandler = (e) => {
            if (e.key === 'Escape') {
                closeModal();
                onCancel();
                document.removeEventListener('keydown', escHandler);
            }
        };
        document.addEventListener('keydown', escHandler);
    }

    // Show generic confirmation modal
    function showConfirmModal(options) {
        const {
            icon = '⚠️',
            title = 'Confirm',
            message = 'Are you sure?',
            confirmText = 'Confirm',
            confirmClass = 'ts-confirm-btn-confirm',
            cancelText = 'Cancel',
            onConfirm = () => {},
            onCancel = () => {}
        } = options;

        // Remove existing modal if any
        const existing = document.querySelector('.ts-confirm-modal-overlay');
        if (existing) existing.remove();

        const modalHtml = `
            <div class="ts-confirm-modal-overlay">
                <div class="ts-confirm-modal">
                    <div class="ts-confirm-modal-header">
                        <span class="ts-confirm-modal-icon">${icon}</span>
                        <h3>${title}</h3>
                    </div>
                    <div class="ts-confirm-modal-body">
                        <p>${message}</p>
                    </div>
                    <div class="ts-confirm-modal-actions">
                        <button class="ts-confirm-btn ${confirmClass}">${confirmText}</button>
                        <button class="ts-confirm-btn ts-confirm-btn-cancel">${cancelText}</button>
                    </div>
                </div>
            </div>
        `;

        document.body.insertAdjacentHTML('beforeend', modalHtml);

        const overlay = document.querySelector('.ts-confirm-modal-overlay');
        const confirmBtn = overlay.querySelector(`.${confirmClass}`);
        const cancelBtn = overlay.querySelector('.ts-confirm-btn-cancel');

        const closeModal = () => overlay.remove();

        confirmBtn.addEventListener('click', () => {
            closeModal();
            onConfirm();
        });

        cancelBtn.addEventListener('click', () => {
            closeModal();
            onCancel();
        });

        // Close on overlay click
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) {
                closeModal();
                onCancel();
            }
        });

        // Close on Escape
        const escHandler = (e) => {
            if (e.key === 'Escape') {
                closeModal();
                onCancel();
                document.removeEventListener('keydown', escHandler);
            }
        };
        document.addEventListener('keydown', escHandler);

        // Focus confirm button
        confirmBtn.focus();
    }

    // Setup Generate button interceptors
    function setupGenerateInterceptors() {
        const buttons = [
            { id: 'txt2img_generate', isImg2Img: false },
            { id: 'img2img_generate', isImg2Img: true }
        ];

        buttons.forEach(({ id, isImg2Img }) => {
            const button = document.getElementById(id);
            if (!button || button.dataset.tsBatchIntercepted) return;

            button.dataset.tsBatchIntercepted = 'true';

            button.addEventListener('click', (e) => {
                // Skip if bypassing
                if (bypassLargeBatchWarning) {
                    bypassLargeBatchWarning = false;
                    return;
                }

                // Skip if feature disabled
                if (largeBatchWarningThreshold <= 0) return;

                // Check total images
                const totalImages = getTotalImages(isImg2Img);
                if (totalImages <= largeBatchWarningThreshold) return;

                // Prevent default - we'll handle this
                e.preventDefault();
                e.stopPropagation();
                e.stopImmediatePropagation();

                // Show modal
                showLargeBatchModal(
                    totalImages,
                    isImg2Img,
                    // On Generate
                    () => {
                        bypassLargeBatchWarning = true;
                        button.click();
                    },
                    // On Queue - use existing intercept mechanism
                    async () => {
                        try {
                            const tab = isImg2Img ? 'img2img' : 'txt2img';
                            const response = await fetch(`/task-scheduler/intercept/${tab}`, {
                                method: 'POST'
                            });
                            const data = await response.json();
                            if (data.success) {
                                bypassLargeBatchWarning = true;
                                button.click();
                            } else {
                                showNotification('Failed to queue: ' + (data.error || 'Unknown error'), 'error');
                            }
                        } catch (error) {
                            console.error('[TaskScheduler] Error setting intercept:', error);
                            showNotification('Failed to queue task', 'error');
                        }
                    },
                    // On Cancel - do nothing
                    () => {}
                );
            }, true); // Capture phase

            console.log(`[TaskScheduler] Batch warning interceptor attached to ${id}`);
        });

        // Retry if buttons not found
        const allFound = buttons.every(({ id }) => document.getElementById(id)?.dataset.tsBatchIntercepted);
        if (!allFound) {
            setTimeout(setupGenerateInterceptors, 1000);
        }
    }

    // Setup context menu for Queue buttons
    function setupQueueContextMenu() {
        const queueButtons = [
            { id: 'txt2img_queue', tab: 'txt2img' },
            { id: 'img2img_queue', tab: 'img2img' }
        ];

        queueButtons.forEach(({ id, tab }) => {
            const button = document.getElementById(id);
            if (!button || button.dataset.tsContextMenu) return;

            button.dataset.tsContextMenu = 'true';

            button.addEventListener('contextmenu', (e) => {
                e.preventDefault();

                // Remove any existing context menu
                const existing = document.querySelector('.ts-context-menu');
                if (existing) existing.remove();

                // Create context menu
                const menu = document.createElement('div');
                menu.className = 'ts-context-menu';
                menu.innerHTML = `
                    <div class='ts-context-menu-item' data-action='bookmark'>
                        <span class='ts-context-menu-icon'>⭐</span>
                        <span>Save as Bookmark</span>
                    </div>
                `;

                // Position menu at click location
                menu.style.left = e.pageX + 'px';
                menu.style.top = e.pageY + 'px';
                document.body.appendChild(menu);

                // Handle menu item click
                menu.querySelector('[data-action="bookmark"]').addEventListener('click', async () => {
                    menu.remove();

                    // Check if name prompt is enabled
                    if (bookmarkPromptName) {
                        showBookmarkNameModal(tab);
                    } else {
                        // Create bookmark directly without name
                        await createBookmark(tab, '');
                    }
                });

                // Close menu on click outside
                const closeMenu = (evt) => {
                    if (!menu.contains(evt.target)) {
                        menu.remove();
                        document.removeEventListener('click', closeMenu);
                    }
                };
                setTimeout(() => document.addEventListener('click', closeMenu), 0);
            });
        });

        // Retry if buttons not found
        const allFound = queueButtons.every(({ id }) => document.getElementById(id)?.dataset.tsContextMenu);
        if (!allFound) {
            setTimeout(setupQueueContextMenu, 1000);
        }
    }

    // Show modal to enter bookmark name
    function showBookmarkNameModal(tab) {
        // Remove existing modal if any
        const existing = document.querySelector('.ts-bookmark-name-modal');
        if (existing) existing.remove();

        const modal = document.createElement('div');
        modal.className = 'ts-bookmark-name-modal ts-confirm-modal-overlay';
        modal.innerHTML = `
            <div class='ts-confirm-modal'>
                <div class='ts-confirm-modal-header'>
                    <span class='ts-confirm-modal-icon'>⭐</span>
                    <h3>Save Bookmark</h3>
                </div>
                <div class='ts-confirm-modal-body'>
                    <p>Enter a name for this bookmark:</p>
                    <input type='text' class='ts-bookmark-name-input' placeholder='My Bookmark' autofocus>
                    <p style='margin-top: 12px; font-size: 0.9em; color: var(--body-text-color-subdued);'>
                        This will capture current ${tab} settings and save them as a bookmark.
                    </p>
                </div>
                <div class='ts-confirm-modal-actions'>
                    <button class='ts-confirm-btn ts-confirm-btn-confirm ts-bookmark-save'>Save</button>
                    <button class='ts-confirm-btn ts-confirm-btn-cancel ts-bookmark-cancel'>Cancel</button>
                </div>
            </div>
        `;

        document.body.appendChild(modal);

        const input = modal.querySelector('.ts-bookmark-name-input');
        const saveBtn = modal.querySelector('.ts-bookmark-save');
        const cancelBtn = modal.querySelector('.ts-bookmark-cancel');

        input.focus();

        const closeModal = () => modal.remove();

        saveBtn.addEventListener('click', async () => {
            const name = input.value.trim() || 'Untitled';
            closeModal();
            await createBookmark(tab, name);
        });

        cancelBtn.addEventListener('click', closeModal);

        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                saveBtn.click();
            } else if (e.key === 'Escape') {
                closeModal();
            }
        });

        modal.addEventListener('click', (e) => {
            if (e.target === modal) closeModal();
        });
    }

    // Create a bookmark by triggering intercept and saving
    async function createBookmark(tab, name) {
        try {
            showNotification('Capturing settings...', 'info');

            // Set intercept mode
            const interceptResponse = await fetch(`/task-scheduler/intercept/${tab}`, {
                method: 'POST'
            });
            const interceptData = await interceptResponse.json();

            if (!interceptData.success) {
                showNotification('Failed to start capture: ' + (interceptData.error || 'Unknown error'), 'error');
                return;
            }

            // Click the Generate button to trigger capture
            const generateBtnId = tab === 'img2img' ? 'img2img_generate' : 'txt2img_generate';
            const generateBtn = document.getElementById(generateBtnId);

            if (!generateBtn) {
                showNotification('Generate button not found', 'error');
                return;
            }

            generateBtn.click();

            // Wait for intercept to capture
            await new Promise(resolve => setTimeout(resolve, 1500));

            // Create the bookmark from captured data
            const bookmarkResponse = await fetch(`/task-scheduler/bookmarks?name=${encodeURIComponent(name)}`, {
                method: 'POST'
            });
            const bookmarkData = await bookmarkResponse.json();

            if (bookmarkData.success) {
                showNotification(`Bookmark "${name}" saved!`, 'success');
                await fetchBookmarks();
                // Switch to bookmarks tab
                window.switchTaskTab('bookmarks');
            } else {
                showNotification('Failed to save bookmark: ' + (bookmarkData.error || 'Unknown error'), 'error');
            }

        } catch (error) {
            console.error('[TaskScheduler] Error creating bookmark:', error);
            showNotification('Error creating bookmark', 'error');
        }
    }

    // Initialize
    function init() {
        console.log('[TaskScheduler] Initializing JavaScript (Queue buttons created via Gradio)...');

        // Fetch settings and setup interceptors
        fetchLargeBatchSetting().then(() => {
            setupGenerateInterceptors();
        });

        // Start auto-refresh for task list
        startAutoRefresh();

        // Setup context menu for Queue buttons
        setupQueueContextMenu();

        // Fetch initial bookmarks
        fetchBookmarks();

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
            /* Task List Tabs */
            .ts-tabs {
                display: flex !important;
                gap: 12px !important;
                padding: 8px 12px 0 12px !important;
                background: var(--block-background-fill, #1f2937) !important;
                border-radius: 8px 8px 0 0 !important;
                border-bottom: 1px solid var(--border-color-primary, #374151) !important;
            }
            .ts-tab {
                display: flex !important;
                align-items: center !important;
                gap: 8px !important;
                padding: 10px 20px !important;
                border: none !important;
                background: transparent !important;
                color: var(--body-text-color-subdued, #9ca3af) !important;
                cursor: pointer !important;
                border-radius: 6px 6px 0 0 !important;
                font-size: 0.95em !important;
                font-weight: 500 !important;
                transition: all 0.2s ease !important;
                position: relative !important;
            }
            .ts-tab:hover {
                background: rgba(255, 255, 255, 0.05);
                color: var(--body-text-color, #fff);
            }
            .ts-tab.active {
                background: var(--background-fill-primary, #111827);
                color: var(--body-text-color, #fff);
            }
            .ts-tab.active::after {
                content: '';
                position: absolute;
                bottom: -1px;
                left: 0;
                right: 0;
                height: 2px;
                background: #2196F3;
            }
            .ts-tab-icon {
                font-size: 1.1em;
            }
            .ts-tab-label {
                display: inline;
            }
            .ts-tab-count {
                background: rgba(255, 255, 255, 0.1);
                padding: 2px 8px;
                border-radius: 10px;
                font-size: 0.85em;
                min-width: 24px;
                text-align: center;
            }
            .ts-tab.active .ts-tab-count {
                background: rgba(33, 150, 243, 0.2);
                color: #2196F3;
            }
            .ts-tab-content {
                background: var(--background-fill-primary, #111827);
                border-radius: 0 0 8px 8px;
                min-height: 200px;
            }
            .ts-tab-panel {
                padding: 12px;
            }
            .ts-panel-header {
                display: flex;
                justify-content: flex-end;
                padding: 0 4px 8px 4px;
                border-bottom: 1px solid var(--border-color-primary, #374151);
                margin-bottom: 8px;
            }
            /* Coming soon placeholder */
            .ts-coming-soon {
                text-align: center;
                padding: 40px 20px;
            }
            .ts-coming-soon-icon {
                font-size: 3em;
                display: block;
                margin-bottom: 16px;
                opacity: 0.5;
            }
            .ts-coming-soon h3 {
                margin: 0 0 8px 0;
                color: var(--body-text-color, #fff);
            }
            .ts-coming-soon p {
                margin: 0;
                color: var(--body-text-color-subdued, #9ca3af);
            }
            /* Context Menu */
            .ts-context-menu {
                position: absolute;
                z-index: 10003;
                background: var(--block-background-fill, #1f2937) !important;
                border: 1px solid var(--border-color-primary, #374151) !important;
                border-radius: 8px !important;
                box-shadow: 0 10px 25px rgba(0, 0, 0, 0.5) !important;
                min-width: 180px !important;
                overflow: hidden !important;
            }
            .ts-context-menu-item {
                display: flex !important;
                align-items: center !important;
                gap: 10px !important;
                padding: 12px 16px !important;
                cursor: pointer !important;
                color: var(--body-text-color, #fff) !important;
                background: var(--block-background-fill, #1f2937) !important;
                transition: background 0.15s ease !important;
                border: none !important;
            }
            .ts-context-menu-item:hover {
                background: rgba(255, 193, 7, 0.2) !important;
            }
            .ts-context-menu-icon {
                font-size: 1.1em;
            }
            /* Bookmark Name Input */
            .ts-bookmark-name-input {
                width: 100%;
                padding: 10px 12px;
                border: 1px solid var(--border-color-primary, #374151);
                border-radius: 6px;
                background: var(--input-background-fill, #111827);
                color: var(--body-text-color, #fff);
                font-size: 1em;
                margin-top: 8px;
            }
            .ts-bookmark-name-input:focus {
                outline: none;
                border-color: #2196F3;
            }
            /* Bookmark Item Styling */
            .bookmark-item {
                border-left: 4px solid #ffc107 !important;
            }
            .bookmark-item .task-header {
                display: flex;
                align-items: center;
                gap: 8px;
                margin-bottom: 8px;
            }
            .bookmark-item .bookmark-icon {
                font-size: 1.1em;
            }
            .bookmark-item .bookmark-name {
                font-weight: 600;
                color: var(--body-text-color, #fff);
                flex: 1;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }
            .bookmark-item .task-type {
                font-size: 0.75em;
                padding: 2px 6px;
                background: rgba(255, 193, 7, 0.2);
                border-radius: 4px;
                color: #ffc107;
            }
            .bookmark-item .bookmark-details {
                display: grid;
                grid-template-columns: repeat(2, 1fr);
                gap: 6px 16px;
                font-size: 0.85em;
                color: var(--body-text-color-subdued, #9ca3af);
            }
            .bookmark-item .bookmark-detail {
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }
            .bookmark-item .bookmark-detail strong {
                color: var(--body-text-color, #fff);
                font-weight: 500;
            }
            @media (max-width: 600px) {
                .bookmark-item .bookmark-details {
                    grid-template-columns: 1fr;
                }
            }
            /* Responsive tabs */
            @media (max-width: 500px) {
                .ts-tab-label {
                    display: none;
                }
                .ts-tab {
                    padding: 10px 12px;
                }
            }
            /* Large Batch Warning Modal */
            .ts-batch-modal-overlay {
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background: rgba(0, 0, 0, 0.7);
                z-index: 10002;
                display: flex;
                align-items: center;
                justify-content: center;
                animation: fadeIn 0.2s ease;
            }
            @keyframes fadeIn {
                from { opacity: 0; }
                to { opacity: 1; }
            }
            .ts-batch-modal {
                background: var(--background-fill-primary, #1f2937);
                border-radius: 12px;
                padding: 24px;
                min-width: 320px;
                max-width: 90%;
                box-shadow: 0 20px 40px rgba(0, 0, 0, 0.5);
                animation: modalSlideIn 0.3s ease;
            }
            @keyframes modalSlideIn {
                from { transform: translateY(-20px); opacity: 0; }
                to { transform: translateY(0); opacity: 1; }
            }
            .ts-batch-modal-header {
                display: flex;
                align-items: center;
                gap: 12px;
                margin-bottom: 16px;
            }
            .ts-batch-modal-icon {
                font-size: 2em;
            }
            .ts-batch-modal-header h3 {
                margin: 0;
                font-size: 1.3em;
                color: var(--body-text-color, #fff);
            }
            .ts-batch-modal-body {
                margin-bottom: 20px;
                color: var(--body-text-color, #e5e7eb);
            }
            .ts-batch-modal-body p {
                margin: 8px 0;
            }
            .ts-batch-modal-body strong {
                color: #f59e0b;
            }
            .ts-batch-modal-actions {
                display: flex;
                gap: 10px;
                justify-content: flex-end;
                flex-wrap: wrap;
            }
            .ts-batch-btn {
                padding: 10px 18px;
                border-radius: 6px;
                border: 1px solid transparent;
                cursor: pointer;
                font-size: 0.95em;
                font-weight: 500;
                transition: all 0.2s ease;
            }
            .ts-batch-btn-generate {
                background: rgba(76, 175, 80, 0.2);
                border-color: rgba(76, 175, 80, 0.5);
                color: #4CAF50;
            }
            .ts-batch-btn-generate:hover {
                background: rgba(76, 175, 80, 0.35);
            }
            .ts-batch-btn-queue {
                background: rgba(33, 150, 243, 0.2);
                border-color: rgba(33, 150, 243, 0.5);
                color: #2196F3;
            }
            .ts-batch-btn-queue:hover {
                background: rgba(33, 150, 243, 0.35);
            }
            .ts-batch-btn-cancel {
                background: rgba(158, 158, 158, 0.2);
                border-color: rgba(158, 158, 158, 0.5);
                color: #9E9E9E;
            }
            .ts-batch-btn-cancel:hover {
                background: rgba(158, 158, 158, 0.35);
            }
            /* Generic Confirmation Modal */
            .ts-confirm-modal-overlay {
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background: rgba(0, 0, 0, 0.7);
                z-index: 10002;
                display: flex;
                align-items: center;
                justify-content: center;
                animation: fadeIn 0.2s ease;
            }
            .ts-confirm-modal {
                background: var(--background-fill-primary, #1f2937);
                border-radius: 12px;
                padding: 24px;
                min-width: 320px;
                max-width: 90%;
                box-shadow: 0 20px 40px rgba(0, 0, 0, 0.5);
                animation: modalSlideIn 0.3s ease;
            }
            .ts-confirm-modal-header {
                display: flex;
                align-items: center;
                gap: 12px;
                margin-bottom: 16px;
            }
            .ts-confirm-modal-icon {
                font-size: 2em;
            }
            .ts-confirm-modal-header h3 {
                margin: 0;
                font-size: 1.3em;
                color: var(--body-text-color, #fff);
            }
            .ts-confirm-modal-body {
                margin-bottom: 20px;
                color: var(--body-text-color, #e5e7eb);
            }
            .ts-confirm-modal-body p {
                margin: 8px 0;
            }
            .ts-confirm-modal-body strong {
                color: #f59e0b;
            }
            .ts-confirm-modal-actions {
                display: flex;
                gap: 10px;
                justify-content: flex-end;
                flex-wrap: wrap;
            }
            .ts-confirm-btn {
                padding: 10px 18px;
                border-radius: 6px;
                border: 1px solid transparent;
                cursor: pointer;
                font-size: 0.95em;
                font-weight: 500;
                transition: all 0.2s ease;
            }
            .ts-confirm-btn:focus {
                outline: 2px solid rgba(33, 150, 243, 0.5);
                outline-offset: 2px;
            }
            .ts-confirm-btn-confirm {
                background: rgba(33, 150, 243, 0.2);
                border-color: rgba(33, 150, 243, 0.5);
                color: #2196F3;
            }
            .ts-confirm-btn-confirm:hover {
                background: rgba(33, 150, 243, 0.35);
            }
            .ts-confirm-btn-delete {
                background: rgba(244, 67, 54, 0.2);
                border-color: rgba(244, 67, 54, 0.5);
                color: #f44336;
            }
            .ts-confirm-btn-delete:hover {
                background: rgba(244, 67, 54, 0.35);
            }
            .ts-confirm-btn-cancel {
                background: rgba(158, 158, 158, 0.2);
                border-color: rgba(158, 158, 158, 0.5);
                color: #9E9E9E;
            }
            .ts-confirm-btn-cancel:hover {
                background: rgba(158, 158, 158, 0.35);
            }
            /* Gradio Queue buttons styling */
            #txt2img_queue, #img2img_queue {
                min-width: 80px !important;
                white-space: nowrap !important;
                font-weight: 500 !important;
                transition: all 0.2s ease !important;
            }
            /* Queue button processing state */
            #txt2img_queue.queue-processing,
            #img2img_queue.queue-processing {
                opacity: 0.7 !important;
                cursor: wait !important;
                position: relative !important;
            }
            #txt2img_queue.queue-processing::after,
            #img2img_queue.queue-processing::after {
                content: '' !important;
                position: absolute !important;
                top: 50% !important;
                right: 8px !important;
                width: 12px !important;
                height: 12px !important;
                margin-top: -6px !important;
                border: 2px solid transparent !important;
                border-top-color: currentColor !important;
                border-radius: 50% !important;
                animation: queueSpinner 0.8s linear infinite !important;
            }
            @keyframes queueSpinner {
                to { transform: rotate(360deg); }
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
            .status-badge-mini.status-stopped { background: rgba(255, 87, 34, 0.2); color: #FF5722; }
            .status-badge-mini.status-paused { background: rgba(156, 39, 176, 0.2); color: #9C27B0; }
            /* Queue status indicator colors */
            .queue-status .status-indicator.stopping { background: #FF5722; animation: pulse 0.5s infinite; }
            .queue-status .status-indicator.pausing { background: #9C27B0; animation: pulse 0.5s infinite; }
            .queue-status .status-indicator.paused { background: #9C27B0; }
            .queue-status.stopping { border-color: rgba(255, 87, 34, 0.5); }
            .queue-status.pausing { border-color: rgba(156, 39, 176, 0.5); }
            .queue-status.paused { border-color: rgba(156, 39, 176, 0.5); }
            @keyframes pulse {
                0%, 100% { opacity: 1; }
                50% { opacity: 0.5; }
            }
            /* Task item status colors */
            .task-item.status-stopped { border-left-color: #FF5722; }
            .task-item.status-paused { border-left-color: #9C27B0; }
            .stat.stopped { color: #FF5722; }
            .stat.paused { color: #9C27B0; }
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
            /* Active Tasks collapsible */
            .task-active-details {
                background: var(--block-background-fill, #1f2937);
                border-radius: 8px;
                overflow: hidden;
            }
            .task-active-summary {
                cursor: pointer;
                user-select: none;
                margin: 0;
                background: linear-gradient(135deg, rgba(33, 150, 243, 0.15), rgba(76, 175, 80, 0.15));
                border-left: 3px solid #2196F3;
                display: flex !important;
                justify-content: space-between;
                align-items: center;
                list-style: none;
            }
            .task-active-summary::-webkit-details-marker {
                display: none;
            }
            .task-active-summary::marker {
                display: none;
                content: "";
            }
            .task-active-summary:hover {
                background: linear-gradient(135deg, rgba(33, 150, 243, 0.25), rgba(76, 175, 80, 0.25));
            }
            .active-title {
                flex: 1;
            }
            .active-title::before {
                content: "▶ ";
                font-size: 0.8em;
                margin-right: 4px;
            }
            .task-active-details[open] .active-title::before {
                content: "▼ ";
            }
            .active-actions {
                display: flex;
                align-items: center;
            }
            /* History collapsible */
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
                display: flex !important;
                justify-content: space-between;
                align-items: center;
                list-style: none;
            }
            .task-history-summary::-webkit-details-marker {
                display: none;
            }
            .task-history-summary::marker {
                display: none;
                content: "";
            }
            .task-history-summary:hover {
                background: rgba(158, 158, 158, 0.2);
            }
            .history-title {
                flex: 1;
            }
            .history-title::before {
                content: "▶ ";
                font-size: 0.8em;
                margin-right: 4px;
            }
            .task-history-details[open] .history-title::before {
                content: "▼ ";
            }
            .history-actions {
                display: flex;
                align-items: center;
            }
            .task-list-history {
                padding-top: 8px;
            }
            .task-list-history .task-item {
                opacity: 0.8;
            }
            /* Selection mode styles */
            .task-section-header-row {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 8px 12px;
                background: var(--block-background-fill, #1f2937);
                border-radius: 6px;
                margin-bottom: 8px;
            }
            .task-section-header-row .task-section-header {
                margin: 0;
                padding: 0;
                background: none;
                border-radius: 0;
            }
            .task-section-active .task-section-header-row {
                background: linear-gradient(135deg, rgba(33, 150, 243, 0.15), rgba(76, 175, 80, 0.15));
                border-left: 3px solid #2196F3;
            }
            .section-actions {
                display: flex;
                gap: 8px;
                align-items: center;
            }
            .section-btn {
                padding: 4px 10px;
                border: 1px solid var(--border-color-primary, #374151);
                border-radius: 4px;
                background: var(--button-secondary-background-fill, #374151);
                color: var(--body-text-color, #fff);
                cursor: pointer;
                font-size: 0.85em;
                display: flex;
                align-items: center;
                gap: 4px;
                transition: all 0.2s ease;
            }
            .section-btn:hover {
                background: var(--button-secondary-background-fill-hover, #4b5563);
            }
            .section-btn-select {
                background: rgba(33, 150, 243, 0.2);
                border-color: rgba(33, 150, 243, 0.5);
            }
            .section-btn-select:hover {
                background: rgba(33, 150, 243, 0.3);
            }
            .section-btn-cancel {
                background: rgba(158, 158, 158, 0.2);
                border-color: rgba(158, 158, 158, 0.5);
            }
            .section-btn-select-all {
                background: rgba(156, 39, 176, 0.2);
                border-color: rgba(156, 39, 176, 0.5);
            }
            .section-btn-start {
                background: rgba(76, 175, 80, 0.2);
                border-color: rgba(76, 175, 80, 0.5);
            }
            .section-btn-start:hover {
                background: rgba(76, 175, 80, 0.3);
            }
            .section-btn-requeue {
                background: rgba(255, 152, 0, 0.2);
                border-color: rgba(255, 152, 0, 0.5);
            }
            .section-btn-requeue:hover {
                background: rgba(255, 152, 0, 0.3);
            }
            .section-btn-delete {
                background: rgba(244, 67, 54, 0.2);
                border-color: rgba(244, 67, 54, 0.5);
            }
            .section-btn-delete:hover {
                background: rgba(244, 67, 54, 0.3);
            }
            /* Task checkbox */
            .task-checkbox {
                display: flex;
                align-items: center;
                justify-content: center;
                margin-right: 8px;
            }
            .task-checkbox input[type="checkbox"] {
                width: 18px;
                height: 18px;
                cursor: pointer;
                accent-color: #2196F3;
            }
            .task-item.selected {
                background: rgba(33, 150, 243, 0.15) !important;
                border-color: rgba(33, 150, 243, 0.5) !important;
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
            /* Run button styles */
            .task-btn-run {
                background: rgba(76, 175, 80, 0.15) !important;
                border-color: rgba(76, 175, 80, 0.5) !important;
                color: #4CAF50 !important;
            }
            .task-btn-run:hover {
                background: rgba(76, 175, 80, 0.3) !important;
            }
            .task-btn-disabled {
                opacity: 0.5 !important;
                cursor: not-allowed !important;
                pointer-events: none !important;
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
            /* Requeued badge for history tasks */
            .requeued-badge {
                display: inline-block;
                padding: 2px 6px;
                margin-left: 6px;
                font-size: 0.75em;
                font-weight: 500;
                background: rgba(156, 39, 176, 0.2);
                color: #9C27B0;
                border-radius: 4px;
                border: 1px solid rgba(156, 39, 176, 0.4);
            }
            /* Task item header row - responsive with wrapping */
            .task-header {
                display: flex;
                align-items: center;
                gap: 8px 12px;
                margin-bottom: 4px;
                flex-wrap: wrap;
            }
            .task-type {
                font-weight: 600;
                color: #60a5fa;
            }
            .task-size {
                font-family: monospace;
                color: #10b981;
                background: rgba(16, 185, 129, 0.1);
                padding: 2px 6px;
                border-radius: 4px;
            }
            .task-images {
                color: #f59e0b;
                background: rgba(245, 158, 11, 0.1);
                padding: 2px 6px;
                border-radius: 4px;
            }
            .task-checkpoint {
                color: #e5e7eb;
                background: rgba(229, 231, 235, 0.1);
                padding: 2px 6px;
                border-radius: 4px;
                max-width: 200px;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }
            .task-vae {
                color: #f472b6;
                background: rgba(244, 114, 182, 0.1);
                padding: 2px 6px;
                border-radius: 4px;
                max-width: 150px;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }
            /* Task meta row - responsive with wrapping */
            .task-meta {
                display: flex;
                gap: 8px 12px;
                flex-wrap: wrap;
                color: var(--body-text-color-subdued, #9ca3af);
            }
            .task-model {
                max-width: 300px;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }
            .task-sampler {
                color: #a78bfa;
            }
            .task-date {
                color: #9ca3af;
            }
            /* Task item base - adjust height for wrapped content */
            .task-item {
                min-height: auto;
            }
        `;
        document.head.appendChild(style);
    }

    onReady(init);
})();
