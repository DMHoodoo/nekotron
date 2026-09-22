# ᓚᘏᗢ Nekotron

Mission control for a fleet of Claude Code and Codex CLI sessions running in kitty.
Built 2026-07-09/10. Everything is event-driven — no daemons, no timers.

## What it does

- **Live tab status** — every kitty tab shows its Claude session's state:
  blue spinner (working), green (done), pulsing orange (needs input), plus
  per-repo color accents, context-pressure amber, and OSC progress %.
- **Fleet board** (`⌘⇧F`) — full-canvas dashboard: session cards with live
  transcript activity feeds, notes, cost, context gradient bars; fleet
  timeline; ring gauges (memory / 5h / weekly usage); vitals incl. kitty
  socket health; animated cat (ASCII or pixel sprite, toggle `s`, pet `c`).
- **Meow on attention** — any session flipping to NEEDS YOU plays
  `sounds/meow.wav` (synthesized from raw sine math, symlinked to
  `~/.claude/sounds/`), board open or not. Delete the symlink to silence.
- **Fleet actions** — `⌘⇧A` jump to the session that needs you, `⌘⇧B`
  broadcast one message to every Claude, `⌘⇧P` peek any tab's live screen
  without switching, `⌘⇧X` open a Claude about whatever is on screen,
  `⌘⇧K` self-updating keybind cheatsheet. The board is
  mouse-aware: click a card to (un)minimize it, hover brightens its panel,
  click the yard to pet the cat; `/` filters cards fuzzily (enter jumps);
  `:` opens a command palette of every fleet action; `d` toggles compact
  one-line cards. Closing a Claude session prints a two-line exit receipt
  (duration · cost · resume command).
  `⌘⇧M` previews any on-screen file path in-terminal (glow for markdown).
  `⌘⇧C` lists the recent code blocks from this tab's Claude session
  (pulled from the transcript, so you copy the exact original text, not
  the screen-wrapped render) — a digit copies to clipboard.

## Second machine (control plane)

`fleet-remote [user@host]` (or `⌘⇧O` with a default host in
`~/.config/nekotron/remote-host`) recreates the other laptop's kitty workspace
as **native local kitty tabs**. Each shared terminal attaches over SSH to the
same remote tmux session; switch tabs normally to inspect prompts and type.
Remote OS-window grouping, tab order/titles, pane grouping, and layout names
are copied when opened. Split ratios, changing titles, tab status LEDs, and
subsequent layout changes are not continuously synchronized; close and reopen
the mirror to refresh its structure. Remote terminals remain live throughout.

Use its Tailscale hostname/IP across networks; macOS Remote Login provides
the SSH server. Update/install Nekotron on **both** machines for this launcher:

```sh
git pull
brew install tmux
./install.sh
source zsh/nekotron.zsh  # existing shells; new shells load it via ~/.zshrc
```

Tabs started outside tmux appear as **[local only]** placeholders, with
migration instructions. They are not silently restarted or copied into new
agent conversations. Already-mirrored windows are excluded to prevent
recursive mirrors. Detached tmux sessions appear in a separate remote window.
Closing a mirror tab disconnects its client without stopping the remote agent.
After a connection drops or you detach, press Enter in that tab to reconnect.

`fleet-remote --board [user@host]` retains the dashboard and its status LEDs.
Interactive `claude` and `codex` commands in kitty now start in persistent
**tmux sessions on the machine running the agent**. `new` and `resume` use
this path too. Piped/noninteractive commands (including `claude -p` and
`codex exec`) retain their normal behavior; launching inside tmux does not
nest another session. Machines without tmux retain direct launches.

On the remote board, press a card's **number**, or `/` to filter then Enter,
to attach to its live terminal. Cards marked **attachable** support this.
You can read prompts and type replies while the original kitty window
remains connected. **Ctrl-B, then D** detaches and returns to the board;
it does not stop the agent. A dropped SSH connection also leaves it running.
Detached sessions remain on the board even after kitty closes. Machine
reboots still require resuming the conversation.

For an explicitly shared shell or command:

```sh
fleet-session run zsh -l
fleet-session run claude --resume SESSION_ID
fleet-session run codex resume SESSION_ID
fleet-session list
fleet-session attach neko-SESSION_NAME
```

Existing agents launched directly in kitty are marked **local only**. They
cannot be attached retroactively. Finish the current turn and exit the old
agent, reload `zsh/nekotron.zsh` in that shell, then resume its conversation.
Do not resume the same conversation while its original process is running.
Keep active approval prompts local until that transition is complete.
The installer never terminates or migrates a running agent.

The local board continues to focus existing kitty tabs; selecting a detached
shared session attaches in the board's terminal. Agent state is stored per
tmux session as well as mirrored to the local tab, so remote/detached
sessions retain working/attention/done indicators. Claude transcript feeds
remain available. Terminal clients share input and use the smaller viewport.

## Charm lane

- **`q <question>`** — sub-second answer from the LOCAL model (ollama gemma4,
  direct, thinking off); pipe stdin for context. Zero Claude quota or spend.
- **`qa <task>`** — agentic local one-shot via crush (tools, file access;
  ~40s of preamble inference). Config: `crush/crush.json`.
- **`resume`** — gum-powered fuzzy picker over the session ledger; resumes the
  chosen Claude session in the current window (● marks already-running).
- **`board-shot [out.png]`** — freeze the fleet board's text layer to a PNG.
- **`md`** — alias for `glow -p` (markdown pager).
- **`docs/demo.tape`** — vhs recording script (`vhs docs/demo.tape`).

## Codex lane

- **`qo <question>`** — non-interactive `codex exec`; pipe stdin for context
  (`cat err.log | qo what broke`). Uses your Codex login/model and quota.
  Progress stays on stderr; the final answer goes to stdout (glow on a tty).
- **Interactive `codex`** — working → attention on approval → done drives the
  same tab LED, fleet card, attention jump, and meow as Claude. No separate
  status files or daemon. All writes go through `kitty-tab-status.sh`.

Run `./install.sh`, then add this at the **top level** of `~/.codex/config.toml`
(before any `[table]`; substitute your actual absolute checkout path):

```toml
notify = ["/Users/YOU/Documents/GlowDevelopment/nekotron/hooks/codex-notify.sh"]
```

The installer also links `~/.codex/AGENTS.md` to `codex/AGENTS.md`, which points
Codex at Hassan's shared Markdown skills in `~/.claude/skills` (install
[dotclaude](https://github.com/DMHoodoo/dotclaude) first). Existing user
instructions are preserved with a manual merge hint.

The installer links `~/.codex/hooks/codex-notify.sh` and `~/.codex/hooks.json`
into this repo. If you already have a hooks file, it preserves it and prints
merge instructions. In a new Codex session, open **`/hooks`** and review/trust
Nekotron's hooks; a changed hook definition needs review again.

Tested with Codex CLI **0.155.1**: `notify` only emits completion, so lifecycle
hooks supply working, approval attention, tool resumption, and interrupt state.
A live Plan-mode `request_user_input` question also produced attention and
returned to working after answering; plain final questions are completed turns (green). Approval hooks may fire
before automatic approval review, briefly showing attention even if review
approves without asking you. Background title-generation completions are ignored.
See [observed payloads and reproduction](docs/codex-events.md).

Codex gets the shared status UI; transcript feeds, cost/context accounting,
Claude broadcast, and automatic Claude session resume remain Claude-specific.
Use `codex resume` to reopen a saved Codex conversation.

## Markdown lane

All rendering uses the Nekotron glamour style (`glow/nekotron.json`,
exported as `GLAMOUR_STYLE`): real headings, palette-matched, no `##`.

- **`mdv <file.md>`** — full-fat viewer: glow text + `![images]()` drawn
  inline via kitty icat + ```mermaid fences rendered to real diagrams
  (mmdc, dark theme). Scrolls in normal scrollback.
- **`md <file.md>`** — styled pager (also behind `⌘⇧M` path-hints).
- **`docs [dir]`** — glow's library browser over a directory of markdown.
- **`slides <file.md>`** — terminal presentation; `---` = slide breaks.
- **`md-shot <file.md> [out.png]`** — styled PNG of a doc (for Slack).
- **`q`** answers are typeset through glow on a tty.
- **`smd <file.md>`** — sibling project [DMHoodoo/SMD](https://github.com/DMHoodoo/SMD):
  native macOS viewer (GFM, mermaid, KaTeX, tabs, live reload). `⌘⇧M`'s
  in-terminal view offers `o` to pop the same file open in SMD.
- **`docs/showcase.md`** — one document that exercises all of the above.
- **Session safety** — crash-proof workspace restore (startup_session +
  auto-snapshots), session ledger (TSV black box), fleet-grep transcript
  search, cost ledger + costs command, context watchdog (purr at 90%),
  attention escalation, mobile push, test-runner guardrail for depechetoi.

## Layout

| dir       | contents                                     | lives at (symlinked)     |
|-----------|----------------------------------------------|--------------------------|
| kitty/    | board, tab bar, overlays, theme, splash      | ~/.config/kitty/         |
| kitty/nekotron.conf | all kitty config additions         | include-d by kitty.conf  |
| bin/      | fleet-grep, costs, note, new, snapshot, wall | ~/bin/                   |
| hooks/    | Claude Code hooks (status, statusline, ledger, guardrail) | ~/.claude/hooks/ |
| codex/    | Codex lifecycle hook wiring                | ~/.codex/hooks.json      |
| hooks/codex-notify.sh | Codex event adapter                 | ~/.codex/hooks/           |
| zsh/      | splash guard + aliases                       | sourced by ~/.zshrc      |
| claude/   | settings.json wiring reference               | (manual merge)           |
| mocks/    | sprite/header design previews                | —                        |

## Install (new machine)

Requires kitty ≥ 0.48 (`brew install --cask kitty`).

```sh
./install.sh          # symlinks everything, prints the 3 manual lines
```

State lives in /tmp/claude-kitty-status/ (ephemeral) and
~/.claude/{session,cost}-ledger.tsv (persistent, not in repo).

## Optional integrations

Everything below is opt-in; each tool degrades cleanly when absent.

| Tool | Powers | Install | Without it |
|---|---|---|---|
| Codex CLI | `qo`, Codex tab/board states | Install/login to Codex; top-level `config.toml`: `notify = ["/ABS/PATH/nekotron/hooks/codex-notify.sh"]`, then `/hooks` review (see Codex lane) | no Codex lane |
| `gum` | `resume` fuzzy picker | `brew install gum` | no picker UI |
| `glow` | `md`, `mdv`, `docs`, `⌘⇧M`, styled `q` | `brew install glow` | plain text |
| `freeze` | `board-shot`, `md-shot` | `brew trust charmbracelet/tap && brew install charmbracelet/tap/freeze` (the core `freeze` formula is an unrelated cask) | no PNG export |
| `vhs` | `docs/demo.tape` recordings | `brew install vhs` | none |
| `slides` | markdown → terminal decks | `brew install slides` | none |
| `crush` | `qa` agentic local one-shots | `brew install charmbracelet/tap/crush` + `crush/crush.json` (symlinked by install.sh) | no qa |
| `ollama` + a local model | `q` sub-second answers (config assumes `gemma4:latest`; edit `bin/q` + `crush/crush.json` for another) | [ollama.com](https://ollama.com) then `ollama pull <model>` | no q/qa |
| `mermaid-cli` | mdv renders ```mermaid fences as diagrams | `brew install mermaid-cli` (needs node) | styled code block |
| [SMD](https://github.com/DMHoodoo/SMD) | `o` from `⌘⇧M` opens the doc natively (GFM/mermaid/KaTeX, live reload) | clone + `make install` (Swift 6 CLT) | terminal-only prompt |

The meow is self-contained (`sounds/meow.wav`, symlinked by install.sh);
delete `~/.claude/sounds/meow.wav` for a silent fleet.
