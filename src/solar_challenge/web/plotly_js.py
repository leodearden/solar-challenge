# SPDX-License-Identifier: AGPL-3.0-or-later
"""Flask Blueprint serving the plotly.js the dashboard's chart pages draw with, from the
installed plotly package.

That is the release plotly writes figure JSON for, and charts.py builds every figure with
plotly. So the JSON and its renderer stay at one version, the one uv.lock pins, and the
pages fetch nothing from another origin.
"""

from pathlib import Path

import plotly
from flask import Blueprint, Response, send_file

_BUNDLED_PLOTLY_JS = Path(plotly.__file__).parent / "package_data" / "plotly.min.js"

bp = Blueprint("plotly_js", __name__)


@bp.route("/plotly.min.js")
def script() -> Response:
    return send_file(_BUNDLED_PLOTLY_JS)
