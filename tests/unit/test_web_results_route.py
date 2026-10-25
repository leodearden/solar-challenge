# SPDX-License-Identifier: AGPL-3.0-or-later
"""GET /results/<run_id>, a run's one results page, which renders the page of the kind its record names (B8).

The old /results/home/<run_id> and /results/fleet/<run_id> URLs answer 301 to it, whichever
kind the run is, so a bookmark of either keeps resolving. A run the page cannot show, one
with no record or no files, redirects to the dashboard, which flashes "Run not found.". A run
it cannot read, such as one stored before runs carried a format version (B5, before
`solar-challenge web migrate`), redirects there too, flashing the refusal, which names the run
and format_version.
"""

import pytest

pytest.importorskip("flask")

from flask.testing import FlaskClient

from solar_challenge.battery import BatteryConfig
from solar_challenge.web.storage import RunStorage
from tests._finance_builders import make_fleet_results, make_home_config, make_sim_results
from tests._html_page import element_ids, headings, texts
from tests._stored_run_fixtures import install_stored_run_fixture
from tests._web_runs import store_fleet_run, store_home_run

_HOME_RUN_NAME = "North Roof"
_FLEET_RUN_NAME = "Community Fleet"


@pytest.fixture
def home_run_id(storage: RunStorage) -> str:
    """The id of a one-day home run named North Roof, saved as a finished job saves it."""
    run_id = "home-1"
    home = make_home_config(battery_config=BatteryConfig(capacity_kwh=5.0))
    store_home_run(storage, run_id, home, make_sim_results(days=1), name=_HOME_RUN_NAME)
    return run_id


@pytest.fixture
def fleet_run_id(storage: RunStorage) -> str:
    """The id of a one-day two-home fleet run named Community Fleet, saved as a finished job saves it."""
    run_id = "fleet-1"
    store_fleet_run(storage, run_id, make_fleet_results(n_homes=2, days=1), name=_FLEET_RUN_NAME)
    return run_id


def _assert_is_the_home_results_page(page: str) -> None:
    """Assert that *page* is the home run's results page: titled with its name, with the home-only Sankey chart."""
    assert headings(page)[0] == _HOME_RUN_NAME
    assert "chart-sankey" in element_ids(page)


def _assert_is_the_fleet_results_page(page: str) -> None:
    """Assert that *page* is the fleet run's results page: titled with its name, with the fleet's aggregate timeline and no Sankey chart."""
    ids = element_ids(page)
    assert headings(page)[0] == _FLEET_RUN_NAME
    assert "chart-aggregate-timeline" in ids
    assert "chart-sankey" not in ids


def test_the_results_page_of_a_home_run_is_the_home_page(client: FlaskClient, home_run_id: str) -> None:
    response = client.get(f"/results/{home_run_id}")

    assert response.status_code == 200
    _assert_is_the_home_results_page(response.get_data(as_text=True))


def test_the_results_page_of_a_fleet_run_is_the_fleet_page(client: FlaskClient, fleet_run_id: str) -> None:
    response = client.get(f"/results/{fleet_run_id}")

    assert response.status_code == 200
    _assert_is_the_fleet_results_page(response.get_data(as_text=True))


def test_the_old_home_results_url_of_a_fleet_run_moves_permanently_to_its_results_page(
    client: FlaskClient, fleet_run_id: str
) -> None:
    response = client.get(f"/results/home/{fleet_run_id}")

    assert (response.status_code, response.location) == (301, f"/results/{fleet_run_id}")
    followed = client.get(f"/results/home/{fleet_run_id}", follow_redirects=True)
    assert followed.status_code == 200
    _assert_is_the_fleet_results_page(followed.get_data(as_text=True))


def test_the_old_fleet_results_url_of_a_home_run_moves_permanently_to_its_results_page(
    client: FlaskClient, home_run_id: str
) -> None:
    response = client.get(f"/results/fleet/{home_run_id}")

    assert (response.status_code, response.location) == (301, f"/results/{home_run_id}")
    followed = client.get(f"/results/fleet/{home_run_id}", follow_redirects=True)
    assert followed.status_code == 200
    _assert_is_the_home_results_page(followed.get_data(as_text=True))


def test_the_results_page_of_an_id_no_run_has_redirects_to_the_dashboard_flashing_run_not_found(
    client: FlaskClient,
) -> None:
    response = client.get("/results/no-such-run", follow_redirects=True)

    assert [(hop.status_code, hop.location) for hop in response.history] == [(302, "/")]
    assert "Run not found." in texts(response.get_data(as_text=True))


def test_the_results_page_of_a_run_whose_job_saved_no_files_redirects_to_the_dashboard_flashing_run_not_found(
    storage: RunStorage, client: FlaskClient
) -> None:
    storage.create_run("pending-1", run_type="home", name="Pending", n_homes=1, created_at="2024-06-01T09:00:00+00:00")

    response = client.get("/results/pending-1", follow_redirects=True)

    assert [(hop.status_code, hop.location) for hop in response.history] == [(302, "/")]
    assert "Run not found." in texts(response.get_data(as_text=True))


@pytest.mark.parametrize("name", ["pre_469_home", "legacy_fleet"])
def test_the_results_page_of_a_run_stored_before_format_versions_redirects_to_the_dashboard_flashing_format_version(
    client: FlaskClient, storage: RunStorage, name: str
) -> None:
    """B5 before `solar-challenge web migrate`: the flash names the run and its missing format_version, never a 500."""
    run_id = install_stored_run_fixture(name, storage.database, storage.data_dir)

    response = client.get(f"/results/{run_id}", follow_redirects=True)

    assert [(hop.status_code, hop.location) for hop in response.history] == [(302, "/")]
    assert response.status_code == 200
    page_texts = texts(response.get_data(as_text=True))
    assert len([text for text in page_texts if run_id in text and "format_version" in text]) == 1, page_texts
