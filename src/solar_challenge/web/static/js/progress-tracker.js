document.addEventListener('alpine:init', () => {
    // One job's progress, for the tracker that templates/simulate/partials/progress-tracker.html writes.
    // It follows the job with followJobProgress from init until the job ends, the page loses its stream, or the tracker is removed.
    Alpine.data('progressTracker', (jobId, resultsUrl) => ({
        status: 'queued',
        step: 'Queued',
        message: 'Waiting to start...',
        progress: 0,
        elapsed: 0,
        error: '',
        resultsUrl,
        reconnecting: false,
        _stopFollowing: null,
        _timer: null,

        init() {
            const startTime = Date.now();
            this._timer = setInterval(() => {
                this.elapsed = Math.floor((Date.now() - startTime) / 1000);
            }, 1000);
            this._stopFollowing = followJobProgress(jobId, {
                onState: (state) => this._show(state),
                onEnd: (state) => this._end(state),
                onReconnecting: (reconnecting) => { this.reconnecting = reconnecting; },
                onLost: () => this._lose(),
            });
        },

        destroy() {
            this._stop();
        },

        formatTime(seconds) {
            const m = Math.floor(seconds / 60);
            const s = seconds % 60;
            return m > 0 ? m + 'm ' + s + 's' : s + 's';
        },

        // Show a state the job reports, a JobState
        _show(state) {
            this.status = state.status;
            this.progress = state.progress_pct;
            this.step = state.current_step;
            this.message = state.message;
        },

        // Show how the job ended: its final state, or null if the server no longer tracks it.
        // A failed job's message is shown as its error, and the message line keeps its last progress message.
        _end(state) {
            this._stop();
            if (state === null) {
                this.status = 'untracked';
            } else if (state.status === 'failed') {
                this.status = 'failed';
                this.error = state.message;
            } else {
                this._show(state);
            }
        },

        _lose() {
            this._stop();
            this.status = 'failed';
            this.error = 'Lost connection to server';
        },

        _stop() {
            this.reconnecting = false;
            if (this._stopFollowing) {
                this._stopFollowing();
                this._stopFollowing = null;
            }
            if (this._timer) {
                clearInterval(this._timer);
                this._timer = null;
            }
        }
    }));
});
