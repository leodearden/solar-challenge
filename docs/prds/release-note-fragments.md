# PRD — Release notes since the last tag: one file per task, so note writers stop queueing on one doc

- **Ruling:** Leo, 2026-11-06, sitting item 506 (escalation `esc-__starvation_auto_pin_cap__-3`): take option D now. Option D removes the single-lock hot spot on `docs/domain-library-consumption.md`, and asks the same question of `review/briefing.yaml`.
- **Status:** authored and implemented 2026-11-06 in one interactive session. The restructure (α) lands through the merge queue. The open tasks' retargets and the companion amendments to other PRDs' tasks are fused-memory edits made in the same session (§8).
- **Approach:** B with a short contract (§4) and a boundary-test table (§5). The seam is the note-file layout, which two other streams read: S29's release (task 224) and S23 η's executable check (task 927).
- **Code anchors** verified against main `073da99` (2026-11-06). They cite symbols; re-locate lines at implementation time.

## 1. Goal

A task that changes the public surface, or what a public name returns, writes its release note as its own file, `docs/unreleased/<doc>/<task id>.md`. It no longer edits a shared doc for it. Tasks that only write a note then hold distinct file locks and run side by side, instead of one at a time behind the consumption guide.

What a reader observes:

- **An agent implementing a surface change** is told by the guide's rule, by the surface lock's failure message and by the fleet-pin message to write `docs/unreleased/domain-library-consumption/<its id>.md`. If it adds a `**Unreleased on main**` paragraph to either doc instead, `tests/unit/test_unreleased_notes.py` fails, naming the file to write.
- **The scheduler** sees, after the retarget (§3 D8), no open task declaring `docs/domain-library-consumption.md` only to add a line to it. Each note writer declares its own note path, which no other task declares.
- **A platform consumer** reading on GitHub finds the changes since 0.5.0 under `docs/unreleased/`, one file per task, from the guide's rule and the finance-model doc's header.
- **The release (S29 β, task 224)** folds `docs/unreleased/*/*.md` into the 0.6.0 section and deletes the notes. It no longer collects paragraphs out of two docs.

## 2. Background (measured on main `073da99` and the store, 2026-11-06)

### 2.1 Why the doc became a hot spot

- The guide's rule "Changes merged since the last tag" asked every such change for an `**Unreleased on main**` paragraph in the guide's "Tag / release convention" section. Changes to what a finance-model name returns got a line in the header of `docs/cost-recovery-finance-model.md` instead.
- The guide held 55 such paragraphs (tasks 392 to 787 and later; task 838 had two). The finance-model header held 11 lines. The surface lock's failure message (`tests/unit/test_public_api_surface.py::_drift_message`) and the fleet-pin test's message ask for the same paragraph.
- Of 163 open tasks, 78 declared the guide in `metadata.files`. 31 declared `review/briefing.yaml` and 18 declared the finance-model doc.
- The orchestrator locks each declared path (`shared.locking.normalize_lock` truncates it to `lock_depth` segments; dark-factory's default is 4 and this repo sets none). Two locks conflict when one is a prefix of the other (`shared.locking.modules_conflict`). So the 78 tasks ran one at a time, at 2-6 h each.
- Tasks 1119, 1171 and 1223 had waited about 126 h. The starvation watchdog's auto-pin cap (3) was full. Task 871 held the guide, task 908 was pinned on it, and 782 and 879 were parked behind it (`data/orchestrator/scheduler_state.json`).

### 2.2 What the contenders write

Two classification seats read each of the 89 open tasks that declare one of the three files (§7.1 gives the counts). Most write only a note. A few edit the guide's other content: task 986 (S29 α) opens the 0.6.0 window heading, task 224 (S29 β) does the release, task 827 edits the Network I/O caveat, and task 895 describes EV behaviour in the guide. Most of the finance-model doc's tasks edit its specification sections, §3 to §9, which is real contention.

### 2.3 Who reads the briefing

`review/briefing.yaml` is read from one path by the orchestrator's task reviewers (dark-factory `defaults.yaml` `briefing_path`, read by `orchestrator/review_inputs.py`) and by the `/review`, `/review-briefing`, `/hotspot-survey` and `/review-all` skills.

## 3. Resolved design decisions

- **D1. One file per task per doc: `docs/unreleased/<doc>/<task id>.md`.** `<doc>` is the stem of the doc whose readers the note serves: `domain-library-consumption` or `cost-recovery-finance-model`. The body is the paragraph a release lists under the task id, without the `**Unreleased on main** (task N):` prefix. The path carries the task id and the doc, so no file holds front matter and nothing parses one.
  - Rejected: a `kind:` front-matter field (breaking / results that move / additive). S29 decisions 4 and 5 give that grouping to β, which classifies with S23 ζ's inventory at release time. A writer's field would decide it earlier with less information, and it would need a parser. Reconsider when S29 has closed, if a later release wants the writer to classify.
  - Rejected: one file per consumer area of the guide (finance, simulation, web). Two tasks in one area would still contend, and an area is a judgment a writer makes, which the release then has to undo.
- **D2. Every existing paragraph moves, text unchanged.** One place holds the unreleased notes (SPOT). Task 838's two paragraphs become one file. The one paragraph headed `(tasks 384, 378, 332)` lives in `384.md` and ends "This note also covers tasks 378 and 332." The two notes that said "(below)" name the other task's note instead.
- **D3. The guard.** `tests/unit/test_unreleased_notes.py` fails when either doc holds a line that starts with `**Unreleased on main**`, when a file under `docs/unreleased` other than its README is not `<doc>/<task id>.md`, when a note is empty, when `NOTE_DOCS` names a doc that does not exist, and when the README is missing. Each message names the file to write.
- **D4. `docs/unreleased/README.md` stays across releases.** It is a pointer to the guide's rule. It exists so the directory stays on main when a release deletes every note. Then a delivered check scoped to `docs/unreleased` never names a removed path.
- **D5. Lock arithmetic.** A note path has 4 segments, within `lock_depth` 4, so `normalize_lock` keeps it whole and distinct. fused-memory's lock charter refuses a directory in `metadata.files` (observed: `LockCharterViolation` on task 224), so no task can lock `docs/unreleased` as a whole. The release therefore names the note files present at its base in its plan, and folds any note that lands meanwhile before it merges (N4).
- **D6. `review/briefing.yaml` is not split.** Its readers take one path (§2.3), so splitting it is a dark-factory change, which this ruling excludes (§9). Fragments would not help either. Most of its contenders rewrite an existing convention or key decision in place, and a reviewer would read the stale entry until a fold ran. The relief here is the retarget: a task whose text asks for no briefing edit stops declaring it (D8).
- **D7. The finance-model doc's body is not split.** Its tasks edit its specification sections. That contention is real, and splitting a specification a board member reads end to end would cost readability. Only its header lines move (D1), which frees the tasks that write nothing else there.
- **D8. Retarget rule for open tasks** (fused-memory `update_task`, `metadata_mode: merge`, the full `files` list re-sent):
  - **Guide note-only:** drop the guide, add `docs/unreleased/domain-library-consumption/<id>.md`, and the note file of each other task whose note it edits (task 1119 corrects 801's and 803's).
  - **Guide body:** keep the guide and add the note path.
  - **Guide none, declared:** drop the guide. Add the note path too, because a change to a public name needs a note under the rule even when the task's text does not ask for one. A unique path costs no contention.
  - **Finance-model doc:** the same three rules, with `docs/unreleased/cost-recovery-finance-model/<id>.md`.
  - **Briefing none, declared:** drop `review/briefing.yaml`. If the task does need it, the architect's plan adds it back.
  - Each retargeted task gets one appended `details` paragraph naming its note path and this PRD. A task text that says "add an Unreleased on main line to docs/domain-library-consumption.md" is then read beside that paragraph. The guard catches an agent that follows the old text anyway.
  - **In-progress tasks are not edited.** A running agent does not see an amendment. Task 871 (in progress, holding the guide) adds its line wherever its branch puts it. If it lands after α, its verify fails on the guard, whose message names the file to write.
- **D9. Delivered checks that read a moved paragraph gain `docs/unreleased` in their paths, in both halves** (the task's `metadata.delivered_checks`, re-sent whole, and its PRD sidecar). The doc stays in each check's paths, so the check stays green when β folds the notes back into the guide. These are the checks that flip from green to red at α: 773 `errors-module-named-in-src-and-consumer-guide`, 774 `consumer-guide-names-the-base-class`, 801 `consumer-guide-names-the-new-member`, 823 `consumers-told-to-re-baseline` and 865 `consumer-guide-names-compute-soh`. Also the pending producers' checks whose line now goes in a note: 802 `consumer-guide-names-the-refusals`, 837 `consumer-guide-names-the-model-change`, 863 `consumer-guide-names-with-round-trip` and 900 `finance-model-header-line`. The other checks on the guide or the finance-model doc match the same files at α's tip as at its base: 224's, 801's two model-doc checks, 803's, 837's model-doc check, 865's finance check, 917's absent check and 986's.
- **D10. S29 and S23 contracts are amended, not rewritten.** Each PRD gains an amendment block naming this PRD (§6). S29 keeps its window: α still opens the `### solar-challenge-v0.6.0` heading and writes the convention paragraph, and a held leaf's note is a file, not a paragraph under the heading. S23 η's check becomes a file-existence check.

## 4. Contract

- **N1. Layout.** A release note for a change merged since the last tag is `docs/unreleased/<doc>/<task id>.md`. `<doc>` is one of `tests/unit/test_unreleased_notes.py::NOTE_DOCS`, and `docs/<doc>.md` exists. `<task id>` is the decimal id of the task whose change it describes. `docs/unreleased/README.md` is the only other file there.
- **N2. Content.** The note is the paragraph the release lists under its task id: what changed against the last tag, ending with what a consumer does when they re-pin. A later change to the same task's note edits the same file. A relative link in a note resolves from the note's own directory (`../../pv-cell-temperature.md`); `tests/unit/test_source_markdown_links.py` checks every one, and the release rebases them when it folds the text into the guide.
- **N3. No doc holds an unreleased note.** No line of `docs/domain-library-consumption.md` or `docs/cost-recovery-finance-model.md` starts with `**Unreleased on main**`.
- **N4. The release folds and deletes.** The release commit moves every note's text into its release section, keeping the task id, and deletes the notes. It keeps the README. It cannot lock the directory (D5), so before it merges it folds any note that landed after its base.
- **N5. One writer per note.** A task declares only note paths that carry its own id, or the id of a task whose note its text corrects.

## 5. Boundary tests

| # | Faces | Scenario | Postcondition | Where |
|---|---|---|---|---|
| B1 | writer | A surface change adds a `**Unreleased on main**` paragraph to the guide | `test_no_doc_holds_an_unreleased_note[domain-library-consumption]` fails, naming the line and the note path | α (observed at α: planted paragraph fails) |
| B2 | writer | A note at `docs/unreleased/domain-library-consumption/x.md` | `test_every_note_is_a_task_file_under_the_doc_it_serves` fails, naming the file | α (observed at α) |
| B3 | writer | An empty note | `test_every_note_says_what_changed` fails | α (observed at α) |
| B4 | scheduler | Two note writers pending | Their declared note paths differ, and neither is a prefix of the other, so neither blocks the other (`modules_conflict`) | α + D8 retarget |
| B5 | release | β deletes every note | The README stays; `test_the_notes_directory_keeps_its_readme` passes; the D9 checks still match the guide | β (224) |
| B6 | S23 η | After β, a frozen-row edit by task N | 927's check finds `docs/unreleased/domain-library-consumption/N.md` | 927 |
| B7 | reader | The text of every moved paragraph | Every word of the 66 paragraphs, less their prefixes, is in a note (word-multiset diff of base and tip) | α (checked at α) |

## 6. Cross-PRD relationship

| Other PRD / task | Direction | Mechanism | Owner of the edit | Amendment |
|---|---|---|---|---|
| `surface-version-bump.md` (S29); α = 986, β = 224 | consumes the notes | β folds `docs/unreleased/*/*.md`; W1, W3, W4 and R4 now name notes | S29 (986, 224 do the work); this PRD amends the text | Amendment block in that PRD; one `details` paragraph each on 986 and 224 |
| `surface-lock-one-module.md` (S23); ζ = 926, η = 927 | consumes the layout | ζ's drift-message trailer names the note file; η's check is "each `UNRELEASED` id has a note file" | S23 | Amendment block in that PRD; one `details` paragraph each on 926 and 927 |
| The PRDs whose sidecars hold the D9 checks: errors-leaf, grid-services-pricing-model, pv-model-one-home, battery-efficiency-and-throughput, one-dispatch-engine | their checks read moved text | `paths` gains `docs/unreleased` | This PRD (α edits the sidecars; the session re-sends each task's checks) | none needed |

## 7. Decomposition plan

No orchestrator leaf. The work is a single change plus store edits, done in the authoring session (Leo's ruling asked for the restructure itself).

- **α: the restructure** (interactive, branch `task/release-note-fragments`, landed via `/merge-queue`). Moves the paragraphs (D2), rewrites the guide's rule and the finance-model header, adds the guard and the README (D3, D4), rewords the lock's, the fleet-pin test's, the briefing's and `pv-cell-temperature.md`'s pointers, repaths the D9 sidecar checks, adds a `CLAUDE.md` Key Patterns bullet, and amends the S29 and S23 PRDs (D10). **Signal:** B1 to B3 and B7 observed on the branch; the verify suite passes.
- **Store edits** (same session, before α merges, so a check repaired early stays green with the doc still in its paths):
  - the D9 delivered-check repairs;
  - the D8 retargets of every open, not in-progress task that declares one of the three files;
  - the companion `details` paragraphs on 224, 926, 927 and 986.
  - **Signal:** a store read after the edits shows no open task, other than in-progress ones and the guide-body tasks, declaring the guide.

### 7.1 Classification counts

Population: the 89 tasks that declared one of the three files at the 2026-11-06 store read (88 open, plus cancelled task 284, which still carried the metadata and is not retargeted). Two classification seats read each task's full text; the lead applied D8 to their output.

| File | Body edit | Note only | Declared, no edit asked | Not declared |
|---|---|---|---|---|
| guide | 7 (224, 827, 895, 927, 939, 986, 1246) | 62 | 10 | 10 |
| finance-model doc | 14 | 1 (1119) | 3 | 71 |
| briefing | 26 edit it | — | 5 (284, 515, 1029, 1043, 1315) | 58 |

After the retarget, 9 tasks declare the guide: the 7 body editors, in-progress task 871 (not edited, D8) and cancelled 284. 16 declare the finance-model doc and 27 the briefing. 1270 keeps the finance-model doc although its text asks for no edit, because its change touches the override the doc's §3 describes. 1119 and 1223 correct other tasks' notes (801 and 803; 862 and 1125); they are retargeted after α merges, because those note files exist only from α on.

## 8. Out of scope

- Splitting `review/briefing.yaml`, or a fold step for briefing fragments (D6).
- Splitting the finance-model doc's body (D7).
- `tests/unit/test_public_api_surface.py`, which 43 open tasks declare. Its frozen tables are real code each surface change edits. S23 owns that module.
- Any dark-factory change. Recorded as notes only:
  - **Sub-file locks.** Lock granularity is one file. A per-section (or per-YAML-key) lock declared in `metadata.files`, e.g. `docs/cost-recovery-finance-model.md#4`, would let spec edits to different sections run side by side.
  - **Append-only declarations.** A file that tasks only append to (a changelog, a conventions list) could be declared shared-append, with the merge queue's rebase as the conflict check, not an exclusive lock.
  - **Directory locks.** The lock charter refuses a directory in `metadata.files`. A release that deletes every file under a directory has no way to hold them all, so it re-checks for late arrivals before merging (D5).
  - **Briefing includes.** If `briefing_path` accepted a directory (one YAML per area or per convention), `review/briefing.yaml` could be split without losing reviewer visibility.
  - **Lock-depth tripwire.** D5 depends on `lock_depth` ≥ 4. A project-level check that its note paths survive `normalize_lock` unchanged would catch a lowered depth.

## 9. Open questions (tactical)

1. **Does β render the notes with a helper?** S29 β can concatenate them by hand, grouping by its inventory. A helper beside the guard is worth writing only if a later release repeats the fold. Decide in 224.

## Gate record

- **G1:** the notes' consumers are the release (224), S23 η's check (927), platform readers and the scheduler's lock table. The guard's consumer is every surface-changing agent.
- **G2:** α's signal is B1 to B3 and B7, observed on the branch, plus the verify. The store edits' signal is the post-edit store read (§7).
- **G3:** verified against dark-factory: `normalize_lock`, `modules_conflict` and `lock_depth` 4 (defaults.yaml; `scheduler_state.json` reports 4). Delivered-check `grep` takes directory pathspecs (`git grep -- <dir>`). `briefing_path` is one path.
- **G4:** §6. Each seam has one owner; this PRD owns only the text amendments.
- **G5:** B + H at small scale: N1 to N5 and B1 to B7.
- **G6:** B1 to B3 were observed failing on planted input. B4 follows from `modules_conflict` on distinct 4-segment paths. D9's flip list comes from `git grep` of each check at α's base and tip. No numeric threshold is asserted.
- **META:** yes. With D1 to D10, an agent implementing any open surface task writes a note file under a lock no other task holds. The release and S23 η each have one place to read.
