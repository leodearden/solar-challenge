# SPDX-License-Identifier: AGPL-3.0-or-later
"""Submitting jobs through the web app to a JobManager the test chose."""

from flask import Flask
from flask.testing import FlaskClient

from solar_challenge.web.jobs import JobManager


A_HOME_JOB_REQUEST = {"pv_kw": 4.0, "battery_kwh": 0, "occupants": 3, "location": "bristol", "days": 1}


def client_using(app: Flask, manager: JobManager) -> FlaskClient:
    """Install *manager* as the app's job manager, and return a client of the app."""
    app.extensions["job_manager"] = manager
    return app.test_client()
