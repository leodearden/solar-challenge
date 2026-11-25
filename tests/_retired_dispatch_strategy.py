# SPDX-License-Identifier: AGPL-3.0-or-later
"""The refusal of a scenario's retired home- or fleet-level dispatch_strategy key, which names the battery's key in its place."""

import re

#: The battery key a refusal of the retired key names in its place.
BATTERY_DISPATCH_STRATEGY = "battery.dispatch_strategy: {strategy_type: tou_optimized}"


def retired_dispatch_strategy_refusal(key_path: str) -> str:
    """Match the refusal of the retired dispatch_strategy key at *key_path*: its path, then the battery's key in its place."""
    return f"{re.escape(key_path)}: .*{re.escape(BATTERY_DISPATCH_STRATEGY)}"
