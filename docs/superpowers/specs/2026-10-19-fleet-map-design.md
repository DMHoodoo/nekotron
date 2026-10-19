# Fleet map: one board for every agent session

Date: 2026-10-19. State: design, awaiting Hassan's approval. Owner: Hassan Khan.

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
decisions you made in the brainstorm are listed under Decisions 1 to 6. Decisions
7 to 10 are my calls on questions the reviewer raised; they are the ones most
worth a second look.

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

## How the goals are met

| Goal | Mechanism | Limit |
|---|---|---|
| Every live session on both machines appears | Local sessions come from the Claude session registry, not the terminal. laptop2 terminals come from Orca. | laptop2 shows terminal-level data only in phase 1 (Decision 8). |
| Purpose, doing now, and two ages per session | Extracted from the transcript with no model calls, tailing from a saved byte offset. | Purpose is your first message verbatim, not a written summary (Decision 3). |
| Agent-to-agent traffic is drawn | Cross-session messages and subagent spawns from transcripts; Orca mail, tasks and dispatches from both machines. | Orca names terminals, not sessions; the mapping relies on the Orca pane id in each process's environment (Reference C). |
| Clusters by initiative, overridable | Inferred from Orca run, then config patterns, then worktree and branch. A config file and a rail control pin a session by hand. | Inference leaves strays in Unsorted until you name them. |
| Peek, jump, send, close from the map | Each node resolves to its host; actions route to Orca, kitty or tmux. | Close always confirms. Closing a parent ends its subagents with it. |

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

### A. Node and line encoding

- Fill color is state, the fleet board's four: working blue, done green, needs you orange with a glow, idle gray.
- "It" age: pulsing while working; solid when it acted within the hour; hollowing from the center toward gray over hours and days.
- "You" age: ring fills clockwise over 24h; solid gray after a day; dashed after a week; dotted when never addressed.
- Subagents are smaller nodes joined to their parent by a short line.
- A traffic line is bright when its newest message is under 10 minutes old and fades over an hour.
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
3. Worktree path and branch; sessions in one worktree share a cluster named after the branch.
4. Unsorted.

`~/.config/nekotron/fleet-map.json`:

```json
{
  "initiatives": [
    {"name": "PR 6869 review", "match": ["pr-6869", "lookdown"]},
    {"name": "Commissions", "match": ["commission", "compensation"]}
  ],
  "assign": {"<sessionId>": "Commissions"}
}
```

`match` entries are case-insensitive substrings tested against title, purpose, worktree path and branch. `assign` pins one session by id and beats everything. The rail's "move to…" control writes to `assign`.

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

## Left to the builder

- The packing algorithm, as long as positions are stable across refreshes.
- Exact pulse and hollowing curves; the legend describes whatever is chosen.
- How much of a very large transcript to read on first open.
- Tests in the existing `tests/` style for the transcript reader, the edge resolver and the cluster matcher. The server and page are exercised by hand.
- The keybind; `⌘⇧F` is taken.
