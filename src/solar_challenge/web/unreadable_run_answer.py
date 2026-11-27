# SPDX-License-Identifier: AGPL-3.0-or-later
"""The JSON answer to a request that reads a stored run which cannot be read (D-S19-9 in docs/prds/run-store-one-owner.md).

Each blueprint whose JSON answers read stored runs registers answer_stored_run_unreadable as its
handler of StoredRunUnreadable, so the 409 has one shape wherever it is answered. A page flashes
the refusal and redirects instead.
"""

import logging

from flask import Response, jsonify

from solar_challenge.web.stored_runs import StoredRunUnreadable

logger = logging.getLogger(__name__)


def answer_stored_run_unreadable(unreadable: StoredRunUnreadable) -> tuple[Response, int]:
    """Answer HTTP 409 with the refusal of a stored run that cannot be read, logged as a warning: its message as error, and its run_id, document and field.

    field is None when the document as a whole is refused.
    """
    logger.warning("%s", unreadable)
    return jsonify(
        {"error": str(unreadable), "run_id": unreadable.run_id, "document": unreadable.document, "field": unreadable.field}
    ), 409
