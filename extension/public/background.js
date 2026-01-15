// Background service worker for Stepwise extension
// Handles side panel opening when Focus Toggle is clicked

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.action === 'openSidePanel') {
        // Open the side panel for the current window
        chrome.sidePanel.open({ windowId: message.windowId })
            .then(() => {
                sendResponse({ success: true });
            })
            .catch((error) => {
                console.error('Failed to open side panel:', error);
                sendResponse({ success: false, error: error.message });
            });
        // Return true to indicate we'll send response asynchronously
        return true;
    }
});

// Set side panel behavior - open on action click is optional
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: false })
    .catch((error) => console.error('Failed to set panel behavior:', error));
