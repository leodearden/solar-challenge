# PRD — Assistant facts from the engine (review-all stream S22)

- **Program:** `plans/review-all-program-solar_challenge-20261014.md`, stream S22 (agent mode, size S, risk low, wave 1, no upstream stream deps). Findings record: `plans/review-all-solar_challenge-20261013.json`.
- **Finding keys (this stream acts on these and no others):** fk-194e5b40da23 (medium, structural), fk-93d3bd7aa219 (low, mechanical), fk-ab16fff6f6c3 (medium, mechanical).
- **Seam owned (program §Seam ownership):** benchmark constants. Their code homes are `load.py` and `validation.py`, and `web/assistant.py` reads them. Every other stream reads them and does not redefine them.
- **Code anchors** verified against main `ac1fdf1` (2026-10-17). The review pinned `7dfea36e`. Since then `web/assistant.py` has changed by +334/−193 lines (task 713's split and task 701's persistence fix), and `load.py`, `validation.py` and `pv.py` have changed too. Every statement below was re-read at `ac1fdf1`. Cite code by symbol and re-locate line numbers when implementing.
- **Quality definition:** `/home/leo/src/dark-factory/docs/code-quality.md`. Heuristics are cited by name.
- **Amendment (2026-10-25, task 1134):** the B3 guard is no longer slow. It reads Bristol's TMY from the weather-cache entry committed under `tests/fixtures/weather_cache`, PVGIS's v5_3 TMY as `PvgisTmy` caches it. So it runs offline in the per-task verify and fails a model change before it merges, whereas as a slow test nothing ran it. §5.4's yield row, §6 decision 3, §7's G3 bullet on the guard and §9 B3 are read as amended. The capability manifest's rows on the slow guard are authoring-time evidence, kept as history.

## 1. Goal

The assistant tells a user what this simulator's engine says, not a second, contradicting copy of it.

- When a user asks the dashboard's assistant about typical consumption, self-consumption or PV yield, the answer and the `suggest_config` sizing come from the constants the engine itself uses:
  - consumption from `load.OFGEM_TDCV_BY_OCCUPANTS`;
  - self-consumption and yield bands from `validation`'s band constants;
  - the default system's Bristol yield from one measured constant.
- Each tool the model can call is declared once, as a record that holds its schema, how it reads its input, and its handler. `dispatch_tool` becomes a lookup. A malformed tool input comes back to the model as an `{"error": ...}` result naming the field. It never ends the user's reply with a streaming error, and it never becomes a silent default.

## 2. Background

### 2.1 What exists today (measured at `ac1fdf1`)

**fk-194e5b40da23: the "grounded" facts contradict each other and the engine.** The comment above `METRIC_TABLE` says `explain_metric` answers from the table "so the model quotes these benchmark numbers instead of hallucinating them". The table and the system prompt hold three different TDCV sets:
- `SIMULATOR_SYSTEM_PROMPT`: "2,900 kWh (Ofgem TDCV low), 3,100 kWh (medium), 4,200 kWh (high)".
- `METRIC_TABLE["annual_consumption"]`: "low 1,900, medium 2,900, high 4,200".
- `METRIC_TABLE["grid_import"]`: "Ofgem TDCV benchmarks: low 1,900, medium 2,700, high 4,100 (net of solar …)". This is a consumption benchmark presented as an import band.
- The `suggest_config` schema adds a fourth TDCV claim: "e.g. 3100 for an Ofgem medium user".

The engine's table is `load.OFGEM_TDCV_BY_OCCUPANTS`: {1: 1800, 2: 2700, 3: 3200, 4: 3900, 5: 4500}. `LoadConfig.get_annual_consumption` derives a household's default from it. S14 δ (task 818) corrects its comment: the table is the project's own interpolation by occupants, not Ofgem's low/medium/high values.

The bands disagree as well:
- **Self-consumption.** The assistant says 30–40 % without storage and 55–70 % with a battery. `validation.validate_self_consumption_pv_only` and `_with_battery` apply the inline literals 20.0–45.0 and 50.0–90.0, and their docstrings say ~25–35 % and ~60–80 %.
- **Yield.** The assistant says "Bristol typically 900–970 kWh/kWp/yr". `suggest_config` sizes PV at `_UK_YIELD_KWH_PER_KWP = 950.0`. The engine's measured Bristol figure for its default 4 kW system is 993.1 kWh per wired kWp today (`docs/pv-annual-yield-benchmark.md`, `scripts/measure_pv_performance_ratio.py`). After S14 ε (task 823, NOCT-SAM) it will be 1012.1.
- **Effect.** The probe `suggest_config(3100, "bill_savings")` returns 3.26 kWp (3100 / 950). With the engine's post-ε figure it would be 3.06 kWp. The assistant tells a user that the engine's default result is above typical for Bristol, and it sizes PV against a yield the model it then runs does not produce.

**fk-93d3bd7aa219: each tool's name lives in three places.**
1. The `TOOLS` tuple of schema dicts.
2. `dispatch_tool`'s six-branch `if name == …` chain (cognitive complexity 11, complexipy 8.0.1).
3. The literal name list in `tests/unit/web_assistant/test_tool_use.py::TestToolSurface::test_tools_fixed_order_for_cache_stability`.

Each branch coerces its input its own way: `str(...)`, `float(...)` or `int(...)`, each with a silent default. Probes of `dispatch_tool`, whose docstring says "Never raises", at `ac1fdf1`:

| Call | Today |
|---|---|
| `suggest_config` with `annual_consumption_kwh` 10**400 | raises `OverflowError` |
| `list_recent_runs` with `limit` inf | raises `OverflowError` |
| `run_fleet_simulation` with `n_homes` inf | raises `OverflowError` |
| `suggest_config` with no `annual_consumption_kwh` (the schema requires it) | recommends 0.0 kWp and 0.0 kWh |
| `suggest_config` with −5 | recommends −0.01 kWp |
| `suggest_config` with `true` | recommends 0.0 kWp |
| `explain_metric` with no `metric` | answers "Metric '' is not recognised" |

In a chat, an `OverflowError` escapes `_reply_events` and ends the turn with an `error` frame "Streaming error: …". The model never sees a tool result it could correct.

**fk-ab16fff6f6c3: closed by task 713, no leaf.**
- Task 713 (done, merged `ddbeb5b`) split `chat()` into named steps:
  - `request_messages` / `_replay_window`, a pure function;
  - `_reply_events` / `_model_call` / `_tool_results`, the typed reply events;
  - `_ReplyRecord`, the immutable accumulator;
  - `_TurnRecorder`, the one persistence step: `store_user_message`, then `store_reply` once, in a `finally`;
  - `_turn_frames` and `_sse_frames`, the framing;
  - the route `chat`.
- Re-measured at `ac1fdf1` with complexipy: `chat` scores 3, down from 47. `_turn_frames` scores 2, `_reply_events` 3 and `_TurnRecorder.store_reply` 3.
- There is one `save_chat_message` site for each row kind. The reply row is never empty: `store_reply` stores `_TurnEnding.stand_in` when no text streamed, and `_replay_window` drops empty rows already stored.
- Task 701 (done, `5e5358c`) fixed the GeneratorExit and empty-row defects that the stream row's "refuses an empty assistant row" alludes to.
- Every element of the stream row's chat remedy is on main, as are its deletable "two of three save sites". The contract's §8 step 1c re-verification finds the finding absent, so nothing is filed for this key.

### 2.2 Already-filed tasks (contract §8 step 1 at `ac1fdf1`)

The read-only `json_each(metadata, '$.x_finding_key')` lookup over `.taskmaster/tasks/tasks.db` finds:

| key | task | status | disposition |
|---|---|---|---|
| fk-194e5b40da23 | none | — | filed by this PRD as α |
| fk-93d3bd7aa219 | 751 | pending (low, no deps) | 751 **is** leaf β: re-scoped in place by `update_task` at decompose, not duplicated |
| fk-ab16fff6f6c3 | 713 | done | closed (§2.1); no filing |

Other live tasks that edit `web/assistant.py`. None of them carries these keys:
- **440** (pending, low): assistant `OverflowError` in three branches, plus the sweep endpoint's.
- **506** (pending, low; depends on 440): `suggest_config` sizes non-positive or absent consumption.
- **761**: the capped model call's tools still run.
- **765**: bare "PRD §n" pointers.
- **770**: trigger-tool descriptions restate defaults.
- **S19 leaves 805, 806, 814, 816, 817 and 822**: the run-store handlers and `dispatch_tool`'s injected collaborators.

§6 decision 5 says how β treats 440 and 506. The rest are file overlap only.

## 3. Rulings that bind, and how this PRD reads them

- **D26** accepts S22 as the synthesis wrote it.
- **D2** makes `ConfigurationError` subclass `ValueError` (task 774, pending; `errors.py` on main still subclasses `Exception`). S4's conversion of the shared readers depends on 774, so β's one `except ValueError` catches the readers' refusals before S4 converts them and after.
- **D4 / D29:** nothing here touches the frozen surface. `OFGEM_TDCV_BY_OCCUPANTS` is frozen and only read. The new `validation` constant and every `web.assistant` name are not on `FROZEN_SURFACE`.
- **Program cross-reference line (from S14's decompose):** "S22 derives its PV facts from 818 and 823."
- **Program cross-reference line (from S19):** 816 replaces `assistant.list_recent_runs`' raw SQL. The S19 PRD's §8 row for S22 says "`dispatch_tool` takes `storage`/`job_manager` (β, γ); S22's handler table keeps that injection".

**Seam-claim reading.** The program's seam row names S22 as owner of the benchmark constants. S14's PRD contract also lists "validation's benchmark constants" among the seams it owns. This PRD reads the two as one split, not a contest:
- S14 δ (task 818) produces the three `validation.UK_*` band constants, with their values and sources.
- S22 owns the seam's rule: the assistant reads them and never restates them.
- S22 also adds the one constant no stream has filed, the Bristol default-system yield (§5.1).

§13 proposes the cross-reference line for the lead.

## 4. Sketch of approach

**Facts are formatted from the engine at import (α).** `SIMULATOR_SYSTEM_PROMPT`, `METRIC_TABLE` and the `suggest_config` schema description stay module-level values, so the prompt-cache prefix stays byte-stable between requests. Their numbers are formatted once from the engine's constants:
- the consumption defaults by occupants, from `OFGEM_TDCV_BY_OCCUPANTS`;
- the PV-only and battery self-consumption bands, from `validation.UK_PV_ONLY_SELF_CONSUMPTION_BENCHMARK_PERCENT` and `UK_BATTERY_SELF_CONSUMPTION_BENCHMARK_PERCENT`;
- the plausible UK yield range, from `validation.UK_YIELD_BENCHMARK_KWH_PER_KWP`;
- the default system's Bristol yield, from a new `validation.BRISTOL_DEFAULT_SYSTEM_YIELD_KWH_PER_KWP`, which `suggest_config` also sizes with.

Bands with no engine counterpart stay as cited external facts, unchanged: self-sufficiency, solar fraction, grid export, battery cycles, and the prompt's system-size bands. The rule is SPOT: a fact the engine holds is read from the engine, and a fact it does not hold keeps its citation.

**One record per tool (β).** A frozen record holds the tool's schema dict and a `run(tool_input, context)` function that reads its inputs, then calls the handler. Reading goes through the shared number readers (`as_finite_float_within`, `as_whole_number`) and one text reader, and a refused input raises `ValueError` naming the field. The table is one tuple of records in the fixed prompt-cache order:
- `TOOLS` is derived from it, a tuple of the schema dicts, so the SDK still gets plain JSON-encodable dicts.
- `dispatch_tool` looks the name up, turns a reader's `ValueError` into `{"error": …}`, and answers an unknown name as today.
- The collaborators the handlers need travel as one frozen `ToolContext`.

Heuristics served: SPOT (11) for the facts and the tool names; no meaningful strings (12) for the name dispatch; invariants enforced uniformly (10) for input refusals; orthogonal dimensions (3), since schema and handler sit in one record.

## 5. Contract

### 5.1 `validation.py` (α adds one constant, beside S14 δ's three)

```python
# after S14 δ (task 818):
UK_YIELD_BENCHMARK_KWH_PER_KWP: tuple[float, float] = (300.0, 1200.0)
UK_PV_ONLY_SELF_CONSUMPTION_BENCHMARK_PERCENT: tuple[float, float]   # sourced: docs/self-consumption-benchmark.md
UK_BATTERY_SELF_CONSUMPTION_BENCHMARK_PERCENT: tuple[float, float]   # sourced: docs/self-consumption-benchmark.md

# α:
BRISTOL_DEFAULT_SYSTEM_YIELD_KWH_PER_KWP: float = <the figure docs/pv-cell-temperature.md records>   # 1012.1 at S14 ε's measurement
"""Annual AC energy per wired kWp of PVConfig.default_4kw() on Bristol's TMY, as
scripts/measure_pv_performance_ratio.py measures it (docs/pv-cell-temperature.md);
tests/integration/test_pv_performance_ratio.py re-measures it."""
```

- **Not a validation band.** No check applies this constant. It is the engine's expected yield for its own default, kept beside the UK band it sits inside, at the code home the program's seam row names. `pv.py` stays the model and caches none of its own outputs.
- **Value.** α copies the figure that ε's `docs/pv-cell-temperature.md` records, and that document gains one line naming the constant as the code's copy of it.
- **Drift guard.** A later re-baseline that moves the measurement fails the slow guard (§9 B3) until the constant moves with it.

### 5.2 `web/assistant.py` facts (α)

The work is in five places:

1. **`SIMULATOR_SYSTEM_PROMPT`.**
   - The "UK reference bands" consumption line becomes the simulator's default annual consumption by household size, formatted from `OFGEM_TDCV_BY_OCCUPANTS`, e.g. "1 occupant 1,800 kWh … 5 occupants 4,500 kWh".
   - The expertise line drops "Ofgem TDCV benchmarks".
   - No text attributes the table to Ofgem, following S14 δ's correction.
   - The PV and battery size bands stay as they are.
2. **`METRIC_TABLE`.**
   - `annual_consumption`: the same by-occupant defaults.
   - `grid_import`: no TDCV restatement. The band says there is no fixed benchmark: import is the demand that PV and battery do not cover, so it is at most the household's annual consumption, whose defaults it names from the same table.
   - `self_consumption_ratio`: the two `UK_*_SELF_CONSUMPTION_*` bands, presented as the UK benchmark the simulator's validation applies.
   - `pv_generation`: the `UK_YIELD_BENCHMARK_KWH_PER_KWP` range, presented as the plausible range the simulator accepts for an unshaded UK array, plus the default system's Bristol figure.
   - The other four entries are unchanged.
   - The table's comment says which entries derive from the engine and that the rest carry their external citation.
3. **`suggest_config`.**
   - It sizes PV with `BRISTOL_DEFAULT_SYSTEM_YIELD_KWH_PER_KWP`, and its note quotes that constant, as it quotes `_UK_YIELD_KWH_PER_KWP` today. `_UK_YIELD_KWH_PER_KWP` is deleted.
   - Its docstring's "/ 950" goes.
   - Its schema's "e.g. 3100 for an Ofgem medium user" becomes the engine's default for `LoadConfig()`'s occupants, formatted from `LoadConfig().get_annual_consumption()` and `LoadConfig().household_occupants`.
4. **Formatting.** Each number is formatted with one helper, so the prompt, the table and the schema render a value identically: kWh with thousands separators, and percentages and kWh/kWp as `g`.
5. **Static derivation.** No fact is computed per request. Every derived string is built at import.

### 5.3 `web/assistant.py` tools (β)

```python
@dataclass(frozen=True)
class ToolContext:
    """What the tools' handlers read and submit to: the app's run store and job manager."""
    # fields are exactly the collaborators dispatch_tool's handlers take on main when β lands:
    # db_path, data_dir and job_manager today; storage and job_manager after S19 β/γ (806, 816)

@dataclass(frozen=True)
class _Tool:
    schema: Mapping[str, Any]                                         # {"name", "description", "input_schema"}, plain dicts
    run: Callable[[Mapping[str, Any], ToolContext], dict[str, Any]]   # reads the input (ValueError naming the field), calls the handler

_TOOL_TABLE: tuple[_Tool, ...]          # fixed order: the prompt-cache prefix
TOOLS: Sequence[Mapping[str, Any]] = tuple(tool.schema for tool in _TOOL_TABLE)
_TOOL_BY_NAME: Mapping[str, _Tool]      # MappingProxyType; construction refuses a duplicate name

def dispatch_tool(name: str, tool_input: Mapping[str, Any], context: ToolContext) -> dict[str, Any]:
    # unknown name -> {"error": "Unknown tool '<name>'. Available tools: <names in order>."} (unchanged text)
    # a reader's ValueError -> {"error": str(error)}; handlers keep returning their own error dicts
```

**Input reading rules,** one per field kind, applied in each tool's `run`:

| field | rule | today |
|---|---|---|
| a required field the schema lists | absent → refused naming it ("<field> is required") | silent default |
| text (`metric`, `goal`, `run_id_or_name`) | must be a `str` | `str(value)` |
| `annual_consumption_kwh` | `as_finite_float_within(…, *FLEET_COMPONENTS["load"].fixed_range)`, the range `run_home_simulation`'s `consumption_kwh` already accepts (500–20,000) | `float()`, 0.0 default |
| `limit` | `as_whole_number`; the handler's documented clamp (≤ 0 → 10, ≤ 50) stays the handler's | `int()`, 10 on error |
| `n_homes` | `as_whole_number`; the handler's documented clamp to 1–100 stays, read from one named constant that the schema description also formats | `int()`, 1 on error |
| the trigger tools' per-home fields | passed whole to `simulation_params.parse_home_config`, as today | unchanged |

- **Error type.** Refusals use the shared readers' `ValueError` (a `ConfigurationError` after S4, which is a `ValueError` under D2). β imports the readers from wherever main holds them: `web/number_fields.py` today, or the package leaf after S4 moves it.
- **Wiring.** `_answer_frames` builds one `ToolContext` and passes `partial(dispatch_tool, context=context)` as the `_ToolRunner`.
- **Tests.** The literal name list in `test_tools_fixed_order_for_cache_stability` gives way to structural checks: `TOOLS` is a tuple derived from the table, its names are unique, and every name dispatches to a record.

### 5.4 Invariants and where each is enforced

| invariant | construction | use |
|---|---|---|
| A fact the engine holds is read from the engine. | the module-level strings format the constants at import | α's test compares the strings with the constants; grep-absent delivered checks for the deleted literals |
| The Bristol yield constant is the measured figure. | `validation.BRISTOL_DEFAULT_SYSTEM_YIELD_KWH_PER_KWP` | the slow guard re-measures it (B3) |
| Every schema has exactly one handler, and the reverse. | one `_Tool` record holds both; `_TOOL_BY_NAME`'s construction refuses a duplicate | `dispatch_tool` is a lookup |
| A malformed tool input reaches the model as an error naming the field. | the per-kind readers | `dispatch_tool`'s one `except ValueError` |

## 6. Resolved design decisions

1. **The Bristol yield is a code constant, not a read of a document.** S14's PRD says S22 reads the figure from `docs/pv-cell-temperature.md`. Parsing a markdown figure at runtime would be an ad-hoc parser (heuristic 12), and the assistant would depend on a document file. The document stays the dated record of the measurement. The code holds one constant that names the document, and the slow guard binds the two.
2. **The constant lives in `validation.py`.** That is the program seam row's code home, beside the UK yield band. Not in `pv.py`: the model does not cache its own outputs. Not in `web/assistant.py`: a fact about the engine belongs to the engine, and other readers may want it.
3. **The guard is the existing slow test.** It goes in `tests/integration/test_pv_performance_ratio.py`, which already measures `site.with_losses` for Bristol with the same script. The tolerance is `rel=0.01`. That is test_pvgis's own tolerance on the TMY's annual GHI, a PVGIS drift the constant should not be failed for, and it still catches a model change the size of ε's +1.9 %. Adding it to the `pvgis` lane job was considered and rejected: that job's contract is "PVGIS's or pvlib's response changed", and a model re-baseline failing there would mislead the fix-task triage the lane's documentation prescribes. **[Amended 2026-10-25, task 1134: the guard reads the committed TMY in the per-task verify (header amendment), so no PVGIS drift reaches it, and the first basis for `rel=0.01` is gone. `rel=0.01` stays: it still catches a change the size of ε's +1.9 %, while a bound near the measurement's rounding floor would fail every PV-model change that moves the yield by a fraction of a percent, and every upstream release that does so in the newest-releases lane. The `pvgis` job still does not run the guard.]**
4. **The assistant states the simulator's own consumption defaults by occupants, and no low/medium/high TDCV.** The engine holds no Ofgem low/medium/high values (S14 δ corrects the comment that implied it). Quoting Ofgem's published values would need a new sourced constant that nothing in the engine reads, an orphan fact. `grid_import` stops posing as a TDCV band.
5. **β reads every input through shared readers, so it absorbs task 506 and the assistant half of task 440.**
   - The finding names the ad hoc coercion "with silent defaults". The coercions 440 and 506 probe are those defaults.
   - Landing 440 and 506 first, then β, would rewrite the same branches twice.
   - Decompose cancels 506 with `x_superseded_by` 751. The lead narrows 440 to the sweep endpoint (`api.simulate_sweep`) by `update_task`, removing its item 3.
   - β decides 506's open point: 0 and negative consumption are refused, because the range is the dashboard's 500–20,000.
6. **The handlers' clamps stay. Only the silent defaults on garbage go.** `limit`'s clamp is documented in the schema, and `n_homes` is clamped to 1–100 "to protect the single-worker JobManager". Both are documented behaviours, and `list_recent_runs`' internals are S19 γ's (816, `RunQuery`). β refuses what the readers refuse (bool, non-finite, fraction, non-numeric, absent-but-required) and leaves range policy to the handlers.
7. **There is one `ToolContext` value, not keyword collaborators.**
   - Its fields follow main's injection when β lands, so β and S19 β/γ can land in either order: whichever lands second edits the fields, not the dispatch.
   - There is no hard edge between β and the S19 chain, because the structure β adds makes S19's handler edits smaller, not larger.
8. **`TOOLS` stays a tuple of plain dicts.** The SDK JSON-encodes nested schema values as they are, and `TOOLS`' existing comment records that `MappingProxyType` is rejected. The records hold the dicts, and `TOOLS` is derived from them.
9. **External bands stay.** `self_sufficiency`, `solar_fraction`, `grid_export` and `battery_cycles`, and the prompt's system-size bands, have no engine home. Moving them is not this stream's finding. One of them looks inconsistent with the model (§12, triage note).

## 7. Pre-conditions

- **α depends on 818 (S14 δ) and 823 (S14 ε).** 818 creates the three `validation.UK_*` constants and corrects the TDCV comment. 823 measures the post-NOCT-SAM Bristol figure and writes `docs/pv-cell-temperature.md`. Both are pending; 823 depends on 812.
- **β has no prerequisites.** Task 751 is pending with no dependencies. `web/number_fields.py` exists with `as_finite_float_within` and `as_whole_number`. `FLEET_COMPONENTS["load"].fixed_range` is (500, 20000). `tests/unit/web_assistant/_fakes.py`'s `FakeAnthropic` records each `messages.stream` call (`.calls`) and scripts tool-use streams (`make_tool_use_stream`).
- **G3 substrate, verified at `ac1fdf1`:**
  - `load.OFGEM_TDCV_BY_OCCUPANTS` and `LoadConfig.get_annual_consumption` exist; the table is frozen and is only read.
  - `scripts/measure_pv_performance_ratio.measure` returns `with_losses.kwh_per_kwp`.
  - `tests/integration/test_pv_performance_ratio.py` is marked `slow` and `integration` and measures Bristol through `get_tmy_data`.
  - `web/assistant.py` already imports from `solar_challenge.web.*`. The core modules `load` and `validation` import no web or Flask code; `validation` imports `home` and `pv`, and `web/simulation_params` already imports `home`, so α adds no import-time cost the app does not already pay.
  - `tests/unit/test_web_app.py::test_building_the_app_does_not_import_the_anthropic_sdk` is unaffected.
- **Not present yet** (delivered upstream): the three `validation.UK_*` constants (818) and `docs/pv-cell-temperature.md` (823).

## 8. Cross-PRD relationship

| other stream | direction | seam mechanism | owner | status |
|---|---|---|---|---|
| S14 PV model (`docs/prds/pv-model-one-home.md`) | consumes | `validation.UK_*` band constants (δ, 818); the Bristol figure in `docs/pv-cell-temperature.md` (ε, 823) | S14 produces the values; S22 owns the reading rule and the code constant for the figure | α depends on 818 and 823 |
| S19 Run store (`docs/prds/run-store-one-owner.md`) | shares | `dispatch_tool`'s collaborators (806 β), `list_recent_runs`/`get_run_results` bodies (816 γ), `results_url` (814 ε), default names (817 ζ), the strict reader (822 κ) | S19 owns handler bodies and which collaborators; S22 owns the table and `ToolContext`'s shape | no edge; whichever lands second follows the other (§6.7) |
| S4 Finite quantities (`docs/prds/finite-quantities.md`) | consumes | the shared number readers, moved to the package leaf; their refusal becomes `ConfigurationError` (a `ValueError`) | S4 | no edge; β imports them from main's location |
| S20 SSE framing | shares | `_sse_frame`/`_event_stream` leave `assistant.py` for one web module | S20 | file overlap only; α and β touch neither |
| S12 / S13 Load | shares | `load.py` (α only reads it) | S12/S13 | none |
| S10 Window, S14 δ | shares | `validation.py` (α adds one constant) | each its own | file overlap only |
| S29 Surface bump | none | no frozen name changes | — | no release line |

There is no reciprocal "the other owns it" pair. The S14 seam-claim overlap is read as a split in §3, and §13 has the line to apply.

## 9. Boundary-test sketch

| # | scenario | preconditions | postconditions | lands with |
|---|---|---|---|---|
| B1 | The model is told the engine's facts | test app with `install_fake_anthropic`; the first scripted stream calls `explain_metric` for `annual_consumption`, then `self_consumption_ratio`, then `pv_generation` (three turns, or one turn with three tool_use blocks); the second stream ends the turn | the `tool_result` content in the second `messages.stream` call contains, for each `OFGEM_TDCV_BY_OCCUPANTS` value, its formatted kWh; both ends of each `UK_*_SELF_CONSUMPTION_*` band; both ends of `UK_YIELD_BENCHMARK_KWH_PER_KWP`; and `BRISTOL_DEFAULT_SYSTEM_YIELD_KWH_PER_KWP`. The first call's system block contains the formatted TDCV values and no "Ofgem" | α |
| B2 | Sizing follows the engine's yield | `dispatch_tool("suggest_config", {"annual_consumption_kwh": 3100, "goal": "bill_savings"}, context)` | `recommended_pv_kwp == round(3100 / BRISTOL_DEFAULT_SYSTEM_YIELD_KWH_PER_KWP, 2)` (3.06 at 1012.1; 3.26 today); the note quotes the constant | α |
| B3 | The constant is the measurement | slow: `measure("Bristol", Location.bristol(), get_tmy_data(...))` | `site.with_losses.kwh_per_kwp == approx(BRISTOL_DEFAULT_SYSTEM_YIELD_KWH_PER_KWP, rel=0.01)` | α |
| B4 | A malformed input comes back as a tool error | `FakeAnthropic` scripted: call 1 calls `run_fleet_simulation` with `n_homes` = inf (and, separately, `suggest_config` with `annual_consumption_kwh` absent, −5, `true` and 10**400, and `list_recent_runs` with `limit` inf); call 2 ends the turn | today: the stream ends with an `error` frame "Streaming error: …" and no second call (inf, 10**400), or the result holds a 0 or negative sizing. After β: a second call is made, its `tool_result` is `{"error": …}` naming the field and the value sent, the stream ends with `done`, and no job is submitted | β |
| B5 | Every tool is declared once | the module | `TOOLS` names equal the table's names in order; names are unique; for every name, `dispatch_tool(name, …)` reaches its record (no "Unknown tool"); an unknown name returns today's error text; `dispatch_tool`'s source holds no `if name ==` | β |

## 10. Decomposition plan

Severity priority: α medium, β low. Neither is high or critical, so no edge goes to trigger-chain gate 772.

**α — The assistant's facts are read from the engine** (new task; fk-194e5b40da23; priority medium)
- **Modules:** `src/solar_challenge/web/assistant.py` (`SIMULATOR_SYSTEM_PROMPT`, `METRIC_TABLE`, `suggest_config` and its schema description); `src/solar_challenge/validation.py` (the one new constant); `tests/integration/test_pv_performance_ratio.py` (B3); `docs/pv-cell-temperature.md` (one line naming the constant); `tests/unit/web_assistant/test_tool_handlers.py`, `tests/unit/web_assistant/test_tool_use.py` (B1, B2).
- **Work:** §5.1, §5.2.
- **Signal (leaf):** B1 through `POST /assistant/chat`: the tool results the model receives carry the engine's constants, and the system block carries the by-occupant defaults and no "Ofgem". Also B2 (3.06 kWp for 3,100 kWh at 1012.1, where today it is 3.26) and B3. `assistant.py` holds none of 2,900 / 3,100 kWh / 4,200 / 1,900 / 4,100 / 30–40 % / 55–70 % / 850–950 / 900–970 / `_UK_YIELD_KWH_PER_KWP` / "Ofgem".
- **Consumer:** the dashboard assistant's users (explain_metric answers, suggest_config sizing, the system prompt); S14's seam (its constants gain their named reader).
- **Prereqs:** 818, 823.

**β — One record per assistant tool; dispatch is a lookup; malformed inputs come back as errors** (task 751 re-scoped by `update_task`; fk-93d3bd7aa219; priority low)
- **Modules:** `src/solar_challenge/web/assistant.py` (`TOOLS`, the records, `ToolContext`, `dispatch_tool`, `_answer_frames`); `tests/unit/web_assistant/test_tool_use.py`; `tests/unit/web_assistant/test_tool_handlers.py`; `tests/unit/web_assistant/_fakes.py` (if a context helper is needed).
- **Work:** §5.3. Supersedes 506. Takes item 3 of 440.
- **Signal (leaf):** B4 through `POST /assistant/chat`: each probe in §2.1's table comes back to the model as a tool error naming the field, and the turn ends `done` (today: "Streaming error" or a 0/negative sizing). Also B5: no `if name ==` chain; the name list lives only in the schemas.
- **Consumer:** the dashboard assistant's users (a malformed call no longer ends their reply); S19's handler leaves (one `ToolContext` to edit); the next tool added (one record).
- **Prereqs:** none.

No integration gate: each leaf's signal is user-observable through the chat route.

**Decompose-time actions:**
- File α new. Update 751 in place as β: description, `prd_path`, `prd_task_label` β, `user_observable_signal`, `consumer_ref` and files. Its `x_finding_key` already holds the key, and `x_finding_run`/`source` are already set.
- Add the edges α → 818 and α → 823.
- Cancel 506 with `metadata.x_superseded_by = 751` after the §8 step-1 re-lookup.
- The lead narrows 440 to the sweep endpoint, removing its item 3.
- No action for fk-ab16fff6f6c3: 713 is done and the finding is absent.

**G7 (advisory, since the project has no `docs/legibility/design-invariants.md`):** screened against dark-factory's trigger shapes.
- **One fact, one home.** α's whole purpose. The document figure and the code constant are bound by the slow guard.
- **No silent fail-soft.** β removes the silent defaults. The handlers' clamps are documented in the schema the model reads.
- **Guards exercise behaviour.** B1 asserts what the model actually receives, not the module's source text. The grep checks only confirm deletions.

No waiver is needed.

## 11. Out of scope

- The external bands (§6.9) and the prompt's PV and battery size bands.
- `templates/simulate/partials/load-config.html`'s "UK average is approximately 3,500 kWh/year (Ofgem TDCV medium)". It is the dashboard form's restatement, not the assistant's (§12 triage note).
- Task 761 (the capped model call's tools), task 770 (defaults restated in trigger-tool descriptions; it depends on 755) and task 765 (PRD pointers). β moves the schemas but keeps their text.
- The handler bodies of `get_run_results`, `list_recent_runs` and the trigger tools (S19).
- SSE framing (S20).
- The chat turn's structure (done by 713).

## 12. Open questions

### Lead-level

None the brief and rulings leave open. §3's seam-claim reading and §6.5's absorption of 506 and 440's item 3 are written as defaults the lead can override through the cross-reference lines.

### Tactical (decide in the leaf)

- The exact wording of each derived band string, and whether `METRIC_TABLE` is built by a small helper or by literal f-strings. Either way, every number comes from the constants.
- Whether the "required" refusal text is "<field> is required" or the readers' style ("<field> must be …, got None"). It must name the field.
- Whether `ToolContext` is built by a test fixture or by a helper in `_fakes.py`.
- The `n_homes` cap constant's name.

### Triage notes (candidate findings for the next run, not filed)

- `METRIC_TABLE["grid_export"]` says a 4 kWp system without storage exports 1,400–1,800 kWh a year. At the engine's ~1,012 kWh/kWp and the assistant's own PV-only self-consumption band, the default system exports roughly 2,400–2,800. This is external-band consistency with the model, not SPOT, and outside fk-194e5b40da23.
- `METRIC_TABLE["battery_cycles"]` defines one cycle as "100 % to 0 % SOC". S28 β (865) makes the engine's unit one usable capacity of discharged energy (`compute_soh`'s docstring). The assistant could point at that once S28 lands.
- `load-config.html`'s "3,500 kWh/year (Ofgem TDCV medium)" restates a TDCV that the engine does not hold.

## 13. Proposed cross-reference lines (for the lead to apply)

- **S14** (from S22): S14 δ produces the three `validation.UK_*` constants. S22 owns the benchmark-constants seam's reading rule and adds `validation.BRISTOL_DEFAULT_SYSTEM_YIELD_KWH_PER_KWP`, whose value is ε's `docs/pv-cell-temperature.md` figure. S22 α depends on 818 and 823. The S14 PRD's "S22 reads the figure from docs/pv-cell-temperature.md" reads as "from the constant that the document names".
- **S19** (from S22): S22 β (task 751) puts the tools' collaborators in one `ToolContext`. Whichever of 751 and 806/816 lands second edits `ToolContext`'s fields and the handler bodies, not dispatch. No edge.
- **S4** (from S22): S22 β reads the assistant's number inputs through the shared readers. When S4 moves `web/number_fields.py` to the package leaf, β's import follows the move, and its `except ValueError` stays correct under D2.
- **Tasks** (from S22): 506 is superseded by 751 (cancel with `x_superseded_by`). 440 is narrowed to `api.simulate_sweep`, and its assistant item moves to 751. 761, 765 and 770 keep their scope (file overlap with 751).
- **FILED row:** fk-ab16fff6f6c3 is closed by task 713 (done, `ddbeb5b`; `chat` complexipy 47 → 3, re-measured at `ac1fdf1`).
