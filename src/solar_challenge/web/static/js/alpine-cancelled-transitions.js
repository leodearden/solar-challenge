// SPDX-License-Identifier: AGPL-3.0-or-later
// Alpine rejects an x-show element's hide with { isFromCancelledTransition: true } when the element is shown again
// before the animation frame after the hide, and attaches its own handler, which ignores that reason, only in that
// frame. This handles that rejection as Alpine's handler does, and leaves every other unhandled rejection uncaught.
// tests/e2e/test_fleet_interactions.py and tests/e2e/test_page_errors.py hold the contract.
window.addEventListener('unhandledrejection', (event) => {
    if (event.reason?.isFromCancelledTransition === true) event.preventDefault();
});
