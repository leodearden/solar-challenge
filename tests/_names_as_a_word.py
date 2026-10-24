# SPDX-License-Identifier: AGPL-3.0-or-later
"""Whether a message names a value as a word of its own, as a refusal naming the value it refuses does.

A substring check also passes on a message that holds the value only inside a longer word
or number: "inf" is in "infinite" and in "-inf", and "1" is in "1.5". A test that pins only
that a refusal names its value, not the rest of its wording, asks names_as_a_word instead.

Usage::

    from tests._names_as_a_word import names_as_a_word

    with pytest.raises(ConfigurationError) as refusal:
        TariffPeriod(start_time="09:00", end_time="17:00", rate_per_kwh=float("inf"))
    assert names_as_a_word(str(refusal.value), float("inf"))
"""

import re


def names_as_a_word(text: str, value: object) -> bool:
    """Whether *text* names str(*value*) as a word of its own: "-inf" does not name "inf", nor does "infinite"."""
    return re.search(rf"(?<![\w.-]){re.escape(str(value))}(?![\w.])", text) is not None
