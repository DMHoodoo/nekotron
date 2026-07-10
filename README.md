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
  broadcast one message to every Claude, `⌘⇧X` open a Claude about whatever
  is on screen, `⌘⇧K` self-updating keybind cheatsheet.
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
