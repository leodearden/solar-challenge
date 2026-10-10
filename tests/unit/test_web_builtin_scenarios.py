# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.web.builtin_scenarios.scenario_files_in: the scenario files a directory holds, each by its name."""

from pathlib import Path

from solar_challenge.web.builtin_scenarios import scenario_files_in


def test_scenario_files_are_named_by_their_stems_in_name_order(tmp_path: Path) -> None:
    """Each .yaml and .yml file is named by its stem, in name order: bristol before bristol-aged, whose file name sorts first."""
    for file_name in ("bristol-aged.yaml", "bristol.yaml", "arbitrage.yml"):
        (tmp_path / file_name).write_text("")

    assert list(scenario_files_in(tmp_path).items()) == [
        ("arbitrage", tmp_path / "arbitrage.yml"),
        ("bristol", tmp_path / "bristol.yaml"),
        ("bristol-aged", tmp_path / "bristol-aged.yaml"),
    ]


def test_a_name_with_both_a_yaml_and_a_yml_file_means_its_yaml_file(tmp_path: Path) -> None:
    """A stem with a file of each suffix is one scenario, its .yaml file."""
    (tmp_path / "fleet.yml").write_text("")
    (tmp_path / "fleet.yaml").write_text("")

    assert list(scenario_files_in(tmp_path).items()) == [("fleet", tmp_path / "fleet.yaml")]


def test_a_name_with_only_a_yml_file_means_its_yml_file(tmp_path: Path) -> None:
    """A stem with a .yml file and no .yaml file is that .yml file."""
    (tmp_path / "fleet.yml").write_text("")

    assert list(scenario_files_in(tmp_path).items()) == [("fleet", tmp_path / "fleet.yml")]


def test_entries_that_are_not_yaml_files_are_not_scenario_files(tmp_path: Path) -> None:
    """A file of another suffix is not a scenario, nor is a directory named like one: its stem means the .yml file beside it."""
    (tmp_path / "notes.txt").write_text("")
    (tmp_path / "fleet.yaml").mkdir()
    (tmp_path / "fleet.yml").write_text("")

    assert list(scenario_files_in(tmp_path).items()) == [("fleet", tmp_path / "fleet.yml")]


def test_a_missing_directory_holds_no_scenario_files(tmp_path: Path) -> None:
    """A directory that does not exist, as scenarios/ in an installed package, holds none."""
    assert scenario_files_in(tmp_path / "scenarios") == {}
