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
