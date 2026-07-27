## 2025-05-18 - [Accessibility and Keyboard Navigation Enhancements]
**Learning:** Adding keyboard accessibility (`tabindex`, keydown handlers, focus rings) and visual dragover states to custom drag-and-drop file uploaders significantly increases both usability and inclusion without adding heavy libraries.
**Action:** Always provide full keyboard fallback triggers (Enter/Space) and explicit high-contrast focus rings (e.g. `outline`) when converting standard `div` elements into interactive target areas.
