# SPDX-License-Identifier: AGPL-3.0-or-later
"""The frame that ends a job's progress stream with a final state the page cannot read."""

import math

from tests.e2e._job_requests import a_job_state, job_state_frame


def unreadable_final_state_frame(job_id: str, run_id: str) -> str:
    """The frame that ends the progress stream of job job_id, of run run_id, with a completed state whose progress is NaN: sse_frame's json.dumps writes the bare token NaN, which the page's JSON.parse refuses."""
    return job_state_frame(
        a_job_state(job_id, run_id, "completed", progress_pct=math.nan), version=5
    )
