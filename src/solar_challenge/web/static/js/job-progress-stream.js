// A job's progress stream is the EventSource a page opens on /api/jobs/<job_id>/progress. An error event on it that
// carries data, which the server sends as JSON, ends the job without results: its failure or, until S20, its
// cancellation. Without data it is the stream breaking: the browser then reopens the stream itself, its readyState
// CONNECTING until it opens, unless it gives the stream up (CLOSED), as after an HTTP error. The page gives up a stream
// still broken this long after it broke, so a server out of reach ends the wait.
const JOB_PROGRESS_RECONNECT_LIMIT_MS = 60 * 1000;

// Call failed(eventData) on the job's failure or cancellation, reconnecting(true) when stream breaks and
// reconnecting(false) when it opens, and lost() once the browser, or the reconnect limit, has given stream up and closed it
function onJobProgressStreamErrors(stream, { failed, reconnecting = () => {}, lost }) {
    let giveUpTimer = null;
    const giveUpIfStillBroken = () => {
        if (stream.readyState !== EventSource.CONNECTING) return;
        stream.close();
        lost();
    };
    stream.addEventListener('open', () => {
        clearTimeout(giveUpTimer);
        giveUpTimer = null;
        reconnecting(false);
    });
    stream.addEventListener('error', (e) => {
        if (e.data) {
            failed(e.data);
        } else if (stream.readyState === EventSource.CONNECTING) {
            giveUpTimer ??= setTimeout(giveUpIfStillBroken, JOB_PROGRESS_RECONNECT_LIMIT_MS);
            reconnecting(true);
        } else {
            lost();
        }
    });
}
