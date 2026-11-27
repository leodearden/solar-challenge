# SPDX-License-Identifier: AGPL-3.0-or-later
"""Flask Blueprint providing JSON API endpoints for background simulations.

Provides REST endpoints for submitting simulation jobs, polling status,
streaming progress via SSE, retrieving results, and consolidated history
and scenarios API endpoints under the /api/ prefix.
"""

import logging
import math
from collections.abc import Mapping
from dataclasses import asdict
from datetime import date
from typing import Any, get_args

from flask import Blueprint, Response, jsonify, request, url_for
from werkzeug.exceptions import InternalServerError

from solar_challenge.config import ScenarioConfig
from solar_challenge.errors import ConfigurationError
from solar_challenge.home import run_window
from solar_challenge.number_fields import as_whole_number
from solar_challenge.scenario_writer import scenario_yaml
from solar_challenge.web.builder_form import (
    builder_form_errors,
    builder_form_from_saved_preset,
    builder_form_from_yaml,
    scenario_from_builder_form,
)
from solar_challenge.web.builtin_scenarios import builtin_scenario_form, builtin_scenarios_loaded_by
from solar_challenge.web.dashboard import get_database, get_job_manager, get_job_stream_policy, get_storage
from solar_challenge.web.field_tree import field_tree
from solar_challenge.web.fleet_components import fleet_component_values
from solar_challenge.web.fleet_scenario import (
    fleet_form_from_yaml,
    parse_fleet_form,
    scenario_from_fleet_form,
)
from solar_challenge.web.presets import (
    PresetNameTaken,
    PresetSource,
    PresetType,
    SavedPresetUnreadable,
    home_preset_named,
    home_presets,
    save_config_preset,
    saved_fleet_preset_named,
    saved_fleet_presets,
)
from solar_challenge.web.request_boundary import (
    answer_refusal,
    answer_server_error,
    read_optional_string,
    read_string,
    request_json_object,
    require_json_object,
)
from solar_challenge.web.run_names import read_run_name
from solar_challenge.web.scenario_import import ImportedForm
from solar_challenge.web.simulation_params import parse_home_config, with_default_days
from solar_challenge.web.sse import event_stream, job_progress_frames, parse_last_event_id
from solar_challenge.web.sweep_request import SweepRequest, read_sweep_request
from solar_challenge.web.storage import RUN_LABELS, RUN_SORTS, RunLabel, RunQuery, RunRecord, headline_figures
from solar_challenge.web.stored_runs import RUN_TYPES, StoredRunUnreadable
from solar_challenge.web.text_options import read_one_of
from solar_challenge.web.unreadable_run_answer import answer_stored_run_unreadable

logger = logging.getLogger(__name__)

api_bp = Blueprint("api", __name__, url_prefix="/api")


# answer_refusal answers a ValueError an endpoint of this blueprint raises, and answer_server_error any other
# exception that no handler below names
api_bp.register_error_handler(ValueError, answer_refusal)
api_bp.register_error_handler(InternalServerError, answer_server_error)


@api_bp.errorhandler(SavedPresetUnreadable)
def _answer_a_saved_preset_that_cannot_be_read(unreadable: SavedPresetUnreadable) -> tuple[Response, int]:
    """Answer HTTP 500 with the error naming a saved preset that cannot be read, logged at ERROR with its traceback.

    Any endpoint of this blueprint that looks a saved preset up is answered this way.
    """
    logger.error("%s", unreadable, exc_info=unreadable)
    return jsonify({"error": str(unreadable)}), 500


# Any endpoint of this blueprint that reads a stored run it cannot read answers 409 (D-S19-9)
api_bp.register_error_handler(StoredRunUnreadable, answer_stored_run_unreadable)


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
    home_config, start_date, end_date, name = parse_home_config(data)
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
    name = read_optional_string(data.get("name"), "name")
    homes_data = data.get("homes", [])
    if not isinstance(homes_data, list):
        return jsonify({"error": f"homes must be a JSON array, got {type(homes_data).__name__}"}), 400
    if not homes_data:
        return jsonify({"error": "Fleet requires at least one home config in 'homes' array"}), 400
    configs = []
    # Use first home's date config for the fleet
    first_config, start_date, end_date, _ = parse_home_config(homes_data[0])
    configs.append(first_config)

    for home_data in homes_data[1:]:
        config, _, _, _ = parse_home_config(home_data)
        configs.append(config)

    job_manager = get_job_manager()

    job_id, run_id = job_manager.submit_fleet_job(
        configs=configs,
        start_date=start_date,
        end_date=end_date,
        name=name,
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
    reports it, under the app's job stream policy. It ends with the job's final state, with
    a timeout once it has been open past the policy's limit, or with untracked when the
    server tracks no such job. A reopened stream resumes after the version its
    Last-Event-ID header names.

    Args:
        job_id: Unique job identifier.

    Returns:
        text/event-stream response.
    """
    job_manager = get_job_manager()
    return event_stream(
        job_progress_frames(
            job_manager,
            job_id,
            last_event_id=parse_last_event_id(request.headers.get("Last-Event-ID")),
            policy=get_job_stream_policy(),
        )
    )


@api_bp.route("/jobs/<job_id>/results", methods=["GET"])
def get_job_results(job_id: str) -> tuple[Response, int]:
    """Return completed job results as JSON.

    Args:
        job_id: Unique job identifier.

    Returns:
        JSON with the job's run's id, name, type and creation time, and as ``summary`` its
        record's RunRecord.summary_tree(); or 404/409 on error. A run whose summary
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

    return jsonify({
        "run_id": run_id,
        "name": run.name,
        "type": run.type,
        "created_at": run.created_at,
        "summary": run.summary_tree(),
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

def _read_preset_name(data: Mapping[str, Any], what: str) -> str:
    """The name a preset save body *data* sends, stripped; *what* names the preset kind in the refusal of a blank name.

    Raises:
        ConfigurationError: From read_string, naming name, for a name that is not a JSON string
            or holds a lone surrogate; "<what> name is required" for a name not sent or blank.
    """
    name = read_string(data.get("name", ""), "name").strip()
    if not name:
        raise ConfigurationError(f"{what} name is required")
    return name


def _answer_preset_save(name: str, preset_type: PresetType, config: Mapping[str, Any]) -> tuple[Response, int]:
    """Save *config* as the *preset_type* preset *name*, a name _read_preset_name has read, answering as both preset save endpoints do.

    Returns:
        JSON with the preset name and id, HTTP 201; or the ``error``: HTTP 409 for a name
        another preset holds, HTTP 500 for a database fault.
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
        HTTP 400, before any database access, for a name that is not a JSON string, a blank
        name, a name holding a lone surrogate or a type other than 'home', HTTP 409 for a
        name a built-in home preset or a saved fleet preset holds.
    """
    data = request_json_object()
    name = _read_preset_name(data, "Preset")
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
    """Preview the homes a fleet form builds, as Run builds them.

    Expects the fleet form POST /api/simulate/fleet-from-distribution takes, read by
    :func:`~solar_challenge.web.fleet_scenario.parse_fleet_form`.

    Returns:
        JSON with ``homes``, the number of homes, and ``values``, each component's value
        of each home in home order (fleet_component_values), HTTP 200 on success; or the
        ``error``, HTTP 400, that parse_fleet_form raises.
    """
    fleet = parse_fleet_form(request_json_object())
    return jsonify({"homes": len(fleet.homes), "values": fleet_component_values(fleet.homes)}), 200

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

    fleet = parse_fleet_form(data)

    job_id, run_id = job_manager.submit_fleet_job(
        configs=list(fleet.homes),
        start_date=fleet.start_date,
        end_date=fleet.end_date,
        name=fleet.name,
    )

    return _submitted_job_answer(job_id, run_id)

@api_bp.route("/fleet/export-yaml", methods=["POST"])
def export_fleet_yaml() -> Response | tuple[Response, int]:
    """Export the fleet page's form as the fleet scenario load_scenario reads back as the homes POST /api/simulate/fleet-from-distribution runs.

    Expects the JSON body the fleet page posts to /api/simulate/fleet-from-distribution.
    Both endpoints read the form with
    :func:`~solar_challenge.web.fleet_scenario.parse_fleet_form`, whose homes are
    config.parse_scenario's reading of the document written here.

    Returns:
        The scenario's YAML file as a download, HTTP 200; or the ``error``, HTTP 400, for a
        form the simulate endpoint refuses, with its message.
    """
    data = request_json_object()
    document = scenario_from_fleet_form(data)
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
        The answer of :func:`_loaded_form_answer`; or the ``error``, HTTP 400, for an
        empty body, YAML that does not parse, or a scenario the fleet page cannot load.
    """
    yaml_text = request.get_data(as_text=True)
    if not yaml_text:
        return jsonify({"error": "Empty request body"}), 400
    imported = fleet_form_from_yaml(yaml_text)
    return _loaded_form_answer(imported)


@api_bp.route("/fleet/presets/<name>", methods=["GET"])
def fleet_preset(name: str) -> tuple[Response, int]:
    """Load the built-in scenario file *name* as the fleet page's form.

    Returns:
        The answer of :func:`_loaded_form_answer` for the preset's form; or the
        ``error``: HTTP 400 for a built-in scenario file the fleet form cannot load, which
        the Load Preset menu does not offer
        (:func:`~solar_challenge.web.builtin_scenarios.builtin_scenarios_loaded_by`); HTTP 404 when no
        built-in scenario file is named *name*.
    """
    imported = builtin_scenario_form(name, fleet_form_from_yaml)
    if imported is None:
        return jsonify({"error": f"Preset '{name}' not found"}), 404
    return _loaded_form_answer(imported)


def _loaded_form_answer(imported: ImportedForm) -> tuple[Response, int]:
    """A page's answer for the form *imported* from a scenario.

    Returns:
        JSON ``{"form", "not_loaded"}``, HTTP 200: the form is the body the page posts, and
        not_loaded the paths of the scenario's settings it has no control for (see
        docs/web-ui-design.md, *Scenario import policy*).
    """
    return jsonify({"form": dict(imported.form), "not_loaded": list(imported.not_loaded)}), 200

# ---------------------------------------------------------------------------
# Parameter sweep endpoint
# ---------------------------------------------------------------------------


#: The days each point of a sweep runs when its base_config sends no window of its own.
_SWEEP_DEFAULT_DAYS = 7


@api_bp.route("/simulate/sweep", methods=["POST"])
def simulate_sweep() -> tuple[Response, int]:
    """Submit a parameter sweep for background execution, one home job per point.

    Expects a JSON object of read_sweep_request's fields (parameter, min, max, steps and
    mode) and base_config, a JSON object read as parse_home_config reads a home, running
    _SWEEP_DEFAULT_DAYS days when it sends no window; each field omitted takes its
    reader's default, so ``{}`` runs the default sweep.

    Returns:
        JSON with parameter, values and job_ids, HTTP 201.
        HTTP 400 for read_sweep_request's refusals, a base_config refusal
        ("base_config: ...") or a point's ("Invalid config for <knob>=<value>: ...");
        every 400 comes before any job is submitted.
    """
    data = request_json_object()
    sweep = read_sweep_request(data)
    base = _sweep_base(require_json_object(data.get("base_config", {}), "base_config"), sweep)
    points = sweep.point_homes(base)
    start_date, end_date = base.simulation_bounds()
    knob = sweep.parameter.knob

    job_manager = get_job_manager()
    job_ids: list[str] = []
    for value, home_config in points:
        job_id, _ = job_manager.submit_home_job(
            config=home_config,
            start_date=start_date,
            end_date=end_date,
            name=f"Sweep {knob.name}={value}",
        )
        job_ids.append(job_id)

    return jsonify({
        "parameter": knob.name,
        "values": [value for value, _ in points],
        "job_ids": job_ids,
    }), 201


def _sweep_base(base_config: Mapping[str, Any], sweep: SweepRequest) -> ScenarioConfig:
    """The single-home scenario every point of *sweep* starts from: *base_config*'s home over its window.

    Raises:
        ConfigurationError: For a base_config parse_home_config refuses, as "base_config: <refusal>".
    """
    try:
        home, start_date, end_date, _ = parse_home_config(with_default_days(base_config, _SWEEP_DEFAULT_DAYS))
    except ConfigurationError as refusal:
        raise ConfigurationError(f"base_config: {refusal}") from refusal
    return ScenarioConfig(
        name=f"Sweep {sweep.parameter.knob.name}",
        period=run_window(home.location, start_date, end_date),
        home=home,
    )


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
    query = _run_query_from(request.args)
    page = get_storage().page_runs(query)
    return jsonify({
        "runs": [_history_row(record) for record in page.records],
        "pagination": _pagination(query, page.total),
    })


def _run_query_from(args: Mapping[str, str]) -> RunQuery:
    """The page of the run list the History list's query parameters *args* ask for, as history_list_runs reads them.

    Raises:
        ConfigurationError: A parameter's value is not one the run list answers; the message
            names the parameter and the value sent.
    """
    run_type = args.get("type")
    return RunQuery(
        run_type=read_one_of(run_type, RUN_TYPES, "type") if run_type else None,
        text=args.get("q") or None,
        created_from=_date_parameter(args, "date_from"),
        created_to=_date_parameter(args, "date_to"),
        sort=read_one_of(args.get("sort", "created_at"), RUN_SORTS, "sort"),
        descending=read_one_of(args.get("order", "desc"), ("asc", "desc"), "order") == "desc",
        page=as_whole_number(args.get("page", 1), "page"),
        per_page=as_whole_number(args.get("per_page", 20), "per_page"),
    )


def _date_parameter(args: Mapping[str, str], name: str) -> date | None:
    """The date the query parameter *name* of *args* sends as YYYY-MM-DD; None when it is not sent or sent empty.

    Raises:
        ConfigurationError: The value sent is not a date; the message names *name* and the value.
    """
    value = args.get(name)
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as refusal:
        raise ConfigurationError(f"{name} is {value!r}, not a date in the form YYYY-MM-DD") from refusal


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
        detail["summary"] = field_tree(summary)
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


def _read_labels(data: Mapping[str, Any]) -> dict[RunLabel, str | None]:
    """The run labels the PATCH body *data* sends, each refused before any is written: a label that read_optional_string refuses, or a name that cannot name a run.

    Raises:
        ConfigurationError: From read_optional_string, naming the label, for a label that is
            neither a JSON string nor null, or holds a lone surrogate; from read_run_name, for
            a null or blank name.
    """
    labels = {label: read_optional_string(data[label], label) for label in RUN_LABELS if label in data}
    if "name" in labels:
        read_run_name(labels["name"])
    return labels


@api_bp.route("/history/runs/<run_id>", methods=["PATCH"])
def history_patch_run(run_id: str) -> Response | tuple[Response, int]:
    """Update a run's name and/or notes.

    Expects a JSON body with optional ``name`` and ``notes`` fields.

    Args:
        run_id: Unique run identifier.

    Returns:
        JSON response with updated run data, or 404 if not found. 400 with the refusal as
        ``error``, naming ``name``, for a null or blank name, which read_run_name refuses;
        and naming the label, for a name or notes that is neither a JSON string nor null, or
        holds a lone surrogate. Each is refused before any label is written.
    """
    data = request_json_object()
    storage = get_storage()

    if storage.run_record(run_id) is None:
        return jsonify({"error": "Run not found"}), 404

    labels = _read_labels(data)
    if not labels:
        return jsonify({"error": "No fields to update"}), 400

    updated = storage.update_run_labels(run_id, labels)
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
    document = scenario_from_builder_form(data)
    return jsonify({"yaml": scenario_yaml(document)}), 200


@api_bp.route("/scenarios/validate", methods=["POST"])
def scenarios_validate_scenario() -> tuple[Response, int]:
    """Validate a builder form against the dashboard's limits and config.parse_scenario.

    Expects a JSON body with the scenario builder's form fields.

    Returns:
        JSON with ``valid`` and the ``errors`` list, empty for a valid form, HTTP 200.
    """
    data = request_json_object()
    errors = builder_form_errors(data)
    return jsonify({"valid": not errors, "errors": errors}), 200


@api_bp.route("/scenarios/save", methods=["POST"])
def scenarios_save_scenario() -> tuple[Response, int]:
    """Save the scenario a builder form describes as a fleet preset.

    Expects a JSON body with a ``name`` and a ``config``, the builder's form, a JSON object; a
    body that sends no ``config`` is itself the config, but for its name and type. The preset
    stored is the scenario document
    :func:`~solar_challenge.web.builder_form.scenario_from_builder_form` builds from the config.

    Returns:
        JSON confirmation with preset name and id, HTTP 201 on success; or HTTP 400, before
        any database access: the ``error`` for a name that is not a JSON string, a blank
        name, a name holding a lone surrogate or a sent config that is not a JSON object,
        and the ``errors`` builder_form_errors lists for a config it refuses; or the
        ``error``, HTTP 409, for a name a saved home preset holds.
    """
    data = request_json_object()
    name = _read_preset_name(data, "Scenario")
    if "config" in data:
        config_payload = require_json_object(data["config"], "config")
    else:
        config_payload = {k: v for k, v in data.items() if k not in ("name", "type")}
    errors = builder_form_errors(config_payload)
    if errors:
        return jsonify({"errors": errors}), 400
    return _answer_preset_save(name, "fleet", scenario_from_builder_form(config_payload))


@api_bp.route("/scenarios/import-yaml", methods=["POST"])
def scenarios_import_yaml() -> tuple[Response, int]:
    """Import a fleet scenario's YAML as the scenario builder's form.

    Accepts the raw YAML text as the request body (Content-Type: text/yaml).

    Returns:
        The answer of :func:`_loaded_form_answer`; or the ``error``, HTTP 400, for an
        empty body, YAML that does not parse, or a scenario the builder cannot load.
    """
    yaml_text = request.get_data(as_text=True)
    if not yaml_text:
        return jsonify({"error": "Empty request body"}), 400
    return _loaded_form_answer(builder_form_from_yaml(yaml_text))


#: The sources of the scenario builder's presets: the built-in scenario files, then the saved fleet presets.
_PRESET_SOURCES: tuple[PresetSource, ...] = get_args(PresetSource)


@api_bp.route("/scenarios/presets", methods=["GET"])
def scenarios_list_presets() -> tuple[Response, int]:
    """List the built-in scenario files the builder loads, then the saved fleet presets, each by name.

    When the database cannot be read, the built-in files are listed alone and
    saved_fleet_presets logs the fault.

    Returns:
        JSON with the ``presets`` array, HTTP 200.
    """
    builtin: PresetSource = "builtin"
    presets: list[dict[str, Any]] = [
        {"name": name, "source": builtin} for name in builtin_scenarios_loaded_by(builder_form_from_yaml)
    ]
    presets.extend(saved_fleet_presets(get_database()))
    return jsonify({"presets": presets}), 200


@api_bp.route("/scenarios/presets/<name>", methods=["GET"])
def scenarios_get_preset(name: str) -> tuple[Response, int]:
    """Load the preset *name* of the ``source`` query parameter, ``builtin`` or ``saved``, as the scenario builder's form.

    A built-in and a saved preset may share a name, so the request names which it wants.

    Returns:
        The answer of :func:`_loaded_form_answer`; or the ``error``: HTTP 400 for a source
        that is neither, a preset the builder cannot load, or a saved preset in the builder's
        former form format; HTTP 404 when no preset of the source is named *name*, so a saved
        home preset's name is not found; HTTP 500, with the fault logged, for a saved preset
        that cannot be read.
    """
    source = read_one_of(request.args.get("source"), _PRESET_SOURCES, "source")
    if source == "builtin":
        imported = builtin_scenario_form(name, builder_form_from_yaml)
    else:
        preset = saved_fleet_preset_named(get_database(), name)
        imported = None if preset is None else builder_form_from_saved_preset(name, preset["config"])
    if imported is None:
        return jsonify({"error": f"Preset '{name}' not found"}), 404
    return _loaded_form_answer(imported)
