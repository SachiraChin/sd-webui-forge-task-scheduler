/**
 * Task Scheduler JavaScript for injecting Queue buttons
 * and handling task queue UI interactions.
 */

(function() {
    'use strict';

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
        // Copy the exact classes from the Generate button for consistent styling
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

    // Queue a task by triggering the appropriate Gradio function
    function queueTask(tabName) {
        // Show feedback immediately
        const queueBtn = document.getElementById(`${tabName}_queue`);
        const originalText = queueBtn ? queueBtn.textContent : 'Queue';
        if (queueBtn) {
            queueBtn.textContent = 'Queuing...';
            queueBtn.disabled = true;
        }

        // Collect all form inputs for the tab
        const params = collectParams(tabName);

        // Send to backend via fetch API
        fetch('/task-scheduler/queue/' + tabName, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(params)
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showNotification('Task queued successfully!', 'success');
                // Try to refresh task list if on queue tab
                triggerRefresh();
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

    // Collect all parameters from the UI
    function collectParams(tabName) {
        const params = { extra_params: {} };

        // Get prompt
        const promptEl = document.querySelector(`#${tabName}_prompt textarea`);
        if (promptEl) params.prompt = promptEl.value || '';

        // Get negative prompt
        const negPromptEl = document.querySelector(`#${tabName}_neg_prompt textarea`);
        if (negPromptEl) params.negative_prompt = negPromptEl.value || '';

        // Get steps - try multiple selectors
        let stepsEl = document.querySelector(`#${tabName}_steps input[type="number"]`);
        if (!stepsEl) stepsEl = document.querySelector(`#${tabName}_steps input`);
        if (stepsEl) params.steps = parseInt(stepsEl.value) || 20;

        // Get CFG scale
        let cfgEl = document.querySelector(`#${tabName}_cfg_scale input[type="number"]`);
        if (!cfgEl) cfgEl = document.querySelector(`#${tabName}_cfg_scale input`);
        if (cfgEl) params.cfg_scale = parseFloat(cfgEl.value) || 7.0;

        // Get dimensions
        let widthEl = document.querySelector(`#${tabName}_width input[type="number"]`);
        if (!widthEl) widthEl = document.querySelector(`#${tabName}_width input`);
        if (widthEl) params.width = parseInt(widthEl.value) || 512;

        let heightEl = document.querySelector(`#${tabName}_height input[type="number"]`);
        if (!heightEl) heightEl = document.querySelector(`#${tabName}_height input`);
        if (heightEl) params.height = parseInt(heightEl.value) || 512;

        // Get batch size
        let batchSizeEl = document.querySelector(`#${tabName}_batch_size input[type="number"]`);
        if (!batchSizeEl) batchSizeEl = document.querySelector(`#${tabName}_batch_size input`);
        if (batchSizeEl) params.batch_size = parseInt(batchSizeEl.value) || 1;

        // Get batch count (n_iter)
        let batchCountEl = document.querySelector(`#${tabName}_batch_count input[type="number"]`);
        if (!batchCountEl) batchCountEl = document.querySelector(`#${tabName}_batch_count input`);
        if (batchCountEl) params.n_iter = parseInt(batchCountEl.value) || 1;

        // Get seed
        let seedEl = document.querySelector(`#${tabName}_seed input[type="number"]`);
        if (!seedEl) seedEl = document.querySelector(`#${tabName}_seed input`);
        if (seedEl) params.seed = parseInt(seedEl.value) || -1;

        // Get sampler - look for dropdown
        const samplerEl = document.querySelector(`#${tabName}_sampling select, #${tabName}_sampler select`);
        if (samplerEl) params.sampler_name = samplerEl.value || 'Euler';

        // Get scheduler
        const schedulerEl = document.querySelector(`#${tabName}_scheduler select`);
        if (schedulerEl) params.scheduler = schedulerEl.value || 'automatic';

        // For img2img, get denoising strength
        if (tabName === 'img2img') {
            let denoisingEl = document.querySelector(`#${tabName}_denoising_strength input`);
            if (denoisingEl) params.extra_params.denoising_strength = parseFloat(denoisingEl.value) || 0.75;
        }

        return params;
    }

    // Show notification toast
    function showNotification(message, type) {
        // Remove any existing notifications
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

    // Trigger refresh of the task list
    function triggerRefresh() {
        // Find refresh button - try multiple selectors since Gradio structures tabs differently
        const selectors = [
            '#task_queue_tab button',
            '[id*="task_queue"] button',
            '.tabitem button'
        ];

        for (const selector of selectors) {
            const buttons = document.querySelectorAll(selector);
            for (const btn of buttons) {
                if (btn.textContent.includes('Refresh') || btn.textContent.includes('🔄')) {
                    console.log('[TaskScheduler] Clicking refresh button');
                    btn.click();
                    return;
                }
            }
        }
        console.log('[TaskScheduler] Refresh button not found');
    }

    // Handle task actions (delete, etc.) via API
    window.taskSchedulerAction = function(action, taskId) {
        if (action === 'delete') {
            if (confirm('Delete this task?')) {
                fetch(`/task-scheduler/queue/${taskId}`, {
                    method: 'DELETE'
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        showNotification('Task deleted', 'success');
                        triggerRefresh();
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
            fetch(`/task-scheduler/queue/${taskId}/retry`, {
                method: 'POST'
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    showNotification('Task requeued', 'success');
                    triggerRefresh();
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

    // Auto-refresh task list when queue tab is visible
    let refreshInterval = null;
    let lastTabWasQueue = false;

    function startAutoRefresh() {
        if (refreshInterval) return;

        // Set up tab change detection
        setupTabChangeDetection();

        refreshInterval = setInterval(() => {
            // Check if task queue tab is visible
            const isQueueTabVisible = isTaskQueueTabVisible();
            if (isQueueTabVisible) {
                triggerRefresh();
            }
        }, 5000); // Refresh every 5 seconds when visible
    }

    function isTaskQueueTabVisible() {
        // Method 1: Check if the selected tab button says "Task Queue"
        const tabButton = document.querySelector('button[role="tab"][aria-selected="true"]');
        if (tabButton && tabButton.textContent.includes('Task Queue')) {
            return true;
        }

        // Method 2: Check for the task queue status element visibility
        const queueStatus = document.getElementById('task_queue_status');
        if (queueStatus && queueStatus.offsetParent !== null && queueStatus.offsetHeight > 0) {
            return true;
        }

        // Method 3: Check for task_queue_tab element
        const taskQueueTab = document.getElementById('task_queue_tab');
        if (taskQueueTab && taskQueueTab.offsetParent !== null && taskQueueTab.offsetHeight > 0) {
            return true;
        }

        // Method 4: Check for the task list element
        const taskList = document.getElementById('task_queue_list');
        if (taskList && taskList.offsetParent !== null && taskList.offsetHeight > 0) {
            return true;
        }

        return false;
    }

    function setupTabChangeDetection() {
        // Monitor for tab changes using MutationObserver
        // Try multiple selectors since Gradio versions may differ
        const selectors = ['.tabs', '[role="tablist"]', '.tab-nav', '#tabs'];
        let tabsContainer = null;
        for (const sel of selectors) {
            tabsContainer = document.querySelector(sel);
            if (tabsContainer) break;
        }

        if (!tabsContainer) {
            // Retry later if tabs not found yet
            console.log('[TaskScheduler] Tab container not found, retrying...');
            setTimeout(setupTabChangeDetection, 1000);
            return;
        }

        console.log('[TaskScheduler] Tab container found, setting up detection');

        // Watch for aria-selected changes on tab buttons
        const observer = new MutationObserver((mutations) => {
            const isQueueTabNow = isTaskQueueTabVisible();
            if (isQueueTabNow && !lastTabWasQueue) {
                // Just switched to queue tab - refresh immediately
                console.log('[TaskScheduler] Switched to Task Queue tab, refreshing...');
                triggerRefresh();
            }
            lastTabWasQueue = isQueueTabNow;
        });

        observer.observe(tabsContainer, {
            attributes: true,
            subtree: true,
            attributeFilter: ['aria-selected', 'class']
        });

        // Also add click handlers to tab buttons as backup
        const addTabClickHandlers = () => {
            document.querySelectorAll('button[role="tab"], .tab-nav button').forEach(tab => {
                if (tab.dataset.taskSchedulerHandler) return; // Already handled
                tab.dataset.taskSchedulerHandler = 'true';
                tab.addEventListener('click', () => {
                    setTimeout(() => {
                        const isQueueTabNow = isTaskQueueTabVisible();
                        if (isQueueTabNow && !lastTabWasQueue) {
                            console.log('[TaskScheduler] Tab clicked, refreshing...');
                            triggerRefresh();
                        }
                        lastTabWasQueue = isQueueTabNow;
                    }, 200);
                });
            });
        };

        addTabClickHandlers();
        // Re-check for new tab buttons periodically (in case dynamically added)
        setInterval(addTabClickHandlers, 5000);
    }

    // Initialize when page loads
    function init() {
        console.log('[TaskScheduler] Initializing...');

        // Try to inject buttons (may need retry due to Gradio loading)
        let attempts = 0;
        const maxAttempts = 60; // 30 seconds total

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
                // Still start auto-refresh for the queue tab
                startAutoRefresh();
            }
        }

        tryInject();

        // Add CSS animations
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
        `;
        document.head.appendChild(style);
    }

    onReady(init);
})();
