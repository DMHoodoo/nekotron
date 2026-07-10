#!/bin/bash
# Snapshot the current kitty workspace into a kitty session file so a
# restart/crash restores every tab: tmux tabs reattach, Claude Code tabs
# resume their exact session (via ~/.claude/sessions/<pid>.json), plain
# shells reopen in their cwd.
#
# Requires kitty remote control (allow_remote_control socket-only +
# listen_on unix:/tmp/kitty-ctl in kitty.conf).
#
# Output: ~/.config/kitty/claude-restore.session (previous copy -> .bak)
set -euo pipefail

OUT="$HOME/.config/kitty/claude-restore.session"
KITTEN="$(command -v kitten || echo /Applications/kitty.app/Contents/MacOS/kitten)"

sock="${KITTY_LISTEN_ON:-}"
if [ -z "$sock" ]; then
    for s in /tmp/kitty-ctl-*; do
        [ -S "$s" ] && "$KITTEN" @ --to "unix:$s" ls >/dev/null 2>&1 && sock="unix:$s" && break
    done
fi
if [ -z "$sock" ]; then
    echo "ERROR: no kitty remote-control socket found (is listen_on active? restart kitty?)" >&2
    exit 1
fi

[ -f "$OUT" ] && cp "$OUT" "$OUT.bak"

python3 - "$OUT" "$KITTEN" "$sock" <<'PYEOF'
import json, os, subprocess, sys, time

out_path, kitten, sock = sys.argv[1], sys.argv[2], sys.argv[3]
r = subprocess.run([kitten, "@", "--to", sock, "ls"], capture_output=True, text=True, timeout=10)
data = json.loads(r.stdout)

# tmux client pid -> session name (for tabs that are attached tmux clients)
tmux_clients = {}
try:
    r = subprocess.run(["tmux", "list-clients", "-F", "#{client_pid} #{client_session}"],
                       capture_output=True, text=True, timeout=5)
    for line in r.stdout.splitlines():
        pid, sess = line.split(None, 1)
        tmux_clients[int(pid)] = sess.strip()
except Exception:
    pass

def claude_session_id(pid):
    p = os.path.expanduser(f"~/.claude/sessions/{pid}.json")
    try:
        with open(p) as f:
            return json.load(f).get("sessionId")
    except Exception:
        return None

lines = [f"# Claude Code workspace restore — generated {time.strftime('%Y-%m-%d %H:%M')} by kitty-claude-snapshot.sh",
         "# Manually-named tabs are pinned; auto-titled tabs re-title on resume."]

for osw in data:
    for tab in osw.get("tabs", []):
        wins = tab.get("windows", [])
        if not wins:
            continue
        w = wins[0]  # multi-pane tabs: only the first window is captured
        # manually-named tabs (title diverges from the window title) get their
        # name pinned in the session file; auto-titled tabs stay unnamed so
        # claude/tmux can re-title them on resume
        ttitle = (tab.get("title") or "").strip()
        wtitles = {(x.get("title") or "").strip() for x in wins}
        manual = ttitle and ttitle not in wtitles
        fgs = w.get("foreground_processes", []) or []
        fg = fgs[-1] if fgs else {}
        cwd = fg.get("cwd") or w.get("cwd") or os.path.expanduser("~")
        cmd0 = os.path.basename((fg.get("cmdline") or [""])[0])
        pid = fg.get("pid")

        run = None
        if cmd0 == "tmux" and pid in tmux_clients:
            run = f"tmux attach -t {tmux_clients[pid]}"
        else:
            sid = claude_session_id(pid) if pid else None
            if sid:
                run = f"claude --resume {sid}"

        lines.append("")
        lines.append(f"new_tab {ttitle}" if manual else "new_tab")
        lines.append(f"cd {cwd}")
        if tab.get("is_focused") and osw.get("is_focused"):
            lines.append("focus")
        if run:
            lines.append(f"launch zsh -l -i -c '{run}; exec zsh'")
        else:
            lines.append("launch zsh -l")

with open(out_path, "w") as f:
    f.write("\n".join(lines) + "\n")
print(f"wrote {out_path}: {sum(1 for l in lines if l.startswith('new_tab'))} tabs")
PYEOF
