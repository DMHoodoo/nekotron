---
name: fleet-map
description: Read the running Nekotron fleet map when asked about sessions, their relationships, run progress, or decisions waiting on the human.
---

# Read the fleet map

Read `~/.config/nekotron/fleet-map.server.json` on the Mac running the map.
It contains `port`, `key`, and `pid` for the current loopback server.
Request `GET /api/state` at `http://127.0.0.1:<port>` with the key in
the `X-Fleet-Key` header. Keep the key out of messages and saved artifacts.

```sh
python3 - <<'PY'
from __future__ import annotations

import json
from pathlib import Path
from urllib.request import Request, urlopen

info = json.loads(
    (Path.home() / '.config/nekotron/fleet-map.server.json').read_text()
)
request = Request(
    'http://127.0.0.1:{}/api/state'.format(info['port']),
    headers={'X-Fleet-Key': info['key']},
)
with urlopen(request, timeout=5) as response:
    print(json.dumps(json.load(response), indent=2))
PY
```

If the file is missing or the server is unavailable, tell the human to open
`fleet-map` on that Mac. After an authentication failure, reread the file
once: a restarted server has a new key.

## Interpret the snapshot

- `nodes`: Claude sessions, subagents, and terminal-only sessions. Join by
  host-qualified `id`; `host` and `kind` identify location and coverage.
  `purpose`, `doing`, `state`, and activity timestamps describe observed work.
  Terminal-only nodes have limited evidence; missing fields are unknown.
- `edges`: directed relationships from `src` to `dst` node IDs, with `kind`
  (`message`, `dispatch`, or `subagent`), `count`, and `newest` timestamp.
  They show observed traffic or parentage, not proof that work is complete.
- `clusters`: named initiative groups; each node's `cluster` selects its group.
  Records summarize the linked run, waiting items, stalls, and projection notes.
- `runs`: validated run projections keyed by run ID, including matrix rows,
  gates, packages, status card, and `run_plan` reference. Stages come from
  projected evidence; activity alone does not establish progress.
  A missing projection is not proof that a run has no work. Engineering OS owns
  the schema and exports `run-status.json` beside each run plan using
  `tools/run-status.py`; the plan's fence is `json run-status`. Nekotron consumes
  that record through its Engineering OS provider.
- `decisions`: projected items waiting on the human across runs, including
  class-B defaults and class-C/D decisions, with run, packet, and `applyAt`.
  Dated class-B defaults sort first. Present the item and its deadline.

Use `generated_at` to state the snapshot's age; `poll_seconds` is the server's
refresh interval. Inspect `rejected_projections` and cluster notes when progress
is missing, and report missing or stale evidence as such.

The default Engineering OS provider discovers `run-status.json`,
`*/run-status.json`, and `engineering-os/*/run-status.json` under local worktree
roots, without traversing outside symlinks or reading remote worktrees. Configure
extra roots or a directory of `--out` exports in `~/.config/nekotron/fleet-map.json`:
Set `providers.engineering_os.roots` to a list such as
`["~/orca/workspaces/glow-core/lookdown"]`, and optionally set
`providers.directory.path` to `"~/.glow/orca-progress"`. Paths expand `~`.

Without `providers`, only Engineering OS discovery is enabled; `{}` disables all.
Unknown keys produce notes. Restart after changing provider settings; roots and
records refresh each snapshot. The newest `updatedAt` wins duplicate runs, with
`superseded` diagnostics for discarded sources. File errors use paths for the
Engineering OS provider and filenames for the directory provider.

This skill is read-only. Summarize what the map shows and what needs attention.
Actions stay with the human in the fleet-map page, including sending messages,
closing sessions, changing assignments, and resolving decisions.
