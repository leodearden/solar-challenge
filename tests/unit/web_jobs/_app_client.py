# SPDX-License-Identifier: AGPL-3.0-or-later
"""The request a home job is submitted with, and serving an app's job progress streams under a JobStreamPolicy the test chose."""

from flask import Flask

from solar_challenge.web.sse import JobStreamPolicy
from tests._web_job_days import web_job_days


A_HOME_JOB_DAYS = web_job_days(count=1)
A_HOME_JOB_REQUEST = {
    "pv_kw": 4.0,
    "battery_kwh": 0,
    "occupants": 3,
    "location": "bristol",
    "days": A_HOME_JOB_DAYS.count,
}


def serve_job_streams_under(app: Flask, policy: JobStreamPolicy) -> None:
    """Install *policy* as the app's job stream policy, the one its job progress streams are served under."""
    app.extensions["job_stream_policy"] = policy
