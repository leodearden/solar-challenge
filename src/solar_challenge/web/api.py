# SPDX-License-Identifier: AGPL-3.0-or-later
"""Flask Blueprint providing JSON API endpoints for background simulations.

Provides REST endpoints for submitting simulation jobs, polling status,
streaming progress via SSE, retrieving results, and consolidated history
and scenarios API endpoints under the /api/ prefix.
"""

import functools
import logging
import math
from collections.abc import Mapping
from dataclasses import asdict
from datetime import date
from typing import Any

import yaml as _yaml
import pandas as pd
from flask import Blueprint, Response, jsonify, request, url_for

from solar_challenge.home import HomeConfig
from solar_challenge.number_fields import Interval, as_finite_float, as_whole_number
from solar_challenge.scenario_writer import scenario_yaml
from solar_challenge.web.builder_form import builder_form_errors, scenario_from_builder_form
from solar_challenge.web.builtin_scenarios import builtin_scenario_files
from solar_challenge.web.fleet_config import sample_distribution
from solar_challenge.web.fleet_presets import fleet_preset_form
from solar_challenge.web.fleet_scenario import (
    FLEET_FORM_REFUSALS,
    ImportedFleetForm,
    fleet_form_from_yaml,
    parse_fleet_form,
    scenario_from_fleet_form,
)
from solar_challenge.web.presets import (
    PresetNameTaken,
    PresetType,
    SavedPresetUnreadable,
    home_preset_named,
    home_presets,
    save_config_preset,
    saved_fleet_preset_named,
    saved_fleet_presets,
)
from solar_challenge.web.request_boundary import NotAJsonObject, request_json_object, require_json_object
from solar_challenge.web.shared import get_database, get_job_manager, get_storage
from solar_challenge.web.simulation_params import parse_home_config, with_default_days
from solar_challenge.web.sse import JobStreamPolicy, event_stream, job_progress_frames, parse_last_event_id
from solar_challenge.web.storage import RUN_LABELS, RUN_SORTS, RunQuery, RunRecord, headline_figures
from solar_challenge.web.stored_runs import RUN_TYPES, StoredRunUnreadable
from solar_challenge.web.text_options import one_of

logger = logging.getLogger(__name__)

api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.errorhandler(NotAJsonObject)
def _refuse_a_value_that_is_not_a_json_object(refusal: NotAJsonObject) -> tuple[Response, int]:
    """Answer HTTP 400 with the refusal of a request value that must be a JSON object and is not one.

    Any endpoint of this blueprint that reads such a value is answered this way.
    """
    return jsonify({"error": str(refusal)}), 400


@api_bp.errorhandler(SavedPresetUnreadable)
def _answer_a_saved_preset_that_cannot_be_read(unreadable: SavedPresetUnreadable) -> tuple[Response, int]:
    """Answer HTTP 500 with the error naming a saved preset that cannot be read, logged at ERROR with its traceback.

    Any endpoint of this blueprint that looks a saved preset up is answered this way.
    """
    logger.error("%s", unreadable, exc_info=unreadable)
    return jsonify({"error": str(unreadable)}), 500


@api_bp.errorhandler(StoredRunUnreadable)
def answer_stored_run_unreadable(unreadable: StoredRunUnreadable) -> tuple[Response, int]:
    """Answer HTTP 409 with the refusal of a stored run that cannot be read, logged as a warning: its message as error, and its run_id, document and field.

    Any endpoint of this blueprint that reads a stored run is answered this way, and a JSON
    endpoint of another blueprint answers through it (D-S19-9 in docs/prds/run-store-one-owner.md);
    field is None when the document as a whole is refused.
    """
    logger.warning("%s", unreadable)
    return jsonify(
        {"error": str(unreadable), "run_id": unreadable.run_id, "document": unreadable.document, "field": unreadable.field}
    ), 409


def _submitted_job_answer(job_id: str, run_id: str) -> tuple[Response, int]:
    """Answer HTTP 201 with a submitted job's job_id and run_id, and as results_url the path of its run's results page."""
    return jsonify({
        "job_id": job_id,
        "run_id": run_id,
        "results_url": url_for("main.run_results", run_id=run_id),
    }), 201


@api_bp.route("/simulate/home", methods=["POST"])
def simulate_home_api() -> tuple[Response, int]:
    """Submit a home simulation job for background execution.

    Expects a JSON body with simulation parameters.

    Returns:
        JSON with job_id, run_id and results_url, HTTP 201 on success.
    """
    data = request_json_object()
    try:
        home_config, start_date, end_date, name = parse_home_config(data)
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400
    job_manager = get_job_manager()

    job_id, run_id = job_manager.submit_home_job(
        config=home_config,
        start_date=start_date,
        end_date=end_date,
        name=name,
    )

    return _submitted_job_answer(job_id, run_id)

@api_bp.route("/simulate/fleet", methods=["POST"])
def simulate_fleet_api() -> tuple[Response, int]:
    """Submit a fleet simulation job for background execution.

    Expects a JSON body with a non-empty array of home configs under the 'homes' key.

    Returns:
        JSON with job_id, run_id and results_url, HTTP 201 on success.
    """
    data = request_json_object()
    homes_data = data.get("homes", [])
    if not isinstance(homes_data, list):
        return jsonify({"error": f"homes must be a JSON array, got {type(homes_data).__name__}"}), 400
    if not homes_data:
        return jsonify({"error": "Fleet requires at least one home config in 'homes' array"}), 400
    try:
        configs = []
        # Use first home's date config for the fleet
        first_config, start_date, end_date, _ = parse_home_config(homes_data[0])
        configs.append(first_config)

        for home_data in homes_data[1:]:
            config, _, _, _ = parse_home_config(home_data)
            configs.append(config)
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400

    job_manager = get_job_manager()

    job_id, run_id = job_manager.submit_fleet_job(
        configs=configs,
        start_date=start_date,
        end_date=end_date,
        name=data.get("name"),
    )

    return _submitted_job_answer(job_id, run_id)

@api_bp.route("/jobs/<job_id>", methods=["GET"])
def get_job_status(job_id: str) -> tuple[Response, int]:
    """Return current job status as JSON.

    Args:
        job_id: Unique job identifier.

    Returns:
        JSON with job status fields, or 404 if not found.
    """
    job_manager = get_job_manager()
    state = job_manager.job_state(job_id)

    if state is None:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(asdict(state)), 200


@api_bp.route("/jobs/<job_id>/progress", methods=["GET"])
def get_job_progress(job_id: str) -> Response:
    """Stream the job's snapshots as Server-Sent Events, as web/sse.py's job_progress_frames sends them.

    A stream sends the job's current state at once and each newer state as the job
    reports it, and ends with the job. A reopened stream resumes after the version its
    Last-Event-ID header names.

    Args:
        job_id: Unique job identifier.

    Returns:
        text/event-stream response.
    """
    job_manager = get_job_manager()
    return event_stream(
        job_progress_frames(
            functools.partial(job_manager.job_snapshot, job_id),
            last_event_id=parse_last_event_id(request.headers.get("Last-Event-ID")),
            policy=JobStreamPolicy(),
        )
    )


@api_bp.route("/jobs/<job_id>/results", methods=["GET"])
def get_job_results(job_id: str) -> tuple[Response, int]:
    """Return completed job results as JSON.

    Args:
        job_id: Unique job identifier.

    Returns:
        JSON with the job's run's id, name, type and creation time, and as ``summary`` its
        summary's field tree, {} while it has none; or 404/409 on error. A run whose summary
        cannot be read is answered 409 with its refusal, as the blueprint answers a
        StoredRunUnreadable.
    """
    job_manager = get_job_manager()
    state = job_manager.job_state(job_id)

    if state is None:
        return jsonify({"error": "Job not found"}), 404
    if state.status != "completed":
        return jsonify({
            "error": "Job not yet completed",
            "status": state.status,
            "progress_pct": state.progress_pct,
        }), 409
    # Load run summary from database
    run_id = state.run_id
    run = get_storage().run_record(run_id)

    if run is None:
        return jsonify({"error": "Run not found"}), 404
    summary = run.summary()

    return jsonify({
        "run_id": run_id,
        "name": run.name,
        "type": run.type,
        "created_at": run.created_at,
        "summary": {} if summary is None else asdict(summary),
    }), 200

# ---------------------------------------------------------------------------
# Config preset endpoints
# ---------------------------------------------------------------------------

@api_bp.route("/presets", methods=["GET"])
def list_presets() -> tuple[Response, int]:
    """List the home presets: the built-in presets, then the saved home presets by name, each name once.

    Returns:
        JSON array of preset objects, HTTP 200.
    """
    return jsonify(home_presets(get_database())), 200

def _answer_preset_save(name: str, preset_type: PresetType, config: Mapping[str, Any]) -> tuple[Response, int]:
    """Save *config* as the *preset_type* preset *name*, answering as both preset save endpoints do.

    Returns:
        JSON with the preset name and id, HTTP 201; or the ``error``: HTTP 409 for a
        name another preset holds, HTTP 500 for a database fault.
    """
    try:
        preset_id = save_config_preset(get_database(), name, preset_type, config)
    except PresetNameTaken as taken:
        return jsonify({"error": str(taken)}), 409
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 500
    return jsonify({"name": name, "id": preset_id}), 201

@api_bp.route("/presets", methods=["POST"])
def save_preset() -> tuple[Response, int]:
    """Save a home preset to the database.

    Expects a JSON body with at least ``name`` and configuration fields. A ``type``, when sent,
    must be 'home': fleet presets are saved through POST /api/scenarios/save.

    Returns:
        JSON confirmation with the preset name and id, HTTP 201 on success; or the ``error``:
        HTTP 400 for an empty name or a type other than 'home', HTTP 409 for a name a built-in
        home preset or a saved fleet preset holds.
    """
    data = request_json_object()
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Preset name is required"}), 400
    preset_type = data.get("type", "home")
    if preset_type != "home":
        return jsonify(
            {"error": f"type must be 'home', got {preset_type!r}; POST /api/scenarios/save saves fleet presets"}
        ), 400
    config_payload = {
        k: v for k, v in data.items() if k not in ("name", "type")
    }
    return _answer_preset_save(name, "home", config_payload)

@api_bp.route("/presets/<name>", methods=["GET"])
def get_preset(name: str) -> tuple[Response, int]:
    """Get the home preset named *name*, as GET /api/presets lists it when the database can be read.

    A built-in preset's name answers the built-in preset, even when the database cannot be
    read, and a name only a saved fleet preset holds is not found.

    Args:
        name: The preset name to look up.

    Returns:
        JSON preset object, HTTP 200; or the ``error``: HTTP 404 when the database was read
        and GET /api/presets lists none under the name; HTTP 500, with the fault logged, when
        the name is not a built-in preset's and the database cannot be read.
    """
    preset = home_preset_named(get_database(), name)
    if preset is None:
        return jsonify({"error": f"Preset '{name}' not found"}), 404
    return jsonify(preset), 200

# ---------------------------------------------------------------------------
# Fleet distribution endpoints
# ---------------------------------------------------------------------------


@api_bp.route("/fleet/preview-distribution", methods=["POST"])
def preview_distribution() -> tuple[Response, int]:
    """Generate sample data for distribution histogram preview.

    Expects a JSON body with ``type``, ``params``, and an optional ``n_samples``
    from 1 to MAX_FLEET_HOMES (default 100).

    Returns:
        JSON with ``samples`` array, HTTP 200 on success; or the ``error``,
        HTTP 400, when sample_distribution refuses the type, params or n_samples.
    """
    data = request_json_object()
    dist_type = data.get("type", "normal")
    params = data.get("params", {})
    n_samples = data.get("n_samples", 100)

    try:
        samples = sample_distribution(dist_type, params, n_samples)
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"samples": samples}), 200

@api_bp.route("/simulate/fleet-from-distribution", methods=["POST"])
def simulate_fleet_from_distribution() -> tuple[Response, int]:
    """Submit a fleet simulation using distribution configuration.

    Expects the JSON body the fleet page posts, a fleet form, read by
    :func:`~solar_challenge.web.fleet_scenario.parse_fleet_form`.

    Returns:
        JSON with ``job_id``, ``run_id`` and ``results_url``, HTTP 201 on success; or the ``error``,
        HTTP 400, for a form parse_fleet_form refuses.
    """
    data = request_json_object()

    job_manager = get_job_manager()

    try:
        fleet = parse_fleet_form(data)
    except FLEET_FORM_REFUSALS as exc:
        return jsonify({"error": str(exc)}), 400

    job_id, run_id = job_manager.submit_fleet_job(
        configs=list(fleet.homes),
        start_date=fleet.start_date,
        end_date=fleet.end_date,
        name=fleet.name,
    )

    return _submitted_job_answer(job_id, run_id)

@api_bp.route("/fleet/export-yaml", methods=["POST"])
def export_fleet_yaml() -> Response | tuple[Response, int]:
    """Export the fleet page's form as the fleet scenario load_fleet_config reads back.

    Expects the JSON body the fleet page posts to /api/simulate/fleet-from-distribution.

    Returns:
        The scenario's YAML file as a download, HTTP 200; or the ``error``, HTTP 400, for a
        form the simulate endpoint refuses, with its message: both read the form with
        :func:`~solar_challenge.web.fleet_scenario.parse_fleet_form`.
    """
    data = request_json_object()
    try:
        document = scenario_from_fleet_form(data)
    except FLEET_FORM_REFUSALS as exc:
        return jsonify({"error": str(exc)}), 400
    return Response(
        scenario_yaml(document),
        mimetype="text/yaml",
        headers={"Content-Disposition": "attachment; filename=fleet-config.yaml"},
    )


@api_bp.route("/fleet/import-yaml", methods=["POST"])
def import_fleet_yaml() -> tuple[Response, int]:
    """Import a fleet scenario's YAML as the fleet page's form.

    Accepts the raw YAML text as the request body (Content-Type: text/yaml).

    Returns:
        The answer of :func:`_loaded_fleet_form_answer`; or the ``error``, HTTP 400, for an
        empty body, YAML that does not parse, or a scenario the fleet page cannot load.
    """
    yaml_text = request.get_data(as_text=True)
    if not yaml_text:
        return jsonify({"error": "Empty request body"}), 400
    try:
        imported = fleet_form_from_yaml(yaml_text)
    except FLEET_FORM_REFUSALS as exc:
        return jsonify({"error": str(exc)}), 400
    return _loaded_fleet_form_answer(imported)


@api_bp.route("/fleet/presets/<name>", methods=["GET"])
def fleet_preset(name: str) -> tuple[Response, int]:
    """Load the built-in scenario file *name* as the fleet page's form.

    Returns:
        The answer of :func:`_loaded_fleet_form_answer` for the preset's form; or the
        ``error``: HTTP 400 for a built-in scenario file the fleet form cannot load, which
        the Load Preset menu does not offer
        (:func:`~solar_challenge.web.fleet_presets.fleet_preset_names`); HTTP 404 when no
        built-in scenario file is named *name*.
    """
    try:
        imported = fleet_preset_form(name)
    except FLEET_FORM_REFUSALS as exc:
        return jsonify({"error": str(exc)}), 400
    if imported is None:
        return jsonify({"error": f"Preset '{name}' not found"}), 404
    return _loaded_fleet_form_answer(imported)


def _loaded_fleet_form_answer(imported: ImportedFleetForm) -> tuple[Response, int]:
    """The fleet page's answer for the fleet form *imported* from a scenario.

    Returns:
        JSON ``{"form", "not_loaded"}``, HTTP 200: the form is the body the fleet page
        posts, and not_loaded the paths of the scenario's settings it has no control for
        (see :func:`~solar_challenge.web.fleet_scenario.fleet_form_from_scenario`).
    """
    return jsonify({"form": dict(imported.form), "not_loaded": list(imported.not_loaded)}), 200

# ---------------------------------------------------------------------------
# Parameter sweep endpoint
# ---------------------------------------------------------------------------


_SWEEP_PARAMETER_HOME_KEYS: Mapping[str, str] = {
    "pv_capacity_kw": "pv_kw",
    "battery_capacity_kwh": "battery_kwh",
    "annual_consumption_kwh": "consumption_kwh",
}

#: The most steps a sweep may have, which the sweep page's Steps input offers.
SWEEP_MAX_STEPS = 50

#: The days each point of a sweep runs when its base_config sends no window of its own.
_SWEEP_DEFAULT_DAYS = 7


@api_bp.route("/simulate/sweep", methods=["POST"])
def simulate_sweep() -> tuple[Response, int]:
    """Submit a parameter sweep for background execution.

    Generates a set of sweep points (linear or geometric) and submits one
    background home-simulation job per point.  Returns the rounded sweep
    values and the ids of the submitted jobs.

    Expects a JSON object whose fields are all optional, so ``{}`` runs the default sweep:
      - parameter: str, a key of _SWEEP_PARAMETER_HOME_KEYS (default "pv_capacity_kw")
      - min: finite number (default 1.0)
      - max: finite number (default 10.0)
      - steps: whole number, 2 to SWEEP_MAX_STEPS (default 5)
      - mode: "linear" | "geometric"
      - base_config: JSON object (optional, default {}), the home config
        every sweep point starts from.  A window it sends is read as
        parse_home_config reads a home's; one that sends none, as
        with_default_days reads a body, runs _SWEEP_DEFAULT_DAYS days.

    Returns:
        JSON with parameter, values and job_ids, HTTP 201.
        HTTP 400 for an unsupported parameter (the error lists the supported
        ones), a min, max or steps it cannot use, or a steps outside 2 to
        SWEEP_MAX_STEPS (the error names the field and the value sent), an
        invalid range, a min and max too far apart for the sweep's points to
        be computed (the error names both), a base_config that is not a JSON
        object (the error names the type sent), or a point whose home config
        is invalid, a window parse_home_config refuses included.
        Every 400 comes before any job is submitted.
    """
    data = request_json_object()
    parameter = str(data.get("parameter", "pv_capacity_kw"))
    home_config_key = _SWEEP_PARAMETER_HOME_KEYS.get(parameter)
    if home_config_key is None:
        supported = ", ".join(_SWEEP_PARAMETER_HOME_KEYS)
        return jsonify({
            "error": f"Unsupported sweep parameter {parameter!r}; supported parameters: {supported}",
        }), 400
    try:
        min_val = as_finite_float(data.get("min", 1.0), "min")
        max_val = as_finite_float(data.get("max", 10.0), "max")
        steps = as_whole_number(data.get("steps", 5), "steps", within=Interval(2, SWEEP_MAX_STEPS))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    if min_val >= max_val:
        return jsonify({"error": "Min must be less than max"}), 400
    mode = str(data.get("mode", "linear"))
    base_config = require_json_object(data.get("base_config", {}), "base_config")

    # Generate sweep points
    if mode == "geometric":
        if min_val <= 0:
            return jsonify({"error": "Min must be positive for geometric sweep"}), 400
        ratio = max_val / min_val
        values = [min_val * ratio ** (i / (steps - 1)) for i in range(steps)]
    else:
        values = [min_val + (max_val - min_val) * i / (steps - 1) for i in range(steps)]
    if not all(math.isfinite(v) for v in values):
        return jsonify({
            "error": (
                f"min {min_val!r} and max {max_val!r} are too far apart to sweep:"
                " computing the points between them overflows a float"
            ),
        }), 400

    rounded_values = [round(v, 3) for v in values]

    # Build every point's home before any job is submitted
    point_base_config = with_default_days(base_config, _SWEEP_DEFAULT_DAYS)
    point_homes: list[tuple[float, HomeConfig, pd.Timestamp, pd.Timestamp]] = []
    for val in rounded_values:
        point_config = {**point_base_config, home_config_key: val}
        try:
            home_config, start_date, end_date, _ = parse_home_config(point_config)
        except (ValueError, TypeError) as exc:
            return jsonify({"error": f"Invalid config for {parameter}={val}: {exc}"}), 400
        point_homes.append((val, home_config, start_date, end_date))

    # Submit one home job per sweep point
    job_manager = get_job_manager()

    job_ids: list[str] = []
    for val, home_config, start_date, end_date in point_homes:
        job_id, _ = job_manager.submit_home_job(
            config=home_config,
            start_date=start_date,
            end_date=end_date,
            name=f"Sweep {parameter}={val}",
        )
        job_ids.append(job_id)

    return jsonify({
        "parameter": parameter,
        "values": rounded_values,
        "job_ids": job_ids,
    }), 201


# ---------------------------------------------------------------------------
# History API endpoints (consolidated from history.py)
# ---------------------------------------------------------------------------


@api_bp.route("/history/runs")
def history_list_runs() -> Response | tuple[Response, int]:
    """One page of the run list, filtered and sorted as the query parameters ask.

    Query parameters, each optional:
        page: The page, numbered from 1 (default 1).
        per_page: The runs a page lists, from 1 to 100 (default 20).
        sort: The column the runs are sorted by, one of RUN_SORTS (default 'created_at').
        order: 'asc' or 'desc' (default 'desc').
        type: Keep only the runs of this type, one of RUN_TYPES.
        q: Keep only the runs whose name or notes hold this text, in any ASCII case.
        date_from: Keep only the runs created on or after this date, YYYY-MM-DD.
        date_to: Keep only the runs created on or before this date, YYYY-MM-DD.
    A filter sent empty keeps every run.

    Returns:
        JSON with ``runs``, the row _history_row answers for each run on the page, and
        ``pagination``. HTTP 400 with the refusal as ``error`` when a value is not one the run
        list answers: a page below 1, a per_page outside 1 to 100, a page or per_page that is
        not a whole number, a sort, order or type that is none of its options, or a date_from
        or date_to that is not a date.
    """
    try:
        query = _run_query_from(request.args)
    except ValueError as refusal:
        return jsonify({"error": str(refusal)}), 400
    page = get_storage().page_runs(query)
    return jsonify({
        "runs": [_history_row(record) for record in page.records],
        "pagination": _pagination(query, page.total),
    })


def _run_query_from(args: Mapping[str, str]) -> RunQuery:
    """The page of the run list the History list's query parameters *args* ask for, as history_list_runs reads them.

    Raises:
        ValueError: A parameter's value is not one the run list answers; the message names the
            parameter and the value sent.
    """
    run_type = args.get("type")
    return RunQuery(
        run_type=one_of(run_type, RUN_TYPES, "type") if run_type else None,
        text=args.get("q") or None,
        created_from=_date_parameter(args, "date_from"),
        created_to=_date_parameter(args, "date_to"),
        sort=one_of(args.get("sort", "created_at"), RUN_SORTS, "sort"),
        descending=one_of(args.get("order", "desc"), ("asc", "desc"), "order") == "desc",
        page=as_whole_number(args.get("page", 1), "page"),
        per_page=as_whole_number(args.get("per_page", 20), "per_page"),
    )


def _date_parameter(args: Mapping[str, str], name: str) -> date | None:
    """The date the query parameter *name* of *args* sends as YYYY-MM-DD; None when it is not sent or sent empty.

    Raises:
        ValueError: The value sent is not a date; the message names *name* and the value.
    """
    value = args.get(name)
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as refusal:
        raise ValueError(f"{name} is {value!r}, not a date in the form YYYY-MM-DD") from refusal


def _history_row(record: RunRecord) -> dict[str, Any]:
    """The History list's row for *record*'s run: its columns but its documents and error, its headline_figures, unreadable among them, and its results page's path."""
    return {
        "id": record.id,
        "name": record.name,
        "type": record.type,
        "status": record.status,
        "created_at": record.created_at,
        "completed_at": record.completed_at,
        "duration_seconds": record.duration_seconds,
        "n_homes": record.n_homes,
        "notes": record.notes,
        **headline_figures(record),
        "results_url": url_for("main.run_results", run_id=record.id),
    }


def _pagination(query: RunQuery, total: int) -> dict[str, int | bool]:
    """Where *query*'s page sits among the pages of the *total* runs it keeps, at least one page however few runs there are."""
    total_pages = max(1, math.ceil(total / query.per_page))
    return {
        "page": query.page,
        "per_page": query.per_page,
        "total": total,
        "total_pages": total_pages,
        "has_next": query.page < total_pages,
        "has_prev": query.page > 1,
    }


@api_bp.route("/history/runs/<run_id>")
def history_get_run(run_id: str) -> Response | tuple[Response, int]:
    """A run's detail: each column of its row, with its summary and its homes read through its kind.

    Args:
        run_id: Unique run identifier.

    Returns:
        JSON of each column of the run's row, plus, once the run has them, ``summary``, its
        summary's field tree, and ``home_configs``, the HomeConfig field tree of each of its
        homes, in order. 404 if no run has the id; 409 {error, run_id, document, field} if its
        summary or its config cannot be read, as the blueprint answers a StoredRunUnreadable,
        the document being runs.summary_json or runs.config_json.
    """
    run = get_storage().run_record(run_id)

    if run is None:
        return jsonify({"error": "Run not found"}), 404

    summary = run.summary()
    homes = run.home_configs()

    detail = asdict(run)
    if summary is not None:
        detail["summary"] = asdict(summary)
    if homes is not None:
        detail["home_configs"] = [asdict(home) for home in homes]
    return jsonify(detail)


@api_bp.route("/history/runs/<run_id>", methods=["DELETE"])
def history_delete_run(run_id: str) -> Response | tuple[Response, int]:
    """Delete a run and its associated files, cancelling the run's queued or running job first.

    The job then cannot write the run back (contract C8, docs/prds/run-store-one-owner.md §3.7).

    Args:
        run_id: Unique run identifier.

    Returns:
        JSON success response, or 404 if not found.
    """
    storage = get_storage()
    if storage.run_record(run_id) is None:
        return jsonify({"error": "Run not found"}), 404

    get_job_manager().cancel_run(run_id)
    storage.delete_run(run_id)
    return jsonify({"success": True, "message": f"Run {run_id} deleted"})


@api_bp.route("/history/runs/<run_id>", methods=["PATCH"])
def history_patch_run(run_id: str) -> Response | tuple[Response, int]:
    """Update a run's name and/or notes.

    Expects a JSON body with optional ``name`` and ``notes`` fields.

    Args:
        run_id: Unique run identifier.

    Returns:
        JSON response with updated run data, or 404 if not found. 400 with the refusal as
        ``error``, naming ``name``, for a null or blank name, which update_run_labels refuses.
    """
    data = request_json_object()
    storage = get_storage()

    if storage.run_record(run_id) is None:
        return jsonify({"error": "Run not found"}), 404

    labels = {label: data[label] for label in RUN_LABELS if label in data}
    if not labels:
        return jsonify({"error": "No fields to update"}), 400

    try:
        updated = storage.update_run_labels(run_id, labels)
    except ValueError as refusal:
        return jsonify({"error": str(refusal)}), 400
    if updated is None:
        return jsonify({"error": "Run not found"}), 404

    return jsonify(asdict(updated))


@api_bp.route("/history/runs/<run_id>/export/csv")
def history_export_csv(run_id: str) -> Response | tuple[Response, int]:
    """Export run results as CSV download.

    Args:
        run_id: Unique run identifier.

    Returns:
        CSV file response, or 404 if not found; 409 {error, run_id, document, field} if a file of
        the run cannot be read, as the blueprint answers a StoredRunUnreadable.
    """
    storage = get_storage()
    run = storage.run_record(run_id)

    if run is None:
        return jsonify({"error": "Run not found"}), 404

    run_name = run.name or "run"

    try:
        df = storage.load_run(run_id).export_frame()
    except FileNotFoundError:
        return jsonify({"error": "Run data files not found"}), 404

    csv_data = df.to_csv()
    safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in run_name)
    filename = f"{safe_name}_{run_id[:8]}.csv"

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@api_bp.route("/history/runs/<run_id>/export/yaml")
def history_export_yaml(run_id: str) -> Response | tuple[Response, int]:
    """Export a run's config as the scenario YAML that `home run` or load_fleet_config reads back.

    The run's kind builds the scenario from the config the run's record holds, so the export
    reads none of the run's files.

    Args:
        run_id: Unique run identifier.

    Returns:
        YAML file response; 404 if the run or its config is missing; 409 {error, run_id,
        document, field} if its record names no run kind or its config cannot be read, as the
        blueprint answers a StoredRunUnreadable; 422 if the scenario grammar cannot express it.
    """
    run = get_storage().run_record(run_id)

    if run is None:
        return jsonify({"error": "Run not found"}), 404

    homes = run.home_configs()
    if homes is None:
        return jsonify({"error": "No config data available"}), 404

    run_name = run.name or "run"
    try:
        document = run.kind.scenario_document(homes, run_name)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 422

    safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in run_name)
    filename = f"{safe_name}_{run_id[:8]}.yaml"

    return Response(
        scenario_yaml(document),
        mimetype="text/yaml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Scenarios API endpoints (consolidated from scenarios.py)
# ---------------------------------------------------------------------------


@api_bp.route("/scenarios/preview-yaml", methods=["POST"])
def scenarios_preview_yaml() -> tuple[Response, int]:
    """The YAML text of the fleet scenario a builder form describes.

    Expects a JSON body with the scenario builder's form fields.

    Returns:
        JSON with the ``yaml`` text, HTTP 200; or the ``error``, HTTP 400, for a
        form the builder does not send.
    """
    data = request_json_object()
    try:
        document = scenario_from_builder_form(data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"yaml": scenario_yaml(document)}), 200


@api_bp.route("/scenarios/validate", methods=["POST"])
def scenarios_validate_scenario() -> tuple[Response, int]:
    """Validate a builder form against the dashboard's limits and the scenario readers.

    Expects a JSON body with the scenario builder's form fields.

    Returns:
        JSON with ``valid`` and the ``errors`` list, empty for a valid form, HTTP 200.
    """
    data = request_json_object()
    errors = builder_form_errors(data)
    return jsonify({"valid": not errors, "errors": errors}), 200


@api_bp.route("/scenarios/save", methods=["POST"])
def scenarios_save_scenario() -> tuple[Response, int]:
    """Save a scenario configuration as a fleet preset.

    Expects a JSON body with at least ``name`` and ``config`` fields.

    Returns:
        JSON confirmation with preset name and id, HTTP 201 on success; or the ``error``:
        HTTP 400 for an empty name, HTTP 409 for a name a saved home preset holds.
    """
    data = request_json_object()
    name = str(data.get("name", "")).strip()
    if not name:
        return jsonify({"error": "Scenario name is required"}), 400
    config_payload = data.get("config", {})
    if not config_payload:
        # Accept flat form data as config
        config_payload = {k: v for k, v in data.items() if k not in ("name", "type")}
    return _answer_preset_save(name, "fleet", config_payload)


@api_bp.route("/scenarios/presets", methods=["GET"])
def scenarios_list_presets() -> tuple[Response, int]:
    """List the built-in scenario files, then the saved fleet presets, each by name.

    When the database cannot be read, the built-in files are listed alone and
    saved_fleet_presets logs the fault.

    Returns:
        JSON with the ``presets`` array, HTTP 200.
    """
    presets: list[dict[str, Any]] = [
        {"name": name, "source": "builtin", "filename": path.name}
        for name, path in builtin_scenario_files().items()
    ]
    presets.extend(saved_fleet_presets(get_database()))
    return jsonify({"presets": presets}), 200


@api_bp.route("/scenarios/presets/<name>", methods=["GET"])
def scenarios_get_preset(name: str) -> tuple[Response, int]:
    """Get the built-in scenario file named *name*, else the saved fleet preset named *name*.

    Args:
        name: The preset name to look up.

    Returns:
        JSON preset object, HTTP 200; or the ``error``: HTTP 404 when neither is named *name*,
        so a saved home preset's name is not found; HTTP 500 for a built-in file that does not
        parse; HTTP 500, with the fault logged, for a saved preset that cannot be read.
    """
    # Try built-in scenarios directory
    path = builtin_scenario_files().get(name)
    if path is not None:
        try:
            content = _yaml.safe_load(path.read_text())
            return jsonify({
                "name": name,
                "source": "builtin",
                "config": content,
            }), 200
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": f"Failed to parse {path.name}: {exc}"}), 500
    preset = saved_fleet_preset_named(get_database(), name)
    if preset is None:
        return jsonify({"error": f"Preset '{name}' not found"}), 404
    return jsonify(preset), 200