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


def _bundled_plotly_js() -> Path:
    """Return the plotly.js the installed plotly package bundles, the file plotly.offline.get_plotlyjs() reads; raise FileNotFoundError when the package has no file there."""
    script = Path(plotly.__file__).parent / "package_data" / "plotly.min.js"
    if not script.is_file():
        raise FileNotFoundError(
            "The web dashboard cannot start: the installed plotly package has no plotly.js"
            f" at {script} for the chart pages to draw with. Reinstall plotly; if this"
            " plotly release keeps its plotly.js elsewhere, serve the file"
            " plotly.offline.get_plotlyjs() reads."
        )
    return script


_BUNDLED_PLOTLY_JS = _bundled_plotly_js()

bp = Blueprint("plotly_js", __name__)


@bp.route("/plotly.min.js")
def script() -> Response:
    return send_file(_BUNDLED_PLOTLY_JS)
