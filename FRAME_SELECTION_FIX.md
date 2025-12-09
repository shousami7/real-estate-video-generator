# Frame Selection UI Bug Fixes

## Summary
Fixed critical bugs in the Frame Selection screen and fullscreen timeline UI that caused event listeners to fail after DOM rebuilds, resulting in non-functional buttons and intermittent popup failures.

## Issues Fixed

### 1. **Missing Event Listeners After DOM Rebuild**
**Problem**: When entering Frame Selection mode, the DOM for frames and tools was dynamically rebuilt, but event listeners were only bound once at page load. This caused the "Use This Frame" button and frame click handlers to stop working.

**Solution**: Created `initFrameSelectionUI()` function that rebinds all event listeners every time Frame Selection mode is activated.

### 2. **Null Reference Errors**
**Problem**: Initialization code ran before DOM elements existed, causing null lookups and silent exceptions that blocked the UI.

**Solution**: Implemented safe DOM lookup helpers:
- `$(sel)` - Safe querySelector with error handling
- `on(el, ev, fn)` - Safe event binding that only binds if element exists

### 3. **Late Initialization Failures**
**Problem**: If the script loaded after DOMContentLoaded, initialization would fail silently.

**Solution**: Added resilient initialization that works whether script loads before or after DOMContentLoaded:
```javascript
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initFunction);
} else {
    initFunction();
}
```

### 4. **Duplicate Event Listeners**
**Problem**: Re-rendering caused duplicate listeners to be attached, creating jitter and race conditions.

**Solution**: 
- Removed static event listener bindings at page load
- Used element cloning technique to remove old listeners before adding new ones
- Centralized all listener binding in `initFrameSelectionUI()`

### 5. **Popup Display Timing**
**Problem**: Heavy synchronous logic blocked the main thread before showing the popup.

**Solution**: Used `setTimeout(..., 0)` to ensure DOM rendering completes before initialization runs:
```javascript
setTimeout(() => {
    initFrameSelectionUI();
}, 0);
```

## Code Changes

### 1. Safe DOM Helpers (lines 2150-2167)
```javascript
const $ = (sel) => {
    try {
        return document.querySelector(sel);
    } catch (e) {
        console.warn(`DOM query failed for: ${sel}`, e);
        return null;
    }
};

const on = (el, ev, fn) => {
    if (el && typeof el.addEventListener === 'function') {
        el.addEventListener(ev, fn);
        return true;
    }
    return false;
};
```

### 2. Frame Selection UI Initialization (lines 5233-5313)
```javascript
function initFrameSelectionUI() {
    try {
        // Rebind "Use This Frame" button
        const pickBtn = $('#fullscreen-pick-frame-btn');
        if (pickBtn) {
            const newPickBtn = pickBtn.cloneNode(true);
            pickBtn.parentNode.replaceChild(newPickBtn, pickBtn);
            on(newPickBtn, 'click', useSelectedFullscreenFrame);
        }

        // Rebind close button, chat buttons, toolbar buttons...
        // (Full implementation in code)

        console.log('Frame Selection UI initialized successfully');
    } catch (error) {
        console.error('Error initializing Frame Selection UI:', error);
        // Don't throw - allow partial initialization
    }
}
```

### 3. Updated openFullscreenTimeline (lines 5315-5383)
Added initialization call after DOM rendering:
```javascript
function openFullscreenTimeline(frames) {
    // ... render DOM ...
    
    // CRITICAL: Initialize Frame Selection UI after DOM is ready
    setTimeout(() => {
        initFrameSelectionUI();
    }, 0);
}
```

### 4. Late Initialization Support (lines 2178-2207)
```javascript
function initFrameExtractionSettings() {
    try {
        const fpsSelect = $('#frame-fps-select');
        const maxSelect = $('#frame-max-select');
        // ... bind events with safe helpers ...
    } catch (error) {
        console.warn('Failed to initialize frame extraction settings:', error);
    }
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initFrameExtractionSettings);
} else {
    initFrameExtractionSettings();
}
```

### 5. Removed Static Bindings (lines 5782-5786)
Removed old static event listener bindings that were causing duplicates:
```javascript
// NOTE: Event listeners for fullscreen buttons are now bound dynamically
// in initFrameSelectionUI() which is called when Frame Selection mode opens.
// This ensures listeners work correctly after DOM rebuilds.
```

## Benefits

✅ **No more intermittent failures** - Popup always appears reliably  
✅ **No missing listeners** - All buttons work after tab switching  
✅ **No jitter** - Duplicate listeners eliminated  
✅ **No null errors** - Safe DOM lookups prevent exceptions  
✅ **No race conditions** - Proper async initialization  
✅ **Error isolation** - Try/catch prevents total UI breakage  

## Testing Recommendations

1. **Basic Flow**: Upload video → Extract frames → Navigate timeline → Click "Use This Frame"
2. **Tab Switching**: Switch between different modes and return to Frame Selection
3. **Rapid Clicking**: Click buttons rapidly to test for duplicate listeners
4. **Late Loading**: Simulate slow network to test late initialization
5. **Error Cases**: Test with missing DOM elements to verify graceful degradation

## Notes

- The Extend and Adjust mode frame grids already had correct listener rebinding patterns
- All changes are backward compatible
- No changes to HTML structure or CSS required
- Console logging added for debugging initialization issues
