document.addEventListener('alpine:init', () => {
    // One job's progress, for the tracker that templates/simulate/partials/progress-tracker.html writes.
    // It follows the job's progress stream from init until the job completes or fails, or the tracker is removed.
    Alpine.data('progressTracker', (jobId) => ({
        status: 'queued',
        step: 'Queued',
        message: 'Waiting to start...',
        progress: 0,
        elapsed: 0,
        error: '',
        completedRunId: '',
        _stream: null,
        _timer: null,

        init() {
            const startTime = Date.now();
            this._timer = setInterval(() => {
                this.elapsed = Math.floor((Date.now() - startTime) / 1000);
            }, 1000);
            this._stream = new EventSource('/api/jobs/' + jobId + '/progress');
            this._stream.addEventListener('progress', (e) => this._onProgress(JSON.parse(e.data)));
            this._stream.addEventListener('complete', (e) => this._onComplete(JSON.parse(e.data)));
            this._stream.addEventListener('error', (e) => this._onError(e.data));
        },

        destroy() {
            this._stop();
        },

        formatTime(seconds) {
            const m = Math.floor(seconds / 60);
            const s = seconds % 60;
            return m > 0 ? m + 'm ' + s + 's' : s + 's';
        },

        _onProgress(data) {
            if (data.progress_pct !== undefined) this.progress = data.progress_pct;
            if (data.current_step) this.step = data.current_step;
            if (data.message) this.message = data.message;
            if (data.status) this.status = data.status;
        },

        _onComplete(data) {
            this.status = 'completed';
            this.progress = 100;
            this.step = 'Done';
            this.message = data.message || 'Simulation completed successfully';
            if (data.run_id) this.completedRunId = data.run_id;
            this._stop();
        },

        // An error event carries the job's failure as JSON, or no data when the stream itself broke
        _onError(eventData) {
            if (eventData) {
                const data = JSON.parse(eventData);
                this.status = 'failed';
                this.error = data.message || data.error || 'An unexpected error occurred';
            } else if (this.status !== 'completed') {
                this.status = 'failed';
                this.error = 'Lost connection to server';
            }
            this._stop();
        },

        _stop() {
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
