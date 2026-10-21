# Fleet Map Declutter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the fleet map readable at a glance: progress bars in collapsed run clusters, real names, no zero noise, legend and edges on demand.

**Architecture:** Server-side additions are small (a `short_name` per cluster, `total_units` on the Implementing cell). Everything else is in `kitty/fleetmap/page.html`, tested through the existing Node-with-minimal-DOM harness in `tests/test_fleetmap_page.py`.

**Tech Stack:** Standard-library Python 3.9, the page's plain JavaScript, `unittest`.

**Spec:** `docs/superpowers/specs/2026-10-19-fleet-map-design.md`, section "Revision 2026-10-20: declutter" (Decisions 23 to 27). Earlier decisions still apply where not amended.

## Global Constraints

- Standard library only; every Python module and test starts with `from __future__ import annotations` and runs on macOS `/usr/bin/python3` 3.9.6.
- Positions and cluster geometry stay stable across ordinary refreshes (final-review ruling I8); layout tests must still pass.
- The fast refresh thread gains no filesystem, Orca, or network work.
- Branch `fleet-map-declutter`; commit per task with prefix `feat(declutter):`; push to origin when a task is complete.

## Review Focus

- A run whose projection has no packages in a slice: the collapsed row shows `verified 0 of 0 units` and an empty bar, never an exception.
- A cluster whose objective starts with a pasted-content tag or a commit hash: `short_name` skips it and still yields words.
- A node with no title and no purpose: the two-line label falls back to the id without throwing.
- `localStorage` throwing (private mode): the legend stays closed and the page still renders.
- Selecting a node with zero edges: no badge, no edges, no error; deselecting restores badges.

---

### Task 24: Collapsed run cluster shows the bars

**Files:**
- Modify: `kitty/fleetmap/matrix.py` (Implementing cell gains `total_units`), `kitty/fleetmap/page.html` (`renderCluster`, `matrixTable`, `stepper`)
- Test: `tests/test_fleetmap_matrix.py`, `tests/test_fleetmap_page.py`

**Interfaces:**
- Consumes: `row.cells.implementing = {segments, verified_units, ...}` from `build_matrix`.
- Produces: `row.cells.implementing.total_units` (sum of package units in the slice, S=1 M=2 L=3); page function `segmentBar(run, row)` returning the `.segments` element used by both the collapsed cluster and the matrix cell.

- [ ] **Step 1: Failing matrix test** `test_implementing_cell_reports_total_units`: a slice with packages S, M, L (one verified M) yields `verified_units == 2` and `total_units == 6`; a slice with no packages yields `0` and `0`.
- [ ] **Step 2: Run** `/usr/bin/python3 -m unittest tests.test_fleetmap_matrix -v`; expect FAIL on the missing key.
- [ ] **Step 3: Implement** `total_units` in `build_matrix`.
- [ ] **Step 4: Failing page tests** in `tests/test_fleetmap_page.py`, using the existing harness: `test_collapsed_run_cluster_renders_now_line_and_slice_bars` (a collapsed run cluster's panel contains the `run.now` text, one `.slice-row` per row each with a `.segments` element and the text `verified 2 of 6 units`, and no `.stepper` element); `test_collapsed_counts_line_only_when_nonzero` (waiting 0 and stalled 0 render no `.cluster-summary`; waiting 1 renders `waiting on you: 1 · 0 stalled`); `test_matrix_holds_stepper_and_proofs` (the expanded table's first column holds the stepper and the proofs paragraph follows the table).
- [ ] **Step 5: Run** them; expect FAIL.
- [ ] **Step 6: Implement** per Decision 23: extract `segmentBar(run, row)` from `matrixTable`, render it in `renderCluster` when collapsed, move `stepper(row)` into the matrix's first column and the proofs line under the table, gate the counts line.
- [ ] **Step 7: Run** `/usr/bin/python3 -m unittest discover -s tests` and `python3 -m unittest discover -s tests`; expect all pass.
- [ ] **Step 8: Commit** `feat(declutter): show slice progress bars in collapsed run clusters`.

### Task 25: Names

**Files:**
- Modify: `kitty/fleetmap/clusters.py` (add `short_name(name: str) -> str`), `kitty/fleetmap/model.py` (every cluster record gains `short_name`), `kitty/fleetmap/page.html` (heading uses `short_name` with `title=name`; `paintNode` two-line label)
- Test: `tests/test_fleetmap_clusters.py`, `tests/test_fleetmap_model.py`, `tests/test_fleetmap_page.py`

**Interfaces:**
- Produces: `short_name(name)`: strips a leading `<tag>...</tag>` or `<tag>` token and any token of at least 32 hexadecimal digits, then returns the first five whitespace-separated words joined by single spaces, with `…` appended when words were dropped; an empty result returns the original name. Cluster records in the snapshot carry `short_name`. Initiative and projection clusters use the name unchanged (Decision 24).

- [ ] **Step 1: Failing tests**: `test_short_name_takes_five_words_with_ellipsis` (`"Review PR 6869 under Engineering OS run 20261007"` → `"Review PR 6869 under Engineering…"`), `test_short_name_skips_pasted_tag_and_hash` (`"<pasted_content id=\"4e35\">\nContinue a review of c5a5627d657b67bb95d28fdf6d794f7d4dff9131 now"` → `"Continue a review of now"`: the tag and the hash are skipped, four words remain, so no ellipsis), `test_short_name_keeps_initiative_names` (a promoted initiative `"Core lint speed"` is unchanged), a model test that every cluster in a snapshot has `short_name`, and a page test `test_cluster_heading_uses_short_name_with_full_title` plus `test_node_label_wraps_to_two_lines_at_a_space` (`"Handoff scheduling engineering OS run"` → first line `"Handoff"`, second `"scheduling…"`; `"Report-task-four"` with no space → `"Report-tas…"` on one line; title attribute holds the full text).
- [ ] **Step 2: Run**; expect FAIL.
- [ ] **Step 3: Implement** `short_name`, attach it in `model.py` where cluster records are created (initiative and projection clusters get the name verbatim), and the page changes.
- [ ] **Step 4: Run** both complete suites; expect pass.
- [ ] **Step 5: Commit** `feat(declutter): short cluster names and two-line node labels`.

### Task 26: Hide zeros, Send to all in the rail

**Files:**
- Modify: `kitty/fleetmap/page.html` (`renderCluster`, `renderRail`, a new `selectCluster(id)`)
- Test: `tests/test_fleetmap_page.py`

**Interfaces:**
- Produces: `selectCluster(id)` sets `selectedCluster`, clears `selectedId`, and `renderRail` shows the cluster card: full name, host, "Open run plan" when the cluster has a run, the counts line, and the Send to all button calling `openBroadcast(name)`.

- [ ] **Step 1: Failing page tests**: `test_heading_has_only_caret_and_name` (no button other than the caret in `.cluster-heading`), `test_clicking_name_selects_cluster_and_rail_shows_send_to_all` (after the click, the rail contains the full name and a `Send to all` button; `expanded` is unchanged), `test_caret_alone_expands` (clicking the caret adds the id to `expanded`; clicking the name does not).
- [ ] **Step 2: Run**; expect FAIL.
- [ ] **Step 3: Implement** per Decision 25.
- [ ] **Step 4: Run** both complete suites; expect pass.
- [ ] **Step 5: Commit** `feat(declutter): select clusters from the heading; broadcast from the rail`.

### Task 27: Legend on demand, edges on focus

**Files:**
- Modify: `kitty/fleetmap/page.html` (header `?` button, `footer` hidden by default, `drawEdges`, `paintNode` badge, hover handlers)
- Test: `tests/test_fleetmap_page.py`

**Interfaces:**
- Produces: `toggleLegend(open?)` persisting to `localStorage['fleetmap.legend']` as `"1"` or `"0"` inside try/catch; `drawEdges()` draws only edges touching `selectedId` or `hoveredId`; `paintNode` sets a `.edge-badge` text to the node's edge count (`9+` above nine) and hides it when the node is selected or hovered or has no edges.

- [ ] **Step 1: Failing page tests**: `test_legend_closed_by_default_and_toggle_persists` (footer hidden on load; after `toggleLegend()` it is visible and `localStorage['fleetmap.legend'] === '1'`; a throwing storage stub leaves it closed without error), `test_edges_drawn_only_for_selected_or_hovered` (three nodes with two edges: no `line.edge` before selection; selecting an endpoint draws its edges only; hover draws the hovered node's), `test_edge_badges_count_and_hide_on_focus` (badge text `2` on a node with two edges, hidden when selected, `9+` for ten edges).
- [ ] **Step 2: Run**; expect FAIL.
- [ ] **Step 3: Implement** per Decisions 26 and 27; subagent parent links unchanged.
- [ ] **Step 4: Run** both complete suites; expect pass.
- [ ] **Step 5: Commit** `feat(declutter): legend behind a toggle; edges and badges on focus`.

### Task 28: Fallback cluster content reserves its height

**Files:**
- Modify: `kitty/fleetmap/page.html` (`layoutFleet`, `renderCluster`, `renderFallback`)
- Test: `tests/test_fleetmap_page.py`

**Interfaces:**
- Consumes: the collapsed cluster panel from Task 24 and the fallback records from Decision 24's `fallbacks`.
- Produces: the node grid of a cluster starts below the panel's rendered content, whatever that content's height; a Now line longer than the cluster width wraps inside the panel and never overflows it.

- [ ] **Step 1: Failing page tests**: `test_fallback_now_line_wraps_inside_panel` (a fallback cluster whose `now` is 200 characters has a panel whose text content is fully inside the panel element and no element with `overflow` outside it), `test_node_grid_starts_below_cluster_content` (with a three-line Now and a projection note, the first node's `y` is greater than the panel content's bottom; with an empty panel, the grid starts where it starts today).
- [ ] **Step 2: Run**; expect FAIL.
- [ ] **Step 3: Implement**: measure the panel content height after rendering (or compute it from the rendered line count) and feed it to `layoutFleet` as the cluster's content offset; wrap long lines with `overflow-wrap: anywhere` in the panel.
- [ ] **Step 4: Run** both complete suites; expect pass, including the position stability tests.
- [ ] **Step 5: Commit** `feat(declutter): node grid starts below cluster content`.

### Task 29: Decision card

**Files:**
- Modify: `kitty/fleetmap/page.html` (`renderDecisions`, `renderContext`, the send overlay's prefill)
- Test: `tests/test_fleetmap_page.py`

**Interfaces:**
- Consumes: `snapshot.decisions` items `{run, title, id, class, text, packet, applyAt}`; `openRun(runId)`; `openOverlay(title, nodeId)` and the `send` action; the `Open run plan` button in the rail; `run.chief_node`; `miniNode(id)`.
- Produces: `showDecision(item)` sets `selectedContext = {run, decision: item.id}` after `openRun(item.run)`; `renderContext` renders a `.decision-card` for that context; `openOverlay` accepts an optional third argument `prefill` that sets the send text field's value.

- [ ] **Step 1: Failing page tests**: `test_decision_chip_has_three_lines` (a chip renders three child lines: title, text, `Class C · E3 · apply-by —`), `test_clicking_decision_opens_run_and_card` (after the click, `expanded` holds the run's cluster, `selectedContext.decision === 'E3'`, and the rail holds a `.decision-card` with the full text, the packet, a mini node for the Chief, buttons `Reply to Chief` and `Open run plan`, and the muted line `Clears when the Chief records it`), `test_reply_to_chief_prefills_send_overlay` (clicking `Reply to Chief` opens the overlay for the Chief node with the text field value `Decision E3: `), `test_decision_card_without_chief_node` (a run whose `chief_node` is not in the snapshot renders the card without the mini node and without `Reply to Chief`, and throws nothing).
- [ ] **Step 2: Run**; expect FAIL.
- [ ] **Step 3: Implement** per Decision 28.
- [ ] **Step 4: Run** both complete suites; expect pass.
- [ ] **Step 5: Commit** `feat(declutter): decision card with reply to Chief`.

## Second round (2026-10-20 10:44 PDT): Decisions 29 to 35

Branch `fleet-map-declutter-2` from master `ece5aa4`. Same global constraints and review focus. Tasks run in order; each is one commit prefixed `feat(declutter2):`.

### Task 30: Header summary, state filter, region status word

**Files:** Modify `kitty/fleetmap/page.html` (`render`, the status line, region metrics); Test `tests/test_fleetmap_page.py`.

**Interfaces:** Produces `stateFilter` (null or one of `working`, `attention`, `idle`), `setStateFilter(state)`, and `nodeDimmed(node)` used by `paintNode`. Idle counts `idle` plus `done`.

- [ ] Failing tests: `test_header_counts_by_state` (2 working, 1 attention, 15 idle plus done renders `22 sessions · 2 working · 1 need you · 15 idle`), `test_state_filter_dims_others_and_toggles_off` (clicking the working count sets `stateFilter` and gives non-working nodes opacity 0.25; clicking it again clears), `test_region_status_word` (`OK`, `Tight` below 40% free, `Over cap` when workers exceed cap).
- [ ] Run; expect FAIL. Implement per Decision 29. Run both suites. Commit `feat(declutter2): header counts with a state filter; region status word`.

### Task 31: Fold idle sessions

**Files:** Modify `kitty/fleetmap/page.html` (`layoutFleet`, `renderCluster`, `paintNode`); Test `tests/test_fleetmap_page.py`.

**Interfaces:** Produces `foldable(node, now)` (idle or done, newer of `you_at`/`it_at` older than 24 h, or never prompted), `unfolded` (a Set of cluster ids), and a `.fold-chip` element per cluster with text `k idle`.

- [ ] Failing tests: `test_old_idle_nodes_fold_into_a_chip` (three idle nodes aged 30 h in one cluster render no node circles and one chip `3 idle`), `test_working_and_recent_nodes_never_fold` (a working node aged 30 h and an idle node aged 2 h both render), `test_clicking_chip_unfolds_cluster` (after the click the three nodes render and the chip is gone), `test_header_counts_include_folded` (the Decision 29 counts are unchanged by folding).
- [ ] Run; FAIL. Implement per Decision 30. Both suites. Commit `feat(declutter2): fold old idle sessions into a chip`.

### Task 32: Search

**Files:** Modify `kitty/fleetmap/page.html` (header input, `render`, `paintNode`, key handling); Test `tests/test_fleetmap_page.py`.

**Interfaces:** Produces `searchQuery`, `nodeMatches(node, query)` over title, purpose, doing, last_said, repo, branch (case-insensitive substring), and the status suffix `· m match`.

- [ ] Failing tests: `test_search_dims_non_matches_and_counts` (query `6897` gives one match at full opacity, others at 0.25, status ends `· 1 match`), `test_search_unfolds_matching_folded_node` (a folded idle node matching the query renders), `test_slash_focuses_and_escape_clears` (`/` focuses the box when no input has focus; Escape clears the query and the dimming), `test_search_combines_with_state_filter`.
- [ ] Run; FAIL. Implement per Decision 31. Both suites. Commit `feat(declutter2): find a session`.

### Task 33: Hover card

**Files:** Modify `kitty/fleetmap/page.html` (`paintNode` title); Test `tests/test_fleetmap_page.py`.

**Interfaces:** Produces `hoverText(node, now)` returning at most five lines per Decision 32.

- [ ] Failing tests: `test_hover_has_title_doing_said_ages_repo` (exact five lines for a full node, `Doing:` and `Said:` cut to 80 characters with `…`), `test_hover_omits_missing_lines_and_never_shows_prompt` (a node with no doing and no said yields three lines; a 10,000-character purpose never appears).
- [ ] Run; FAIL. Implement. Both suites. Commit `feat(declutter2): hover card instead of the first prompt`.

### Task 34: Rail order, vocabulary, Peek reasons

**Files:** Modify `kitty/fleetmap/page.html` (`renderRail`, node actions, Peek overlay), `kitty/fleetmap/server.py` and `kitty/fleetmap/actions.py` only if the Peek response needs a `reason` field; Test `tests/test_fleetmap_page.py`, `tests/test_fleetmap_server.py` if the response changed.

**Interfaces:** Produces the rail order of Decision 33, `stateLine(node, now)`, a `<details>` labeled `First prompt`, omitted unavailable actions, and the Peek reason line.

- [ ] Failing tests: `test_rail_leads_with_state_doing_said_ages` (child order: title, state line, Doing, Said, ages, actions, run card, details), `test_rail_omits_unavailable_actions_and_parent` (no button text contains `unavailable`; no parent link when the parent is absent), `test_rail_button_labels` (`Add to a project`, `Move to another box`), `test_first_prompt_is_collapsed` (the details element is closed and holds the purpose), `test_peek_empty_screen_states_reason` (each of the three reasons renders its exact line).
- [ ] Run; FAIL. Implement. Both suites. Commit `feat(declutter2): rail leads with what the session is doing`.

### Task 35: Retired worker terminals

**Files:** Modify `kitty/fleetmap/model.py` (terminal nodes, host worker counts), `kitty/fleetmap/orca.py` only if worker records lack the fields, `kitty/fleetmap/page.html` (chip, rail list); Test `tests/test_fleetmap_model.py`, `tests/test_fleetmap_page.py`.

**Interfaces:** A worker record from `orca orchestration worker-list --run <id> --json` carries `workerState` (`succeeded`, `released`, `abandoned`, `failed`, `ready`, …) and `terminalState` (`retained` or absent). Produces `retired_workers` per cluster in the snapshot (`[{title, dispatchId, state, retainedFor}]`), terminal nodes excluded for them, `hosts[].workers` counting live workers only, and a `.retired-chip` `k retired workers` with a rail list.

- [ ] Failing tests (model, with the FakeOrca fixture): `test_retired_worker_terminals_are_not_nodes` (a released and an abandoned retained terminal yield no nodes and a two-entry `retired_workers` on their cluster), `test_live_agent_terminal_is_never_retired` (a retained terminal with a live agent process stays a node), `test_host_worker_count_excludes_retired`; page: `test_retired_chip_lists_in_rail`.
- [ ] Run; FAIL. Implement per Decision 34. Both suites. Commit `feat(declutter2): retired worker terminals fold into a chip`.

### Task 36: Boxes by repository

**Files:** Modify `kitty/fleetmap/clusters.py` (`cluster_for`), `kitty/fleetmap/model.py` (repository lookup in the slow thread, cached per worktree root), `kitty/fleetmap/registry.py` or `kitty/fleetmap/signals.py` for the git call if one of them owns git probes today; Test `tests/test_fleetmap_clusters.py`, `tests/test_fleetmap_model.py`.

**Interfaces:** Produces `repository_name(worktree_root) -> str | None` (basename of the parent of `git rev-parse --git-common-dir`, resolved to an absolute path; `None` outside a repository), cached per root for the slow thread's TTL, and `cluster_for(...)` grouping unclaimed nodes by that name with `Unsorted` as the fallback. Node `repo` keeps today's worktree basename; a new node field `repository` carries the name.

- [ ] Failing tests: `test_repository_name_from_common_dir` (two worktrees of one temp repository both yield the repository's directory name; a plain directory yields None), `test_unclaimed_nodes_cluster_by_repository_not_branch` (nodes on branches `main` and `feature` in two worktrees of one repository share the cluster named after it), `test_run_and_pin_claims_still_win`, `test_no_repository_goes_to_unsorted`, and a model test that the lookup runs in the slow thread and is cached (the fast thread never calls git).
- [ ] Run; FAIL. Implement per Decision 35. Both suites. Commit `feat(declutter2): boxes named by repository`.

## Third round (2026-10-20 14:55 PDT): Decisions 36 to 41

Branch `fleet-map-declutter-3` from master. Same global constraints. One commit per task prefixed `feat(declutter3):`. Page tests assert the DOM through the Node harness; where layout matters, assert computed positions from `layoutFleet`, and use a `matchMedia`/`innerWidth` stub for width-dependent behavior.

### Task 37: Rail on demand and narrow-width header

**Files:** `kitty/fleetmap/page.html`; `tests/test_fleetmap_page.py`.

- [ ] Failing tests: `test_rail_hidden_until_selection` (no selection: rail hidden, map width equals the viewport minus margins), `test_selection_opens_rail_and_close_hides_it` (node click opens; the close button and Escape with an empty search close; Escape inside an open dialog does not), `test_narrow_width_rail_is_overlay` (innerWidth 768: opening the rail adds an overlay class and a dimmed backdrop, the map keeps its full width), `test_narrow_header_wraps_search_onto_second_line` (innerWidth 390: the search box and `?` are in the second header row).
- [ ] Implement per Decision 36. Both suites one at a time. Commit `feat(declutter3): rail opens on demand; overlay below 1000 px`.

### Task 38: Boxes fit their contents, heading on one line

**Files:** `kitty/fleetmap/page.html`; `tests/test_fleetmap_page.py`.

- [ ] Failing tests: `test_cluster_height_fits_one_node_row` (a box with no panel content and four nodes is at most heading + one node row + padding tall), `test_clusters_pack_by_actual_height` (a short box and a tall box in one region: the next box starts below the short one, not below a fixed slot), `test_long_name_wraps_beside_caret` (the caret and the name's first line share a top coordinate), plus the existing position stability tests passing.
- [ ] Also fix: a subagent dot must never overlap a neighboring node (it is drawn on top of `Random PF` in the live glow-core box); add `test_subagent_dots_never_overlap_sibling_nodes`.
- [ ] Implement per Decisions 37 and 38. Both suites. Commit `feat(declutter3): boxes fit their contents; caret and name on one line`.

### Task 39: Short ids, decision chip, large screens

**Files:** `kitty/fleetmap/page.html`; `tests/test_fleetmap_page.py`.

- [ ] Failing tests: `test_long_hex_ids_are_shortened_in_now_lines` (a Now line containing a 64-hex id renders `c5a5627d…` and its title attribute holds the full text), `test_decision_strip_label_and_attention_style` (`Needs you · 1`, the chip has the attention class and a dot; with none, `Nothing needs you`), `test_large_screen_steps_font_and_node_size` (innerWidth 2560: base font 14 px and node radius scaled by 14/12; innerWidth 1512: unchanged).
- [ ] Implement per Decisions 39 to 41. Both suites. Commit `feat(declutter3): short ids, a decision strip that stands out, larger type on big screens`.

## Status from the run plan (2026-10-21): Decisions 42 to 44

Branch `fleet-map-status-from-plan` from master. Same global constraints; commits prefixed `feat(status):`.

### Task 40: Read the run-status block, show freshness and rejections

**Files:** `kitty/fleetmap/providers/engineering_os.py`, `kitty/fleetmap/projection.py` (a vendored `status_block(text)` parser identical in behavior to the lab's: ignores fences nested in other fences, exactly one block), `kitty/fleetmap/model.py` (slow-thread git call for the plan's last commit hash and time, cached by plan path and mtime; last-good projection per run kept in memory), `kitty/fleetmap/page.html`; tests in `tests/test_fleetmap_providers.py`, `tests/test_fleetmap_model.py`, `tests/test_fleetmap_page.py`.

- [ ] Failing tests: `test_provider_reads_run_status_block_from_run_plan` (temp git repo with `engineering-os/r1/run-plan.md` holding one valid block, committed: the projection is returned with runPlan.commit equal to the plan's last commit), `test_plan_without_block_is_ignored`, `test_plan_with_two_blocks_or_bad_json_is_rejected_with_reason`, `test_nested_example_fences_do_not_count`, `test_block_and_file_for_same_run_newer_wins`, `test_fast_thread_never_calls_git_for_plans`; model: `test_rejected_known_run_keeps_last_good_projection_and_reason`; page: `test_run_box_shows_status_age`, `test_run_box_amber_when_plan_changed_since`, `test_rejected_status_line_is_shown`, `test_unattributed_rejections_listed_in_rail`.
- [ ] Implement per Decisions 42 to 44. Run the page module, then the full suite alone gated on its exit status. Commit `feat(status): read run status from the run plan; show freshness and rejections`.
