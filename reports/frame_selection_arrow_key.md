# Investigation: Arrow key navigation stuck during frame selection

## Summary of issue
Users report that pressing the left or right arrow keys while selecting frames does not move the focus to another frame (the selection appears "stuck").

## Findings
- Keyboard navigation for the inline frame timeline is handled by `handleTimelineKeyboard` in `templates/video_editor_ui.html`.
- The handler immediately returns whenever a fullscreen timeline element exists because it checks `document.querySelector('.fullscreen-timeline-mode')` without verifying whether the fullscreen mode is actually open.
- The fullscreen container is always present in the DOM, just toggled with the `hidden` class. Because the querySelector always finds this element, the handler exits early, preventing arrow key logic from running at all. As a result, pressing the arrow keys never calls `selectTimelineFrame`, leaving focus on the original frame and making navigation feel stuck.

## Evidence
- Early exit in `handleTimelineKeyboard` due to the existence of the fullscreen element, which is always truthy even when hidden: `const isFullscreen = document.querySelector('.fullscreen-timeline-mode'); if (timelineSection.classList.contains('hidden') || isFullscreen) return;`【F:templates/video_editor_ui.html†L5634-L5651】

## Conclusion
The arrow key navigation stops because the inline timeline keyboard handler incorrectly treats the mere presence of the fullscreen timeline element as meaning fullscreen is active. This prevents the arrow key handler from running, keeping the selection stuck on the current frame. Updating the condition to check the actual fullscreen state (e.g., `isFullscreenTimelineOpen` or `.hidden` visibility) would allow the handler to process arrow key presses normally.
