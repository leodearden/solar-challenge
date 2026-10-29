# SPDX-License-Identifier: AGPL-3.0-or-later
"""JSON text nested too deeply for json.loads to decode, as tests write it into a stored run's document.

json.loads gives up on deep nesting at a depth that differs by minor, from about a thousand
arrays on 3.11 to tens of thousands on 3.14, whose check is stack-based. A million arrays is
deeper than each, so json.loads raises RecursionError for this text, not a ValueError, on
every admitted minor.

Usage::

    from tests._deeply_nested_json import JSON_NESTED_TOO_DEEPLY_TO_DECODE

    def test_a_summary_nested_too_deeply_to_decode_is_refused_as_a_whole(storage: RunStorage) -> None:
        store_home_run(storage, "home-1", make_home_config(), make_sim_results(days=1))
        (stored_run_dir(storage, "home-1") / "summary.json").write_text(JSON_NESTED_TOO_DEEPLY_TO_DECODE)
        with pytest.raises(StoredRunUnreadable):
            storage.load_run("home-1")
"""

#: An array holding an array, a million deep, which json.loads refuses with RecursionError on every admitted minor.
JSON_NESTED_TOO_DEEPLY_TO_DECODE = "[" * 1_000_000 + "]" * 1_000_000
