document.addEventListener('alpine:init', () => {
    // One job's progress, for the tracker that templates/simulate/partials/progress-tracker.html writes.
    // It follows the job's progress stream from init until the job completes, fails or is cancelled, or the tracker is removed.
    Alpine.data('progressTracker', (jobId, resultsUrl) => ({
        status: 'queued',
        step: 'Queued',
        message: 'Waiting to start...',
        progress: 0,
        elapsed: 0,
        error: '',
        resultsUrl,
        reconnecting: false,
        _stream: null,
        _timer: null,

        init() {
            const startTime = Date.now();
            this._timer = setInterval(() => {
                this.elapsed = Math.floor((Date.now() - startTime) / 1000);
            }, 1000);
            this._stream = new EventSource('/api/jobs/' + jobId + '/progress');
            this._stream.addEventListener('progress', (e) => this._onProgress(e.data));
            this._stream.addEventListener('complete', (e) => this._onComplete(e.data));
            onJobProgressStreamErrors(this._stream, {
                failed: (eventData) => this._onFailed(eventData),
                cancelled: (eventData) => this._onCancelled(eventData),
                reconnecting: (reconnecting) => { this.reconnecting = reconnecting; },
                lost: () => this._onLost(),
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

        _onProgress(eventData) {
            const data = JSON.parse(eventData);
            if (data.progress_pct !== undefined) this.progress = data.progress_pct;
            if (data.current_step) this.step = data.current_step;
            if (data.message) this.message = data.message;
            if (data.status) this.status = data.status;
        },

        // A complete or error event ends the job: its handler stops first, so an event it cannot read still ends the stream
        _onComplete(eventData) {
            this._stop();
            const data = JSON.parse(eventData);
            this.status = 'completed';
            this.progress = 100;
            this.step = 'Done';
            this.message = data.message || 'Simulation completed successfully';
        },

        _onFailed(eventData) {
            this._stop();
            const data = JSON.parse(eventData);
            this.status = 'failed';
            this.error = data.message || data.error || 'An unexpected error occurred';
        },

        _onCancelled(eventData) {
            this._stop();
            const data = JSON.parse(eventData);
            this.status = 'cancelled';
            this.step = 'Cancelled';
            this.message = data.message;
        },

        _onLost() {
            this._stop();
            this.status = 'failed';
            this.error = 'Lost connection to server';
        },

        _stop() {
            this.reconnecting = false;
            if (this._stream) {
                this._stream.close();
                this._stream = null;
            }
            if (this._timer) {
                clearInterval(this._timer);
                this._timer = null;
            }
        }
    }));
});
