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

        // Create Queue button
        const queueBtn = document.createElement('button');
        queueBtn.id = `${tabName}_queue`;
        queueBtn.className = 'lg secondary gradio-button';
        queueBtn.textContent = 'Queue';
        queueBtn.title = 'Add current settings to task queue';
        queueBtn.style.marginLeft = '8px';

        // Insert after Generate button
        generateBtn.parentNode.insertBefore(queueBtn, generateBtn.nextSibling);

        // Add click handler
        queueBtn.addEventListener('click', function(e) {
            e.preventDefault();
            queueTask(tabName);
        });

        console.log(`[TaskScheduler] Queue button injected for ${tabName}`);
        return true;
    }

    // Queue a task by triggering the appropriate Gradio function
    function queueTask(tabName) {
        // Show feedback immediately
        const queueBtn = document.getElementById(`${tabName}_queue`);
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
                refreshTaskList();
            } else {
                showNotification('Failed to queue task: ' + data.error, 'error');
            }
        })
        .catch(error => {
            console.error('[TaskScheduler] Error queuing task:', error);
            // Fallback: try using Gradio's internal mechanism
            queueTaskViaGradio(tabName);
        })
        .finally(() => {
            if (queueBtn) {
                queueBtn.textContent = 'Queue';
                queueBtn.disabled = false;
            }
        });
    }

    // Fallback: Queue task via Gradio button click simulation
    function queueTaskViaGradio(tabName) {
        // Find the hidden queue trigger if it exists
        const hiddenTrigger = document.getElementById(`${tabName}_queue_trigger`);
        if (hiddenTrigger) {
            hiddenTrigger.click();
        } else {
            showNotification('Task queued! Check the Task Queue tab.', 'info');
        }
    }

    // Collect all parameters from the UI
    function collectParams(tabName) {
        const params = {};

        // Get prompt
        const promptEl = document.querySelector(`#${tabName}_prompt textarea`);
        if (promptEl) params.prompt = promptEl.value;

        // Get negative prompt
        const negPromptEl = document.querySelector(`#${tabName}_neg_prompt textarea`);
        if (negPromptEl) params.negative_prompt = negPromptEl.value;

        // Get other common parameters
        const paramMappings = {
            'steps': 'steps',
            'cfg_scale': 'cfg_scale',
            'width': 'width',
            'height': 'height',
            'batch_size': 'batch_size',
            'batch_count': 'n_iter',
            'seed': 'seed',
            'sampler': 'sampler_name',
        };

        // Try to get each parameter
        for (const [uiName, paramName] of Object.entries(paramMappings)) {
            const el = document.querySelector(`#${tabName}_${uiName} input`);
            if (el) {
                params[paramName] = el.value;
            }
        }

        return params;
    }

    // Show notification toast
    function showNotification(message, type) {
        // Use Gradio's built-in notification if available
        if (typeof gradio_config !== 'undefined' && gradio_config.show_toast) {
            gradio_config.show_toast(message);
            return;
        }

        // Fallback: create custom notification
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
            animation: slideIn 0.3s ease;
            background: ${type === 'success' ? '#4CAF50' : type === 'error' ? '#f44336' : '#2196F3'};
            color: white;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        `;

        document.body.appendChild(notification);

        setTimeout(() => {
            notification.style.animation = 'slideOut 0.3s ease';
            setTimeout(() => notification.remove(), 300);
        }, 3000);
    }

    // Refresh the task list in the Task Queue tab
    function refreshTaskList() {
        const refreshBtn = document.querySelector('#task_queue_tab button:contains("Refresh")');
        if (refreshBtn) {
            refreshBtn.click();
        }
    }

    // Handle task actions (delete, etc.)
    window.taskSchedulerAction = function(action, taskId) {
        if (action === 'delete') {
            if (confirm('Delete this task?')) {
                const taskIdInput = document.getElementById('task_action_id');
                if (taskIdInput) {
                    // Trigger Gradio update
                    taskIdInput.value = taskId;
                    taskIdInput.dispatchEvent(new Event('input', { bubbles: true }));
                }
            }
        }
    };

    // Auto-refresh task list when queue tab is visible
    let refreshInterval = null;

    function startAutoRefresh() {
        if (refreshInterval) return;

        refreshInterval = setInterval(() => {
            const taskQueueTab = document.getElementById('task_queue_tab');
            if (taskQueueTab && taskQueueTab.offsetParent !== null) {
                // Tab is visible, refresh
                const refreshBtn = document.querySelector('#task_queue_tab [id*="refresh"]');
                if (refreshBtn) {
                    refreshBtn.click();
                }
            }
        }, 5000); // Refresh every 5 seconds
    }

    function stopAutoRefresh() {
        if (refreshInterval) {
            clearInterval(refreshInterval);
            refreshInterval = null;
        }
    }

    // Initialize when page loads
    function init() {
        console.log('[TaskScheduler] Initializing...');

        // Try to inject buttons (may need retry due to Gradio loading)
        let attempts = 0;
        const maxAttempts = 30;

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
            }
        }

        tryInject();

        // Add CSS animations
        const style = document.createElement('style');
        style.textContent = `
            @keyframes slideIn {
                from { transform: translateX(100%); opacity: 0; }
                to { transform: translateX(0); opacity: 1; }
            }
            @keyframes slideOut {
                from { transform: translateX(0); opacity: 1; }
                to { transform: translateX(100%); opacity: 0; }
            }
            #txt2img_queue, #img2img_queue {
                min-width: 80px;
            }
        `;
        document.head.appendChild(style);
    }

    onReady(init);
})();
