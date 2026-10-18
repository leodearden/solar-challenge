# Capability manifest — Assistant facts from the engine (review-all S22)

This manifest mechanizes G3 (the substrate exists) and G6 (the premise is valid) for each leaf of `docs/prds/assistant-facts-from-engine.md`. Each capability a leaf's signal asserts is bound to evidence. The machine-readable twin is `docs/prds/assistant-facts-from-engine.capability-manifest.yaml`.

**Code anchors** were verified against main `ac1fdf1` (2026-10-17). Cite by symbol and re-locate lines when implementing. Probes ran with `uv run --locked --extra dev --extra web python -I` on that tree. complexipy 8.0.1 ran through `uvx --offline`.

**Batch verdict: PASS.** No binding resolves to `declared-only`, `test-only`, `producer-absent`, `producer-downstream`, `producer-extent-short`, `bound≤floor` or `rejection-absent`.
- α's two cross-stream producers, 818 and 823, are upstream prerequisites.
- β has no producer outside itself.
- Each refusal β asserts was observed to be absent today: an `OverflowError` escapes, or a silent default.
- The mechanism that carries a refusal to the model was observed on main: a handler's error dict becomes the `tool_result` content.

## α — The assistant's facts are read from the engine (leaf)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| The contradicting literals exist to delete | grep `web/assistant.py`: "2,900 / 3,100 / 4,200" (system prompt); "1,900 / 2,700 / 4,100" (`grid_import`); "1,900 / 2,900 / 4,200" (`annual_consumption`); "30–40 % / 55–70 %"; "850–950", "900–970"; `_UK_YIELD_KWH_PER_KWP = 950.0`; "Ofgem" ×5, including "e.g. 3100 for an Ofgem medium user" | PASS |
| The engine's consumption table exists and is readable | grep `load.py`: `OFGEM_TDCV_BY_OCCUPANTS: dict[int, float]` {1: 1800 … 5: 4500}; `LoadConfig.get_annual_consumption` reads it; frozen name, read only | PASS |
| The three `validation.UK_*` band constants | producer: task 818 (S14 δ), pending, upstream of α; its delivered checks grep `^UK_PV_ONLY_SELF_CONSUMPTION_BENCHMARK_PERCENT` and `^UK_BATTERY_SELF_CONSUMPTION_BENCHMARK_PERCENT` present, and `_UK_YIELD_BENCHMARK_KWH_PER_KWP` absent (renamed public). Extent: all three constants, which is the full set α reads | PASS (queued prerequisite) |
| The Bristol default-system figure is measured and recorded | producer: task 823 (S14 ε), pending, upstream of α; its delivered check requires `docs/pv-cell-temperature.md`, and its signal records 1012.1 kWh per wired kWp for the default 4 kW | PASS (queued prerequisite) |
| The measurement the slow guard repeats is the figure's own | grep `scripts/measure_pv_performance_ratio.py::measure` returns `SiteMeasurement.with_losses.kwh_per_kwp` (AC kWh / wired kWp); docs/pv-system-losses.md records this script's 993.14 for Bristol today, the figure 823 moves to 1012.1 | PASS |
| The slow guard's home exists and is marked slow | grep `tests/integration/test_pv_performance_ratio.py`: `@pytest.mark.slow`, `@pytest.mark.integration`, `measure("Bristol", bristol, get_tmy_data(bristol))` | PASS |
| B3's tolerance is above the method's floor and below the change it must catch | floor: on a fixed TMY the measurement is deterministic, so a rounding to 0.1 kWh/kWp gives about 0.01 %. Admitted drift: test_pvgis pins the TMY's annual GHI at `approx(1069.5, rel=0.01)`, and yield scales with GHI. Bound: rel 0.01 ≥ that drift, and below ε's measured +1.9 % (×1.0191) | PASS |
| B2's sizing value | computed: 3100 / 1012.1 = 3.0629 → 3.06; today `suggest_config(3100, "bill_savings")` returns 3.26 (probed). The signal asserts the formula against the constant, not the literal | PASS |
| B1: the model receives `explain_metric`'s dict as the `tool_result` | grep `_tool_results`: `json.dumps(result, ensure_ascii=False)` per call; `test_tool_use.py` already asserts the second `messages.stream` call's last user message carries `METRIC_TABLE["self_consumption_ratio"]["uk_benchmark_band"]` through `POST /assistant/chat` | PASS (wired) |
| B1: the system block reaches the model | grep `_model_request`: `"system": [{"type": "text", "text": SIMULATOR_SYSTEM_PROMPT, …}]`; `FakeAnthropic.calls` records each call's kwargs | PASS (wired) |
| Formatting at import keeps the cached prefix stable | `SIMULATOR_SYSTEM_PROMPT`, `METRIC_TABLE` and `TOOLS` are module-level; formatting constants at import yields the same bytes for every request | PASS (by construction) |
| Importing `load` and `validation` from the web module adds no new dependency | grep: `validation.py` imports `pandas`, `battery`, `home`, `pv`, `timebase`; `web/simulation_params.py` already imports `home`, `battery` and `config`, so the app already pays the cost; neither module imports Flask or anthropic | PASS |

## β — One record per assistant tool; dispatch is a lookup; malformed inputs come back as errors (leaf; task 751 re-scoped)

| Capability asserted by signal | Evidence binding | Status |
|---|---|---|
| The six-name if-chain exists to delete | grep `dispatch_tool`: six `if name == "…"` branches; complexipy 11 | PASS |
| The third copy of the names exists | grep `tests/unit/web_assistant/test_tool_use.py::TestToolSurface::test_tools_fixed_order_for_cache_stability`: literal list of the six names | PASS |
| `OverflowError` escapes today (B4's RED) | probe: `dispatch_tool("suggest_config", {"annual_consumption_kwh": 10**400, …})`, `("list_recent_runs", {"limit": inf})`, `("run_fleet_simulation", {"n_homes": inf, "pv_kw": 4})` each RAISES `OverflowError` | PASS (absence observed) |
| Silent defaults today (B4's RED) | probe: `suggest_config` with no `annual_consumption_kwh` → 0.0 kWp / 0.0 kWh; −5 → −0.01 / −0.01; `true` → 0.0 / 0.0; `explain_metric` with no `metric` → "Metric '' is not recognised" | PASS (absence observed) |
| An escaping exception ends the chat turn with an error frame and no second model call | grep `_turn_frames`: `except Exception as error: ending = _failed(error)` → `_error_frame("Streaming error: …")`; `_reply_events` makes the next model call only after `_tool_results` returns | PASS (mechanism observed) |
| A handler's error dict reaches the model, and the turn continues | grep `_tool_results`: every `run_tool` result is JSON-dumped into a `tool_result` block; `_reply_events` then calls the model again | PASS (wired) |
| The shared readers refuse what B4 sends, naming the field | grep `web/number_fields.py`: `as_finite_float` catches `ValueError, TypeError, OverflowError` and refuses a bool or a non-finite value, with the message "{field} must be a finite number, got {value!r}"; `as_finite_float_within` adds the range; `as_whole_number` refuses a fraction | PASS |
| The consumption range has one home | grep `web/fleet_components.py`: `FLEET_COMPONENTS["load"].fixed_range=(500, 20000)`; the `run_home_simulation` schema and `simulation_params.parse_home_config` already read it | PASS |
| `TOOLS` must stay plain dicts | grep: `TOOLS`' comment says "JSON encoding rejects read-only mappings" and `_model_request` passes `"tools": TOOLS` to the SDK | PASS (the constraint the record design keeps) |
| The tool runner seam takes one callable | grep `_answer_frames`: `run_tool = partial(dispatch_tool, db_path=…, job_manager=…, data_dir=…)`, typed `_ToolRunner = Callable[[str, dict], dict]` | PASS |
| `ConfigurationError` stays catchable as `ValueError` after S4 | D2: `ConfigurationError` subclasses `ValueError`. On main, `errors.py` still has `class ConfigurationError(Exception)`; the rebase is producer task 774 (S1 β). S4's conversion of the readers depends on 774 (program cross-reference "S4 depends on 774"). The readers raise a plain `ValueError` today, so β's `except ValueError` is correct in every order the DAG allows | PASS (ordering by DAG) |

## Closed without a leaf — fk-ab16fff6f6c3

| Check | Evidence | Status |
|---|---|---|
| Contract §8 step 1 | lookup finds task 713, `done`, `done_provenance.commit` `ddbeb5b` | 1c: re-verify |
| Re-verification at `ac1fdf1` | complexipy `chat` 3 (47 at `7dfea36e`); `_turn_frames` 2, `_reply_events` 3, `_TurnRecorder.store_reply` 3; one `save_chat_message` per row kind (`store_user_message`, `store_reply` in a `finally`); `store_reply` stores the stand-in when no text streamed | finding absent; no filing |
