---
name: Don't change backend routes to match frontend bugs
description: When the frontend hits the wrong URL, tell the user — don't silently change backend routes
type: feedback
---

If an API endpoint returns nothing because the frontend is calling the wrong URL, flag the URL mismatch to the user rather than changing the backend route. The backend spec is the source of truth.

**Why:** User explicitly stopped a route rename that would have broken the spec-defined API shape. The frontend was wrong, not the backend.

**How to apply:** When debugging "endpoint returns nothing" issues, first compare the URL being hit against the defined routes. Report the mismatch and let the user decide which side to fix.
