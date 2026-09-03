# ᓚᘏᗢ Nekotron

Mission control for a fleet of Claude Code sessions running in kitty.
Built 2026-07-09/10. Everything is event-driven — no daemons, no timers.

## What it does

- **Live tab status** — every kitty tab shows its Claude session's state:
  blue spinner (working), green (done), pulsing orange (needs input), plus
  per-repo color accents, context-pressure amber, and OSC progress %.
- **Fleet board** (`⌘⇧F`) — full-canvas dashboard: session cards with live
  transcript activity feeds, notes, cost, context gradient bars; fleet
  timeline; ring gauges (memory / 5h / weekly usage); vitals incl. kitty
  socket health; animated cat (ASCII or pixel sprite, toggle `s`, pet `c`).
- **Fleet actions** — `⌘⇧A` jump to the session that needs you, `⌘⇧B`
  broadcast one message to every Claude, `⌘⇧P` peek any tab's live screen
  without switching, `⌘⇧X` open a Claude about whatever is on screen,
  `⌘⇧K` self-updating keybind cheatsheet. The board is
  mouse-aware: click a card to jump, hover one for a live peek of that tab,
  click the yard to pet the cat; `/` filters cards fuzzily (enter jumps).
  `⌘⇧M` previews any on-screen file path in-terminal (glow for markdown).

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
| zsh/      | splash guard + aliases                       | sourced by ~/.zshrc      |
| claude/   | settings.json wiring reference               | (manual merge)           |
| mocks/    | sprite/header design previews                | —                        |

## Install (new machine)

```sh
./install.sh          # symlinks everything, prints the 3 manual lines
```

State lives in /tmp/claude-kitty-status/ (ephemeral) and
~/.claude/{session,cost}-ledger.tsv (persistent, not in repo).
