// A job's progress stream is the EventSource on /api/jobs/<job_id>/progress, and followJobProgress is the only code
// that opens one or reads its frames. The server's events are web/sse.py's job catalogue. progress, completed, failed
// and cancelled each carry the job's whole state, a JobState, and the last three end the job; untracked ends the
// stream of a job the server no longer tracks; timeout ends a stream open past the server's limit while the job goes
// on. The browser then reopens the stream itself after the frame's retry, resuming after the last state it was sent.
// The EventSource's own error event is the transport alone: the stream breaking, after which the browser reopens it,
// its readyState CONNECTING until it opens, unless it gives the stream up (CLOSED), as after an HTTP error. The page
// gives up a stream still broken this long after it broke, so a server out of reach ends the wait.
const JOB_PROGRESS_RECONNECT_LIMIT_MS = 60 * 1000;

// Follow job jobId's progress stream: call onState(state) with each state the job reports while it is unfinished,
// then onEnd(state) once with its final state, or with null if the server no longer tracks the job;
// onReconnecting(true) when the stream breaks unexpectedly and onReconnecting(false) when it opens; and onLost() once
// the browser, or the reconnect limit, has given the stream up, or the job's final state cannot be read. Returns the
// function that stops following the job.
function followJobProgress(jobId, { onState, onEnd, onReconnecting = () => {}, onLost }) {
    const stream = new EventSource('/api/jobs/' + jobId + '/progress');
    let giveUpTimer = null;
    // Set by timeout: the break that follows is the server ending the stream, not the connection failing
    let breakExpected = false;
    const stop = () => {
        stream.close();
        clearTimeout(giveUpTimer);
        giveUpTimer = null;
    };
    const lose = () => {
        stop();
        onLost();
    };
    const giveUpIfStillBroken = () => {
        if (stream.readyState === EventSource.CONNECTING) lose();
    };
    // A final state that cannot be read loses the stream, so the page still learns it ended, and its error is rethrown
    // for the console
    const endWith = (readFinalState) => (e) => {
        stop();
        let finalState;
        try {
            finalState = readFinalState(e);
        } catch (unreadable) {
            onLost();
            throw unreadable;
        }
        onEnd(finalState);
    };
    const readState = (e) => JSON.parse(e.data);
    stream.addEventListener('progress', (e) => onState(readState(e)));
    stream.addEventListener('completed', endWith(readState));
    stream.addEventListener('failed', endWith(readState));
    stream.addEventListener('cancelled', endWith(readState));
    stream.addEventListener('untracked', endWith(() => null));
    stream.addEventListener('timeout', () => { breakExpected = true; });
    stream.addEventListener('open', () => {
        clearTimeout(giveUpTimer);
        giveUpTimer = null;
        onReconnecting(false);
    });
    stream.addEventListener('error', () => {
        if (stream.readyState !== EventSource.CONNECTING) {
            lose();
            return;
        }
        giveUpTimer ??= setTimeout(giveUpIfStillBroken, JOB_PROGRESS_RECONNECT_LIMIT_MS);
        if (!breakExpected) onReconnecting(true);
        breakExpected = false;
    });
    return stop;
}
