# Fleet map: one board for every agent session

Date: 2026-10-19. State: approved in full by Hassan Khan, base at 13:09 PDT and Decisions 11 to 22 at 13:55 PDT. Owner: Hassan Khan.

## The ask

**Problem.** Hassan runs 15 to 20 Claude Code sessions at once across Orca
terminals, kitty tabs and tmux, plus Codex and Claude workers on laptop2 through
`orca serve`. Sitting back down, he cannot tell what each session is for, what it
is doing, who is talking to whom, or which ones are dead weight. The fleet board
and menu bar answer a different question, "who needs me now", and see only 5 of
the 16 local sessions because they key on kitty window ids.

**Proposal.** One browser page, the fleet map, that shows every agent session on
both machines as a node, grouped by initiative, with lines for agent-to-agent
traffic. Clicking a node shows its purpose, what it is doing, and two ages: since
Hassan last spoke to it, and since it last acted. Peek, jump, send a line and
close work from the map, including on laptop2. It extends nekotron and replaces
nothing.

**Your judgment.** Approve the design as written, or name what to change. The
decisions you made in the brainstorm are Decisions 1 to 6, 11, 14 to 20.
Decisions 7 to 10, 12, 13, 21 and 22 are my calls, on reviewer questions and on
how your process and the lab repo fit in; they are the ones most worth a second
look.

## What you will see

Tomorrow morning you press the fleet map keybind. A page opens with two regions,
this Mac and laptop2. Inside, sessions sit in labeled clusters: PR 6869 review,
Commissions, Handoff scheduling, and Unsorted for the two untitled lookdown
sessions nobody has claimed.

Handoff Project is blue and pulsing, so it is acting right now. Its ring is a
third full: you last wrote to it eight hours ago. A bright line runs from it to
PR Review and a dimmer one crosses into laptop2 to chief-probe, so it has been
dispatching work. You click it. The rail reads:

- **Purpose:** "Review PR 6869 under Engineering OS run 20261007" (your first
  message to it).
- **Doing now:** running `gate:ratchet` (its last tool call).
- **You:** 8h ago. **It:** 40s ago.
- **Where:** Orca, worktree lookdown, branch `DMHoodoo/pr-6869-review-chief`.
- **Talking to:** PR Review (2 messages), laptop2 chief-probe (1 dispatch).
- **Last moves:** five lines, newest first.
- **Actions:** Peek, Jump, Send a line, Close.

Commissions Audit is a gray, hollowed node with a solid gray ring: idle three
days on both counts. You click Close. A confirm names the Orca terminal it will
close and says the transcript stays resumable. You confirm, and the node goes.

### The same morning, for a big run

The Handoff scheduling cluster on laptop2 carries one extra line in its header:
three seven-dot steppers, one per slice, all at Implementing, and "waiting on
you: 1". You click the cluster. It expands in place into a gate matrix: slices as
rows, the process's stages as columns (Goal, Design, Plan, Implementing, Review,
Delivery, Accepted), each cell holding that stage's evidence. The three Goal,
Design and Plan cells read "pass 10-19". The Implementing cells hold a bar of
package segments sized S, M, L and colored by dispatch state. The Live column
holds the same worker nodes as the map, small. You click the P06 segment: the
rail shows its branch, head, checkpoint evidence, independent verifier, what it
holds, and the laptop2 session running it, with Peek and Jump.

The One-offs cluster expands the same way, but its ladder is four rungs: Asked,
Working, PR, Merged, derived from git and GitHub. The core-lint session sits at
PR with "6962 ready, green". Five sessions you never prompted sit at Asked with a
"close all 5" control.

## How the goals are met

| Goal | Mechanism | Limit |
|---|---|---|
| Every live session on both machines appears | Local sessions come from the Claude session registry, not the terminal. laptop2 terminals come from Orca. | laptop2 shows terminal-level data only in phase 1 (Decision 8). |
| Purpose, doing now, and two ages per session | Extracted from the transcript with no model calls, tailing from a saved byte offset. | Purpose is your first message verbatim, not a written summary (Decision 3). |
| Agent-to-agent traffic is drawn | Cross-session messages and subagent spawns from transcripts; Orca mail, tasks and dispatches from both machines. | Orca names terminals, not sessions; the mapping relies on the Orca pane id in each process's environment (Reference C). |
| Clusters by initiative, overridable | Inferred from Orca run, then config patterns, then worktree and branch. A config file and a rail control pin a session by hand. | Inference leaves strays in Unsorted until you name them. |
| Peek, jump, send, close from the map | Each node resolves to its host; actions route to Orca, kitty or tmux. | Close always confirms. Closing a parent ends its subagents with it. |
| Big runs show stage per slice and what waits on Hassan | A gate matrix per cluster, fed by a projection the Chief renders from its run plan (Reference H). | A run with no projection shows only its "Now" line; the map never infers a stage from activity. |
| One-offs stay in view without anyone writing status | A four-rung ladder derived from branch, commits and PR state (Reference I). | Only what git and GitHub can prove; a session with no branch sits at Asked. |
| A one-off can grow into a project | "Make a slice" moves it into a named project with a hand-set stage (Reference J). | The hand-set stage lasts until a run plan exists for it. |
| What waits on Hassan is one list | A decision strip above the map, from every projection's `decisions` and merge gate (Decision 15). | Only runs with a v2 projection contribute. |
| Memory and worker caps are visible per machine | Region headers probe memory locally and over SSH, and compare workers with caps (Decision 16). | A machine without an SSH entry shows blanks. |
| Stale evidence, stalled workers, broadcast, run plan access | Decisions 17 to 20, each a small addition to the matrix, the node overlay, the cluster header. | Stale detection needs a `headSha` in the projection; stall detection is map-side and never written back. |
| Every Chief and session takes part without being asked | The lab tool and Chief sentence (Decision 21); the `fleet-map` skill (Decision 22). | Runs pinned before the lab change keep writing by hand until re-pinned or told once. |

## Decisions

1. **Shape: a map with a detail rail.**
   - **Decision:** sessions as nodes in initiative clusters inside machine regions, traffic as lines, a rail on click. Rejected: initiative columns, roster plus wire.
   - **Why:** "what is connected to what" reads fastest as a map; the rail carries the context-recovery text.
   - **Decided by:** Hassan, 2026-10-19, brainstorm screen "layout".

2. **Age ring is "you"; the node itself is "it".**
   - **Decision:** a thin ring fills over 24h since Hassan's last message. The node pulses while acting, then hollows toward gray over hours and days since its last action. Node size is constant. Rejected: fade, bubble size, two rings.
   - **Why:** two rings turn into a wall of arcs at twenty nodes; "acting now versus gone quiet" is louder as a pulse. Fade and bubble size hide the stale sessions, which are the ones to close.
   - **Decided by:** Hassan, 2026-10-19, screens "age-and-actions" and "two-clocks".

3. **Purpose comes from the transcript, with no model calls.**
   - **Decision:** first message, last reply, last tool call, two timestamps. A model-written one-liner is a later opt-in.
   - **Why:** the raw pair is enough to place a session and costs nothing. A model line costs cents per day but needs a key and a cache.
   - **Decided by:** Hassan, 2026-10-19.

4. **Clusters are inferred, with hand naming available.**
   - **Decision:** inference order in Reference D; `~/.config/nekotron/fleet-map.json` names initiatives and pins sessions; strays go to Unsorted.
   - **Decided by:** Hassan, 2026-10-19.

5. **Investigate and close from the map, both machines.**
   - **Decision:** peek, jump, send a line, close; close confirms with the exact terminal.
   - **Decided by:** Hassan, 2026-10-19.

6. **Lives in nekotron, Python, standard library, loopback with a per-launch key.**
   - **Decision:** one program next to the fleet board; keybind and SwiftBar row to open it; no daemon when closed.
   - **Why:** same language and helpers as the rest of nekotron; the brainstorm companion already proves the loopback-plus-key pattern.
   - **Decided by:** Claude, 2026-10-19, stated to Hassan without objection.

7. **"Needs you" for sessions outside kitty.**
   - **Decision:** extend `hooks/kitty-tab-status.sh` to also write state to `/tmp/claude-kitty-status/sid-<sessionId>` before its kitty early return. The map reads that file first, the kitty file as fallback.
   - **Why:** the registry only says busy or idle, and the hook today writes nothing for Orca-hosted sessions, which are 11 of 16. Hook scripts spawn fresh per event, so live sessions pick the change up without a restart. Rejected: Orca's `agentWait` field (undocumented, null everywhere today) and transcript inference (cannot see a permission prompt, so never orange).
   - **Decided by:** Claude, 2026-10-19, after the builder check.

8. **laptop2 is terminal-level in phase 1.**
   - **Decision:** laptop2 nodes carry title, screen preview and last-output age from Orca; the rail marks them "terminal only". Reading its registry and transcripts over SSH is phase 2.
   - **Why:** laptop2's Claude files live under another user's home and are unreachable through Orca.
   - **Decided by:** Claude, 2026-10-19.

9. **What counts as Hassan speaking to a session.**
   - **Decision:** any `user` text record that is not `isMeta` and whose `turnOrigin` is `human` or absent. A line sent from the map, the kitty broadcast or `orca terminal send` by hand counts. A dispatched worker's first prompt does not, so workers wear the dotted "never addressed" ring until Hassan writes to them.
   - **Why:** those sends are Hassan's own acts; a dispatch prompt is the coordinator's. Older transcripts carry no origin field, so absent must count as human.
   - **Decided by:** Claude, 2026-10-19.

10. **Non-Claude agents and plain shells.**
    - **Decision:** any Orca terminal with an agent identity but no Claude session (Codex and similar) is drawn as a terminal-only node. Plain shells are not drawn. Orca orchestration state is polled on this Mac and every saved environment and merged, and a line may cross regions.
    - **Why:** the first goal says every agent session; the local worker list already holds dispatches whose terminals are on laptop2.
    - **Decided by:** Claude, 2026-10-19.

11. **Run tracking is a gate matrix inside the cluster.**
    - **Decision:** clicking a run-backed cluster expands it in place into a matrix: slices as rows, stages as columns, evidence in the cells, live nodes in the last column. Collapsed, the cluster header shows a seven-dot stepper per slice and "waiting on you: N". Rejected: slice bars in the header only, a run lane of segments, a stage board, an outline. A run whose sessions span both machines has a cluster in each region, but one matrix: it opens in the region holding the Chief's terminal; the other region's cluster shows the stepper header and a "matrix on <host>" link. The Live column draws every worker wherever it runs, each with a host tag, and the Chief node sits in the matrix header.
    - **Why:** it answers "what passed, when, what's left" without a click, and keeps the map as the map.
    - **Decided by:** Hassan, 2026-10-19, screens "run-card" and "project-slice-stage".

12. **Stages are the process's gates, and progress is evidence, not activity.**
    - **Decision:** the seven stages are Goal, Design, Plan (readiness), Implementing, Review, Delivery, Accepted, in that order. A package has a dispatch state: planned, assigned, running, returned, verified, blocked. The only number shown is verified units of total, weighted S=1, M=2, L=3. No fractional credit for running or checks. Columns map to the projection as: Goal, Design, Plan and Delivery each to the gate of that id; Review to the four gates `test-quality, code-standards, commenting, general-code`, drawn as four verdict chips; Implementing to the row's packages; Accepted to `acceptance`. Proofs have no column; they show in the cluster header and the rail. A run-level gate fans out to every slice row unless the slice carries its own gate with the same id. A run with no slices has one row named after the run, so review-only runs still get a stepper and a matrix.
    - **Why:** the Engineering OS process marks completion from evidence and required review, and names activity, task counts and green checks as what readiness is not.
    - **Decided by:** Claude, 2026-10-19, from `engineering-os-lab/process.md` and `roles/chief.md`; shown to Hassan on the "run-card" screen.

13. **The run plan stays the single record; the map reads a projection of it.**
    - **Decision:** the run plan carries the progress data itself, as exactly one fenced `json run-status` block anywhere in the file; the Status card section is the recommended place, and a plan with zero or two such blocks fails the export. The lab tool `run-status.py` (Decision 21) extracts that block, validates the Engineering OS-owned schema summarized in Reference H, stamps the plan commit and worktree, and writes `run-status.json` beside the plan atomically. The map reads only integer `schemaVersion: 2` records through configured progress providers; an absent or rejected record leaves the Orca objective and a diagnostic. The map never translates older shapes and never parses run plans. The lab validator is normative field for field.
    - **Why:** the process forbids a status document beside the run plan, so the block lives inside it. Translating the existing v1 file would mean inventing a mapping for its fractional statuses, which Decision 12 rejects.
    - **Decided by:** Claude, 2026-10-19, after the builder check; the Handoff Project Chief session is sent Reference H once Hassan approves this addition.

14. **One-offs get an automatic ladder, and promotion by hand.**
    - **Decision:** clustering stays as Reference D. Any cluster with no run projection expands into the ladder view for its sessions, so "Commissions" and a per-branch cluster get ladders too. A session with no human prompt is never clustered by worktree; it goes to Unsorted, and Unsorted alone carries the "never prompted, close all N" row. "Make a slice" writes both the `assign` pin (cluster) and the `projects` entry (stage), one store from the rail's point of view; "move to…" on a promoted session rewrites the pin and drops the `projects` entry when the target is not a project. Precedence for cluster and stage: run projection, then `assign` and `projects`, then `match`, then worktree, then Unsorted. When a projection names a pinned session, the session moves to the run's cluster and the rail shows the pin as overridden.
    - **Why:** free and honest for the many small sessions; one piece of hand-kept state for the few that grow.
    - **Decided by:** Hassan, 2026-10-19, screen "one-offs".

15. **A decision inbox across runs.**
    - **Decision:** a strip above the map lists every open class-C and class-D item and every unratified class-B default from all projections, with its run, packet and apply-by time, class-B items ordered by apply-by. Clicking one opens that run's matrix and rail. The cluster header's "waiting on you: N" counts the same items.
    - **Why:** these block every Chief and today live in four separate run plans.
    - **Decided by:** Hassan, 2026-10-19 13:29 PDT.

16. **Worker caps against memory, per region.**
    - **Decision:** each region header shows free memory percent, swap used, and running workers against the cap. Local probes: `vm_stat`, `sysctl hw.memsize`, `sysctl vm.swapusage`. A remote region probes the same over SSH using the host from the config's `hosts` map (Reference J). A running worker is an Orca dispatch from `worker-list`, on any host's list, whose `agentTerminalHandle` is in that region's terminal list and whose `workerState` is not settled, released or abandoned; the worker record's own `host` field is ignored because it reports `local` for laptop2 workers. The cap comes from the projection's `caps` for that host, else the config's `caps`, else none. The header turns amber when workers exceed the cap or free memory is under 40 percent, the thresholds the handoff run plan uses. An unreachable probe shows blanks.
    - **Decided by:** Hassan, 2026-10-19 13:29 PDT.

17. **Stale evidence flag.**
    - **Decision:** a passed gate that carries a `headSha` is compared with the current head: for the run, `gh pr view <pr.number> --repo <pr.repo> --json headRefOid`; for a slice with a `branch`, `git ls-remote origin <branch>` run in `runPlan.worktree`. If the head moved, the cell shows "evidence stale". The rail lists the commits since only when `runPlan.worktree` already holds them; otherwise it says "head moved, commits not fetched". The map never runs `git fetch`. Without a `headSha`, or without both a PR and a branch, no check and no flag. Results are cached for 60 s.
    - **Why:** PR 6869's head moved three times during its review.
    - **Decided by:** Hassan, 2026-10-19 13:29 PDT.

18. **Stalled workers.**
    - **Decision:** a `claude` or `terminal` node that is `working` by state but whose transcript offset and terminal `lastOutputAt` have both been unchanged for 10 minutes, the watchdog's default stall window, is drawn `stalled`: the working fill with a hatched overlay. The cluster header counts them. Not a fifth state in the projection; a map-side overlay.
    - **Decided by:** Hassan, 2026-10-19 13:29 PDT.

19. **Broadcast to a cluster.**
    - **Decision:** a "Send to all" control in the cluster header sends one line to every `claude` node in the cluster through the action router; terminal-only nodes are included only when a checkbox says so. The confirm names the count and the hosts.
    - **Decided by:** Hassan, 2026-10-19 13:29 PDT.

20. **Open the run plan's Resume here.**
    - **Decision:** a cluster with a projection has an "Open run plan" control that opens `runPlan.worktree/runPlan.path` and opens it with nekotron's `bin/md-preview` in a kitty overlay, scrolled to "Resume here".
    - **Decided by:** Hassan, 2026-10-19 13:29 PDT.

21. **Engineering OS owns the run-status record; nekotron plugs into it.**
    - **Decision:** `engineering-os-lab/tools/run-status.py --run-plan <path> [--out <file>]` extracts the fenced `json run-status` block, validates the Engineering OS-owned schema version 2, stamps `runPlan.commit` from the plan's last Git commit and `runPlan.worktree` from the checkout root, and atomically writes `run-status.json` beside the run plan by default. It exits 1 and names the field on a violation. The lab's validator is the schema authority; nekotron vendors it in `projection.py` and consumes records through its Engineering OS progress provider. The Engineering OS workflow names no consumer and requires no nekotron output path. The Chief refreshes the record after each run-plan update; older pinned runs must adopt the new exporter and fence.
    - **Why:** the run plan stays the single record, Engineering OS owns its export, and each consumer chooses how to discover it.
    - **Decided by:** Task 23 dependency inversion, 2026-10-20, superseding the original consumer-specific renderer integration.

22. **A `fleet-map` skill for sessions.**
    - **Decision:** `nekotron/claude/skills/fleet-map/SKILL.md`, installed like the other nekotron Claude assets, tells a session how to read the map: find `~/.config/nekotron/fleet-map.server.json`, call `GET /api/state` with the key, and interpret nodes, edges, clusters and decisions. Read-only; actions stay with the human in the page.
    - **Decided by:** Claude, 2026-10-19, same basis as Decision 21.

## Out of scope

- Replacing the fleet board, menu bar or Orca's sidebar.
- History, replay or analytics. The map shows now, with the last few moves.
- A daemon. The process lives while the page is open and exits after 30 minutes with no page connected.
- Reading whole transcripts every refresh.
- Any listener beyond loopback, or one without a key.
- Later: the opt-in model one-liner, phase 2 laptop2 data over SSH, collapsing a cluster to one node.

## Reference

The builder reads this part. Each item is the authoritative statement of the
mechanism named above.

**Where each part lives**

- A: `kitty/fleetmap/page.html`.
- B: `kitty/fleetmap/transcript.py`.
- C: `kitty/fleetmap/registry.py` and `kitty/fleetmap/orca.py`.
- D: `kitty/fleetmap/clusters.py`.
- E: `kitty/fleetmap/edges.py`.
- F: `kitty/fleetmap/actions.py`.
- G: `kitty/fleetmap/server.py` and `bin/fleet-map`.
- H: `kitty/fleetmap/providers/engineering_os.py` consumes the schema owned by `tools/run-status.py` in the `engineering-os-lab` repository, branch `fleet-map-progress`, commit `f752803`; `kitty/fleetmap/projection.py` vendors its validator (Decision 21).
- I: `kitty/fleetmap/ladder.py`.
- J: `kitty/fleetmap/clusters.py`.
- Decision 7: `hooks/kitty-tab-status.sh`.
- Decision 12: `kitty/fleetmap/matrix.py`.
- Decisions 15 to 18: `kitty/fleetmap/signals.py`.
- Decisions 19 and 20: `kitty/fleetmap/actions.py` and `kitty/fleetmap/page.html`.
- Decision 22: `claude/skills/fleet-map/SKILL.md`.
- Per-run worker collection and Resume here paging (Task 18 fix rounds): `kitty/fleetmap/model.py` and `bin/md-preview`, respectively.
- Stage-only route and `never_prompted` flag (Task 19 fix rounds): `kitty/fleetmap/server.py` and `kitty/fleetmap/model.py`, respectively.
- Host reachability degradation and the subagent window (Tasks 7b, 7c): `kitty/fleetmap/model.py`.
- Full-width layout (Task 10b): `kitty/fleetmap/page.html`.
- Orca binary fallback: `kitty/fleetmap/orca.py` and `bin/fleet-map`.

### A. Node and line encoding

- Fill color is state, the fleet board's four: working blue, done green, needs you orange with a glow, idle gray.
- "It" age: pulsing while working; solid when it acted within the hour; hollowing from the center toward gray over hours and days.
- "You" age: ring fills clockwise over 24h; solid gray after a day; dashed after a week; dotted when never addressed.
- Subagents are smaller nodes joined to their parent by a short line.
- A traffic line is bright when its newest message is under 10 minutes old and fades over an hour.
- `stalled` is an overlay on a working node: the working fill with a diagonal hatch (Decision 18).
- A legend on the page explains every encoding.
- The rail shows: purpose, doing now, both ages in words, repo, worktree, branch, host (Orca, kitty, tmux, laptop2), model, context percent and cost when known, partners with message counts, the last five moves newest first, the action row, and a "move to…" control for the cluster.

### B. Transcript fields

| Field | Source record |
|---|---|
| Title | `ai-title`, else the registry `name` |
| Purpose | first `user` record with text content, not `isMeta`, not a tool result |
| Doing now | last `assistant` `tool_use` (tool name plus a short argument), else the last `assistant` text |
| Last said | last `assistant` text block |
| You age | last `user` text record per Decision 9 |
| It age | last `assistant` record or `user` tool result |

The reader stores a byte offset per transcript and parses only what was appended. The first open of a large transcript reads it once in full.

### C. Hosts and data paths

This Mac:

- Sessions: `~/.claude/sessions/<pid>.json` gives name, status, cwd, sessionId, startedAt, statusUpdatedAt. Live when `kill -0 pid` succeeds.
- Transcripts: `~/.claude/projects/<cwd-slug>/<sessionId>.jsonl`. Subagents: `<project>/<sessionId>/subagents/agent-*.jsonl` with `.meta.json`.
- Orca terminals: `orca terminal list --json` gives handle, title, worktreePath, branch, connected, lastOutputAt, tabId, leafId, agentIdentity.
- Terminal to session: each Orca-launched Claude process has `ORCA_AGENT_PANE=<tabId>:<leafId>` in its environment. Fallback: the process walk in `bin/kitty-to-orca`.
- tmux: `fleet_tmux.sessions()` for `neko-*` sessions.
- kitty: state and context percent from `/tmp/claude-kitty-status` as today, plus the `sid-<sessionId>` files from Decision 7.

laptop2, through `orca --environment laptop2`: `terminal list --json` and `terminal read --screen`. State is working when output is under a minute old, else idle.

### D. Clusters

Inference order, first match wins:

1. The Orca orchestration run the terminal is bound to; the run description names the initiative.
2. A `match` pattern in the config.
3. Worktree path and branch; sessions in one worktree share a cluster named after the branch. Only sessions with at least one human prompt.
4. Unsorted.

A session named by a run projection (Reference H, through its package `dispatchId` or `chiefTerminal`) joins that run's cluster ahead of every rule above.

`~/.config/nekotron/fleet-map.json`:

```json
{
  "initiatives": [
    {"name": "PR 6869 review", "match": ["pr-6869", "lookdown"]},
    {"name": "Commissions", "match": ["commission", "compensation"]}
  ],
  "assign": {"local:sid:<sessionId>": "Commissions", "env:laptop2:term:<handle>": "Handoff scheduling"}
}
```

`match` entries are case-insensitive substrings tested against title, purpose, worktree path and branch. `assign` pins one node by its node id and beats everything below it; a bare session id is accepted as `local:sid:<id>`. Terminal-only nodes can be pinned and promoted by their handle, which is stable for the terminal's life. The rail's "move to…" control writes to `assign`.

### E. Traffic edges

| Edge | Source |
|---|---|
| Cross-session, outbound | `SendMessage` `tool_use` records; `input.to` resolved against registry names and agent ids |
| Cross-session, inbound | `user` records containing `<cross-session-message from="…">` |
| Parent to subagent | the subagent files in C |
| Orca orchestration | `orca orchestration inbox --json` (from_handle, to_handle, run_id), `task-list`, and `worker-list` (maps `dispatch:` handles to terminals); polled locally and per saved environment, merged |

### F. Actions

| Action | Orca, either machine | kitty | tmux |
|---|---|---|---|
| Peek | `orca terminal read --screen` | `get-text` | `tmux capture-pane` |
| Jump | `orca terminal switch` | `fleet-jump <window>` | attach in kitty |
| Send a line | `orca terminal send` | `send-text` | `tmux send-keys` |
| Close | `orca terminal close` | `close-window` | `tmux kill-session` |

The close confirm names the host, the terminal handle or window, and that the transcript remains resumable. Closing a parent does not separately close its subagents; they end with the process.

### G. Process and launch

- One Python 3 program under `kitty/` or `bin/`, standard library only, one HTML page over loopback, random per-launch key in the URL.
- The page polls a JSON endpoint every 3 seconds while visible and stops when hidden. The server exits after 30 minutes with no page connected.
- A new keybind in `kitty/nekotron.conf` and a "Fleet map" row in the SwiftBar menu run one launcher that reuses a running server.
- Cluster and node positions come from a deterministic packing, keyed by session id and kept for the life of the server, so nodes do not jump between refreshes.

### H. Run projection

The run plan holds one fenced block, opened with ```` ```json run-status ````, in its Status card section. Engineering OS owns this schema and its authoritative `validate()` in `tools/run-status.py`. That exporter (Decision 21) writes `run-status.json` beside the plan by default, stamping `runPlan.commit` and `runPlan.worktree`; `--out <file>` optionally selects another output. Writes are atomic (temp file, then rename). Nekotron vendors the validator and reads this record through progress providers; it does not define the Engineering OS workflow or export destination. Every field below is required unless marked optional; lists may be empty.

With no `providers` key in `~/.config/nekotron/fleet-map.json`, the map enables exactly the Engineering OS provider with no extra roots. On each snapshot refresh it searches the deduplicated local nodes' worktree roots plus configured extra roots, using only `run-status.json`, `*/run-status.json`, and `engineering-os/*/run-status.json`. It never traverses a symlink outside its root, searches deeper, or reads a remote host's worktree. Each file is read independently, with content and modification time from the same open file. Only integer `schemaVersion: 2` records passing the lab validator are accepted; rejections are keyed by file path in `rejected_projections`.

Each configured provider key enables that provider. `~` expands in paths; an unknown provider produces a config note and leaves known providers enabled. An explicit empty object disables all providers. The optional directory provider supports existing `--out` users by reading every top-level `*.json` in its directory, retaining filename-based rejection labels:

```json
{
  "providers": {
    "engineering_os": {"roots": ["~/orca/workspaces/glow-core/lookdown"]},
    "directory": {"path": "~/.glow/orca-progress"}
  }
}
```

The provider results and rejection diagnostics are merged. For duplicate `run` IDs, the newer `updatedAt` wins; the discarded source is marked `superseded` under `<provider-name>:<file-path>`. ISO timestamps are compared as instants; an unparseable timestamp ranks oldest, and ties retain the first source. The map matches selected records to Orca's existing run list. Provider construction uses the launch configuration; restart the map after changing provider settings. Local discovery roots and record contents refresh on every snapshot without new Orca or network calls on the fast thread.

```json
{
  "schemaVersion": 2,
  "run": "run_4d94eb181d65",
  "title": "Handoff scheduling",
  "updatedAt": "2026-10-19T20:15:53Z",
  "runPlan": {"path": "engineering-os/20261015-handoff-scheduling/run-plan.md", "commit": "0eb10688f1",
              "worktree": "/Users/hassankhan/Documents/GlowDevelopment/glow-core/.claude/worktrees/handoff-scheduling"},
  "pr": {"repo": "TuleInc/glow-core", "number": null},
  "acceptance": {"state": "pending", "at": null, "by": null},
  "chiefTerminal": "term_c585d3a9-91d2-4e9e-a368-2016d2b3b47b",
  "now": "wave 1 running on laptop2; wave 2 starts when P00 pushes",
  "statusCard": {"done": "requirements accepted; designs passed", "running": "P00, P02, P04, P05 on laptop2",
                 "blockedOn": "nothing now", "nextCheckpoint": "P00 push, then wave 2"},
  "decisions": [{"id": "E3", "class": "C", "text": "run the E3 calendar check after P04 lands",
                 "packet": "Decision packet 4", "applyAt": null}],
  "gates": [{"id": "goal", "verdict": "pass", "at": "2026-10-19", "ref": "goal-review-2.md", "headSha": null}],
  "mergeGate": {"ready": false, "classDOpen": 0, "classBUnratified": 2},
  "proofs": [{"id": "E4", "status": "pass"}],
  "caps": {"laptop2": 7},
  "slices": [{"id": "1", "name": "Statuses and history", "stage": "implementing", "branch": null,
              "gates": [{"id": "design", "verdict": "pass", "at": "2026-10-19", "ref": "design-slice1.md", "headSha": "a1b2c3d"}],
              "packages": ["P00", "P01", "P06", "P13a", "P13b", "P14", "P15", "P16"]}],
  "packages": [{"id": "P06", "slice": "1", "title": "Outcomes and ownership", "size": "L",
                "state": "running", "dispatchId": "ctx_64ec1a2ee6d8", "machine": "laptop2",
                "branch": "hok/handoff-l2-p06-outcomes", "headSha": "1e87221", "blockedBy": [],
                "proofs": ["E5"], "checkpointEvidence": "E5 ownership chain proof",
                "verifier": "Fable review before merge",
                "lastEvent": "checks started", "lastEventAt": "2026-10-19T20:15:53Z"}]
}
```

Vocabulary: `stage` is one of `goal, design, plan, implementing, review, delivery, accepted`. Package `state` is one of `planned, assigned, running, returned, verified, blocked`. `verdict` is `pass, revise, pending`. Decision `class` is `B, C, D`; `applyAt` is an ISO 8601 time for class B defaults, else null. Gate `id` is one of `goal, design, plan, test-quality, code-standards, commenting, general-code, delivery`. `runPlan.worktree` is the absolute path of the checkout holding the plan; the tool fills it from its own working directory. `pr.number` is null until a PR exists. `acceptance.state` is one of `pending, accepted, merged`. Optional fields: `pr.number`, `acceptance.at`, `acceptance.by`, `caps`, `slices[].branch`, `gates[].headSha`, `gates[].ref`, `decisions[].packet`, `decisions[].applyAt`, `packages[].headSha`, `packages[].lastEvent`, `packages[].lastEventAt`. A package's `dispatchId` links to its worker node through Orca's worker list; `chiefTerminal` links to the Chief node through the terminal lists of every host.

### I. One-off ladder

For a `claude` node with no run and no promotion, from its worktree:

| Rung | Condition |
|---|---|
| Asked | default; also when the worktree has no branch or no commits ahead of the repo's default branch |
| Working | `git rev-list --count <default>..HEAD` is above zero |
| PR | `gh pr list --head <branch> --json number,state,isDraft,statusCheckRollup` returns an open PR; the cell shows number, draft flag and checks |
| Merged | that PR's state is `MERGED` |

Results are cached per branch for 60 s. A node whose transcript has no human prompt is "never prompted" and listed in a closing row at the bottom of the Unsorted cluster (Decision 14).

### J. Promotion

`~/.config/nekotron/fleet-map.json` gains:

```json
{"projects": [{"name": "Core lint speed",
               "slices": [{"name": "root cause 6962", "stage": "review", "sessions": ["local:sid:…"]}]}],
 "hosts": {"laptop2": {"ssh": "hok@Hassans-MacBook-Pro.local"}},
 "caps": {"laptop2": 7, "local": 3}}
```

`hosts` supplies the SSH target for remote memory probes (Decision 16); `caps` supplies worker caps when a projection has none.

"Make a slice" in the rail writes one entry. A slice's `stage` is edited from the rail. When a run projection names the same sessions, the projection wins and the hand-set stage is ignored.

## Left to the builder

- The packing algorithm, as long as positions are stable across refreshes.
- Exact pulse and hollowing curves; the legend describes whatever is chosen.
- How much of a very large transcript to read on first open.
- Tests in the existing `tests/` style for the transcript reader, the edge resolver and the cluster matcher. The server and page are exercised by hand.
- The keybind; `⌘⇧F` is taken.
- The matrix's expand and collapse animation and how it displaces neighboring clusters, as long as positions stay stable afterward.
- The decision strip's layout when it holds more than a handful of items.

## Revision 2026-10-20: declutter

Hassan reviewed the merged board (nekotron master 8668078) on 2026-10-20 06:59 PDT and found it cluttered: raw objectives as cluster names, truncated node labels, zero counts and a Send to all button on every cluster, a permanent legend, dispatch edges across the whole screen, and no progress bars in the collapsed cluster. He chose items 1 to 5 of the proposed fixes at 07:01 PDT. These decisions amend the ones above; where they conflict, the newer decision wins.

- **Decision 23 (collapsed run cluster).** A collapsed run-backed cluster shows: the cluster's short name; the Chief's Now line (`run.now`); one row per slice with the slice name, the package segment bar from the matrix's Implementing cell, and the text `verified n of m units`; and the line `waiting on you: N · M stalled` only when N or M is nonzero. The seven-dot stepper and the proofs line move into the expanded matrix (stepper as the first column, proofs under the table). The segment bar in the collapsed view is the same element as in the matrix cell, so a click on a segment opens the package in the rail exactly as it does there. This restores the "three slice bars" of the run-card mockup Hassan approved on 2026-10-19, which Decision 12 had dropped.
- **Decision 24 (names).** A cluster carries `short_name`, computed server-side: the initiative name when the cluster is a promoted initiative or a run projection title; otherwise the first five words of the objective or purpose, ending with an ellipsis when truncated, never a commit hash, an Orca id or a pasted-content tag (a leading `<...>` tag and any token of at least 32 hexadecimal digits are skipped; Orca run and terminal ids are 64 hex digits, Git hashes 40). The full name stays in `name` and is the heading's hover title. Node labels show up to two lines of 11 characters, breaking at a space when one exists in the first 22 characters; the full title is the hover title. Label precedence is unchanged (hand name, then session title, then purpose, then id).
- **Decision 25 (hide zeros, Send to all in the rail).** The cluster heading carries only the caret and the short name. Clicking the name selects the cluster: the rail shows the cluster card (full name, host, run link when any, counts, and the Send to all button). The caret alone expands and collapses. The counts line is omitted when both counts are zero.
- **Decision 26 (legend on demand).** The legend is closed by default behind a `?` button in the header. Its open state is remembered in `localStorage` under `fleetmap.legend` and restored on load; the key is read inside a try block so a blocked store leaves it closed.
- **Decision 27 (edges on focus).** Message and dispatch edges are drawn only for the selected node and the hovered node, in both directions. Every other node with at least one such edge shows a small count badge at its upper right (the number of edges, capped at the display `9+`). Subagent links (the short parent lines) are unchanged. Edge age fading applies as before to the edges that are drawn.
- **Decision 28 (decision card), 2026-10-20 10:07 PDT.** Hassan found the decision strip confusing: a chip is one long string and clicking it only opens the run's matrix. A chip now reads as three lines: the run title; the item's text; `Class C · E3 · apply-by —`. Clicking a chip opens the run's matrix as before and shows a decision card in the rail: the full text; the packet name; the class and apply-by; the Chief node as a mini node with Jump and Send; a `Reply to Chief` button that opens the existing send overlay for the Chief node with the text field prefilled `Decision E3: ` (the item id); and `Open run plan`, which uses the existing open-plan action for the run. The map records nothing about the decision itself: it clears when the Chief's projection drops it, and the card says so in one muted line ("Clears when the Chief records it").

## Revision 2026-10-20 (second round): first screen, find, hover, rail, ghosts, boxes

Claude walked the merged board as a first-time user at 1512x900 on 2026-10-20 10:40 PDT: 18 of 22 sessions were below the fold, nothing summarized the fleet, there was no search, the hover showed the whole first prompt, the rail led with the run card and the prompt, five retained Orca worker terminals showed as idle sessions, and clusters were named after branches. Hassan approved this round at 10:44 PDT.

- **Decision 29 (header summary and state filter).** The header line reads `N sessions · a working · b need you · c idle · updated …` where "need you" counts nodes in the attention state and idle counts idle plus done. Each count is a toggle: on, the map dims every node not in that state to 25% opacity and dims clusters with no matching node; off restores. One filter at a time; clicking the active one clears it. The region header reads a status word before the numbers: `OK` when free memory is at or above 40% and workers are within cap, `Tight` when free memory is below 40%, `Over cap` when workers exceed the cap; the amber color rule is unchanged.
- **Decision 30 (fold idle sessions).** A cluster folds every node that is idle or done and whose newer of `you_at` and `it_at` is older than 24 hours into one chip, `k idle`, drawn where the first folded node would have been. Clicking the chip unfolds that cluster until the page reloads; a folded cluster with no other nodes shows only the chip. Never-prompted nodes fold too. A working, attention or stalled node never folds. The state counts in Decision 29 count folded nodes.
- **Decision 31 (search).** A search box in the header (placeholder `Find a session`, focused by the `/` key when no input has focus) matches, case-insensitively, a node's title, purpose, doing, last said, repository and branch. While the query is non-empty every non-matching node dims to 25% and every matching node is unfolded and drawn at full opacity with its label; the status line appends `· m match`. Escape clears the box. Search and the state filter combine (both must match).
- **Decision 32 (hover card).** A node's hover title is at most five lines: the title; `Doing: …` when present; `Said: …` when present, each cut to 80 characters with an ellipsis; `You: 2h · It: 5m` from the ages; and the repository and branch. The first prompt never appears in the hover.
- **Decision 33 (rail order and vocabulary).** For a node the rail shows, in order: the title; a one-line state (`working · pulsing 5m`, `needs you`, `idle 3d`, `done 2h`, `stalled`); `Doing`; `Said`; `You` and `It` ages; the action buttons; the run or ladder card; then the purpose inside a collapsed disclosure labeled `First prompt`. An action that is unavailable is omitted, never shown disabled or with an "unavailable" label; the parent link appears only when the parent exists. Button labels: `Peek`, `Jump`, `Send`, `Close`, `Add to a project` (was Save slice / stage), `Move to another box` (was Move session). The Peek overlay, when the screen is empty, states the reason in one line: `No terminal is bound to this session`, `laptop2 is unreachable`, or `The terminal returned nothing`.
- **Decision 34 (retired worker terminals).** An Orca terminal whose worker-list record says the dispatch is released, abandoned, failed or succeeded and whose terminal is retained is a retired worker. Retired workers never appear as nodes; each cluster that has any shows one chip, `k retired workers`, which lists them in the rail when clicked (title, dispatch state, how long retained). The host's worker count excludes them and the region shows `workers/cap` from live workers only. A terminal with a live agent process is never retired.
- **Decision 35 (boxes by repository).** A node that no run, initiative, pin or promoted project claims is clustered by repository, not by branch. The repository identity is the basename of the directory that holds the worktree's common git directory (`git rev-parse --git-common-dir`, resolved once per worktree root in the slow thread and cached), so every worktree of glow-core joins one `glow-core` box; a node with no repository goes to `Unsorted`. The box's full name is the repository name; the branch stays on the node and in the hover card. Decision 14's branch rule is withdrawn for display; its worktree-root grouping remains the basis for the repository lookup.

## Revision 2026-10-20 (third round): readability across window sizes

Claude captured the merged board at 390x844, 768x1024, 1280x800, 1512x900, 1920x1080 and 2560x1440 on 2026-10-20 14:40 PDT. It read well from 1280 to 1920 wide. Below about 1000 px the empty rail covered half the map; at 2560 the text was small and most of the screen empty. Boxes were far taller than their contents, raw hex ids filled Now lines, a long box name dropped below its caret, and the decision chip did not stand out. Hassan approved this round at 14:55 PDT.

- **Decision 36 (rail on demand).** With nothing selected the rail is hidden and the map takes the full width. Selecting a node, cluster, package or decision opens it; Escape (when no dialog is open and the search box is empty) and a close button in the rail's top corner close it. At widths of 1000 px or more the rail sits beside the map as today; below 1000 px it opens as an overlay sheet from the right, 90% of the width, over a dimmed map, and closing it returns the full map. Below 700 px the header wraps onto two lines: title and counts first, search box and `?` second, and the search box is never pushed off screen. Below 700 px the host regions stack vertically, each at the full viewport width, and box text wraps inside the viewport so nothing needs horizontal scrolling.
- **Decision 37 (boxes fit their contents).** A cluster box is as tall as its panel content plus its node rows plus padding, with no fixed minimum beyond the heading and one node row. Clusters pack in the region's grid by their actual heights. Position stability across refreshes with unchanged content is preserved.
- **Decision 38 (heading on one line).** The caret and the box name share one line; a long name wraps beside the caret with the caret aligned to the first line, never alone on a line above the name.
- **Decision 39 (short ids in text).** In any Now line, fallback note or rail text, a token of 32 or more hex digits is shown as its first 8 characters followed by `…`; the full text stays in the hover or title attribute of that line.
- **Decision 40 (decision chip stands out).** A decision chip uses the attention color for its border and a leading dot, and the strip's label reads `Needs you` with the count (`Needs you · 1`). With no open decisions the strip collapses to one muted line, `Nothing needs you`.
- **Decision 41 (large screens).** At widths of 2200 px or more the page's base font size steps from 12 px to 14 px and node radii scale by the same ratio, so text and nodes keep their apparent size on a 1440p display.

## Revision 2026-10-21: status comes from the run plan

On 2026-10-20 the Handoff run's map view sat 16 hours stale: its Chief kept the progress JSON by hand and lost the helper that refreshed it, and when it rewrote the file with gate names outside the schema the run vanished from the map with no reason shown. Hassan asked for a fix that ensures the status stays current (2026-10-20 23:59 PDT) and approved this revision (2026-10-21 06:03 PDT).

- **Decision 42 (read the block from the run plan).** The Engineering OS provider reads the fenced ```` ```json run-status ```` block directly from each `run-plan.md` it discovers under local worktree roots (globs: `run-plan.md`, `*/run-plan.md`, `engineering-os/*/run-plan.md`, same bounds and symlink rules as `run-status.json`). It stamps `runPlan.path` (relative to the repository root), `runPlan.worktree`, and `runPlan.commit` (the last commit touching the plan, via `git log -1 --format=%h -- <plan>` in the slow thread, cached by plan mtime), then validates with the vendored `validate`. A plan with no block is ignored. A plan with zero or several blocks, malformed JSON, or a validation failure is a rejected source with its reason. A `run-status.json` beside a plan is still read; when both exist for the same run, the newer `updatedAt` wins (existing superseded rule). The directory provider is unchanged. Decision 21's export step becomes optional.
- **Decision 43 (freshness on the run box).** Every run-backed cluster shows `status updated <age>` under its Now line, from `updatedAt`. The line is amber and reads `status updated <age> · plan changed since` when the run plan has a commit newer than the status's `updatedAt` (the plan's last commit time, from the same git call). With no plan commit available it shows the age only.
- **Decision 44 (rejections are visible).** A rejected source for a run whose id is known (from the file name, the block's `run` field, or an Orca run with a matching id) keeps its cluster on the map with the last good projection if one was seen in this server's lifetime, and shows a red line `status rejected: <first reason>`; with no last good projection, the cluster shows the fallback content plus that red line. Rejected sources with no known run are listed in the rail's "At a glance" view under `Rejected status files`.
