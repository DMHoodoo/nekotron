# Fleet map: one board for every agent session

Date: 2026-10-19. Status: design, awaiting approval.

## Intent

Hassan runs 15 to 20 Claude Code sessions at once across Orca terminals, kitty
tabs and tmux, plus Codex and Claude workers on a second laptop reached through
`orca serve`. Sitting back down, the question is not "who needs me" (the fleet
board and menu bar answer that) but "what is each session for, what is it doing,
who is talking to whom, and which ones are dead weight".

The fleet map is one browser page that answers those four questions for both
machines at once, and lets him act on a session (peek, jump, send a line, close)
without finding its terminal first.

## Goals

- Every live agent session on this Mac and laptop2 appears, regardless of which
  terminal hosts it. Today the fleet board sees 5 of 16 local sessions because it
  keys on kitty window ids.
- Each session reads as a one-line purpose plus "doing now", with two ages: time
  since Hassan last spoke to it, and time since it last acted.
- Agent-to-agent traffic is drawn: cross-session messages, Orca orchestration
  mail and dispatches, parent-to-subagent.
- Sessions cluster by initiative, inferred by default, overridable by hand.
- Close, peek, jump and send work from the map, including for laptop2.

## Non-goals

- Replacing the fleet board, menu bar or Orca's sidebar. They stay.
- Historical replay or analytics. The map shows now, with short recent context.
- A model-written purpose sentence. The free transcript extraction ships first;
  a model one-liner is a later opt-in (see "Later").

## Anti-goals

- A daemon that runs when the map is closed. Nekotron has none; the map's
  process lives while the page is open and exits on idle.
- Reading whole transcripts every refresh. Several are tens of megabytes.
- Closing anything without a confirm that names the exact terminal or process.
- Any network listener beyond loopback, and none without a per-launch key.

## Decided

### Shape

Option B from the brainstorm: a map with a detail rail.

- Two regions side by side: this Mac and laptop2. More regions if more Orca
  environments are saved.
- Inside a region, sessions are nodes grouped into initiative clusters. Clusters
  are drawn as labeled soft outlines; an "Unsorted" cluster holds the rest.
- Subagents are smaller nodes attached to their parent by a short line.
- Lines between session nodes are traffic. A line brightens when its newest
  message is under 10 minutes old and fades over an hour.
- Clicking a node fills the rail: purpose, doing now, both ages in words,
  repo, worktree, branch, host terminal (Orca / kitty / tmux / laptop2), model,
  context percent and cost when known, partners it has exchanged messages with,
  the last five moves (tool calls and replies, newest first), and the action
  row.
- A legend explains every encoding. Nothing depends on memory.

### Node encoding

- Fill color is state, the same four as the fleet board: working (blue), done
  (green), needs you (orange, glowing), idle (gray).
- "It" age (time since the session's last tool call or reply) is the node
  itself: pulsing while working, solid when it moved within the hour, then
  hollowing from the center toward gray over hours and days.
- "You" age (time since Hassan's last message to it) is a thin ring that fills
  clockwise over 24 hours, then turns solid gray, then dashed after a week. A
  session Hassan has never addressed (subagent, dispatched worker) gets a dotted
  ring.
- Node size is constant. Size is not activity or importance.

### Purpose and "doing now", free tier

Derived from the session transcript with no model calls:

| Field | Source |
|---|---|
| Title | `ai-title` record, else the registry `name` |
| Purpose | first `user` record whose content is text, not `isMeta`, not a tool result |
| Doing now | last `assistant` `tool_use` record (tool name plus a short argument), or the last `assistant` text if no tool use since |
| Last said | last `assistant` text block |
| You age | timestamp of the last `user` text record Hassan initiated (see below) |
| It age | timestamp of the last `assistant` record or `user` tool result |

What counts as Hassan speaking to a session, builder's call: any `user` text
record that is not `isMeta` and whose `turnOrigin` is `human` or absent (older
transcripts have no `promptSource` or `turnOrigin`). A line sent from the map,
the kitty broadcast or `orca terminal send` by hand counts as Hassan, since he
initiated it. The first prompt of a dispatched worker does not: a session whose
terminal is an Orca dispatch target (`orca orchestration worker-list --json`)
ignores its dispatch prompt, so workers get the dotted "never addressed" ring
until Hassan actually writes to them.

The reader keeps a byte offset per transcript and only parses what was appended
since the last refresh. First open of a large transcript reads it once in full.

### Initiative clustering

Inference order, first match wins:

1. The Orca orchestration run the session's terminal is bound to (`orca
   orchestration run-list`); the run description names the initiative.
2. A pattern in a hand-named initiative config (below).
3. Worktree path and branch: sessions in the same worktree share a cluster named
   after the branch.
4. Otherwise Unsorted.

Hand naming lives in `~/.config/nekotron/fleet-map.json`:

```json
{
  "initiatives": [
    {"name": "PR 6869 review", "match": ["pr-6869", "lookdown"]},
    {"name": "Commissions", "match": ["commission", "compensation"]}
  ],
  "assign": {"<sessionId>": "Commissions"}
}
```

`match` entries are case-insensitive substrings tested against title, purpose,
worktree path and branch. `assign` pins one session by id and beats everything.
The rail has a "move to…" control that writes to `assign`.

### Traffic edges

| Edge | Source |
|---|---|
| Cross-session message, outbound | `SendMessage` `tool_use` records: `input.to` resolved against registry names and agent ids |
| Cross-session message, inbound | `user` records containing `<cross-session-message from="…">` |
| Parent to subagent | `<project>/<sessionId>/subagents/agent-*.jsonl` with its `.meta.json` |
| Orca orchestration | `orca orchestration inbox --json` (from_handle, to_handle, run_id), `task-list` and `worker-list` (which maps `dispatch:` handles to terminals), polled on this Mac and on every saved environment and merged; edges may cross regions |

Orca handles name runs, dispatches and terminals, not Claude sessions. Every
Orca-launched Claude process carries `ORCA_AGENT_PANE=<tabId>:<leafId>` in its
environment, which matches `tabId` and `leafId` in `orca terminal list --json`,
so a registry pid maps to its terminal by reading that variable. The process
walk in `bin/kitty-to-orca` is the fallback when the variable is absent.

### State for sessions outside kitty

The registry only says busy or idle. "Needs you" and "done" come from the
nekotron hook today, and that hook returns early when `KITTY_PID` and `TMUX` are
unset, so Orca-hosted sessions never get them.

Builder's call: extend `hooks/kitty-tab-status.sh` to also write the state to
`/tmp/claude-kitty-status/sid-<sessionId>` whenever a session id is available,
before the kitty early return. Hook scripts are spawned fresh on every event, so
live sessions pick this up without a restart. The map reads the session-id file
first and the kitty file as a fallback. The tab bar and board are untouched.

### Hosts and data paths

This Mac:

- Sessions: `~/.claude/sessions/<pid>.json` (name, status busy/idle, cwd,
  sessionId, startedAt, statusUpdatedAt). Live if `kill -0 pid` succeeds.
- Transcripts: `~/.claude/projects/<cwd-slug>/<sessionId>.jsonl`.
- Orca terminals: `orca terminal list --json` (handle, title, worktreePath,
  branch, connected, lastOutputAt).
- Orca terminals with no Claude session but an `agentIdentity` (Codex and
  similar) are drawn as "terminal only" nodes, the same way laptop2 terminals
  are in phase 1. Plain shells with no agent identity are not drawn.
- tmux: `fleet_tmux.sessions()` for `neko-*` sessions.
- kitty: existing state files under `/tmp/claude-kitty-status`, for the
  state and context percent of kitty-hosted sessions.

laptop2, through `orca --environment laptop2`:

- `terminal list --json` and `terminal read --screen` give every terminal, its
  title, worktree, branch, last output and a screen preview. That covers Codex
  workers and Claude sessions as terminals.
- Claude-level fields (purpose, ages, edges) are unavailable from here because
  laptop2's registry and transcripts live under its own user's home. Phase 1
  draws laptop2 terminals as nodes with title, preview and last-output age, and
  marks them "terminal only" in the rail. Phase 2 reads the remote registry and
  transcripts over SSH (`orca host list` already has an SSH target for it).

State for a laptop2 node in phase 1 is derived from the screen preview and
`lastOutputAt`: output within the last minute is working, else idle.

### Actions

All actions resolve the node to its host and route accordingly.

| Action | Orca-hosted (either machine) | kitty | tmux |
|---|---|---|---|
| Peek | `orca terminal read --screen` | kitty `get-text` | `tmux capture-pane` |
| Jump | `orca terminal switch` | `fleet-jump <window>` | attach in kitty |
| Send a line | `orca terminal send` | kitty `send-text` | `tmux send-keys` |
| Close | `orca terminal close` | kitty `close-window` | `tmux kill-session` |

Close always shows a confirm naming the host, the terminal handle or window,
and that the transcript remains resumable. Closing a parent does not close its
subagents' terminals; they belong to the same process and end with it.

### Process and launch

- One Python 3 program under `kitty/` or `bin/` in nekotron, standard library
  only, serving one HTML page over loopback with a random per-launch key in the
  URL, the same pattern the brainstorm companion uses.
- The page polls a JSON endpoint every 3 seconds while visible and stops when
  hidden. The server exits after 30 minutes with no page connected.
- Launch from a new nekotron keybind in `kitty/nekotron.conf` and a "Fleet map"
  row in the SwiftBar menu, next to "Open Fleet Board". Both run the same
  launcher, which reuses a running server if one exists.
- Map layout: clusters positioned by a simple deterministic packing so nodes do
  not jump between refreshes; positions are keyed by session id and persisted
  for the life of the server.

### Later, not in this build

- Opt-in model one-liner for purpose, cached per transcript offset, only
  re-run when the transcript advanced.
- Phase 2 laptop2 Claude-level data over SSH.
- Collapsing a cluster to a single node.

## Left to the builder

- Packing algorithm for clusters and nodes, as long as positions are stable
  across refreshes.
- Exact pulse and hollowing curves; the legend must describe whatever is chosen.
- How much of a transcript to read on first open of a very large file.
- Test layout: fixtures mirroring the existing `tests/` style for the transcript
  reader, the edge resolver and the initiative matcher. The server and page can
  be exercised by hand.
- Keybind choice; `⌘⇧F` is taken by the fleet board.
