#!/bin/bash
# Idempotent installer: symlink repo files into their live locations.
set -e
R="$(cd "$(dirname "$0")" && pwd)"
mkdir -p ~/.config/kitty ~/bin ~/.claude/hooks
for f in "$R"/kitty/*; do
    b=$(basename "$f")
    [ "$b" = "nekotron.conf" ] && continue
    # Do not follow existing directory symlinks (including the fleetmap package).
    ln -sfn "$f" ~/.config/kitty/"$b"
done
for f in "$R"/bin/*;   do ln -sf "$f" ~/bin/"$(basename "$f")"; done
for f in "$R"/hooks/*; do
    [ "$(basename "$f")" = codex-notify.sh ] && continue
    ln -sf "$f" ~/.claude/hooks/"$(basename "$f")"
done
mkdir -p ~/.claude/skills
for f in "$R"/claude/skills/*; do
    ln -sfn "$f" ~/.claude/skills/"$(basename "$f")"
done
mkdir -p ~/.codex/hooks
# Share Hassan's Markdown skills with Codex without replacing user instructions.
if [ ! -e ~/.codex/AGENTS.md ] && [ ! -L ~/.codex/AGENTS.md ]; then
    ln -s "$R/codex/AGENTS.md" ~/.codex/AGENTS.md
elif [ "$(readlink ~/.codex/AGENTS.md)" != "$R/codex/AGENTS.md" ]; then
    echo "Codex: merge $R/codex/AGENTS.md into your existing ~/.codex/AGENTS.md"
fi
ln -sf "$R"/hooks/codex-notify.sh ~/.codex/hooks/codex-notify.sh
# Preserve existing user hooks; merge manually if this is not our symlink.
if [ ! -e ~/.codex/hooks.json ] && [ ! -L ~/.codex/hooks.json ]; then
    ln -s "$R"/codex/hooks.json ~/.codex/hooks.json
elif [ "$(readlink ~/.codex/hooks.json)" != "$R/codex/hooks.json" ]; then
    echo "Codex: merge $R/codex/hooks.json into your existing ~/.codex/hooks.json"
fi
mkdir -p ~/.claude/sounds ~/.config/crush ~/.config/nekotron/swiftbar
ln -sf "$R"/swiftbar/nekotron.5s.py ~/.config/nekotron/swiftbar/nekotron.5s.py
ln -sf "$R"/sounds/meow.wav ~/.claude/sounds/meow.wav          # attention meow
[ -e ~/.config/crush/crush.json ] || ln -sf "$R"/crush/crush.json ~/.config/crush/crush.json
# Off macOS, cmd+ is the Win key (mostly reserved by Windows): mirror every
# cmd+ map as ctrl+alt+ in a file nekotron.conf globincludes.
if [ "$(uname -s)" != Darwin ]; then
    sed -n 's/^map cmd+/map ctrl+alt+/p' "$R/kitty/nekotron.conf" > ~/.config/kitty/nekotron-keys-linux.conf
    # WSLg: kitty's Wayland paste comes back empty; paste via wl-paste instead,
    # and on Ctrl+V too since that is the Windows habit.
    if grep -qi microsoft /proc/version 2>/dev/null; then
        for k in ctrl+shift+v ctrl+v; do
            printf 'map %s launch --type=background ${HOME}/bin/nk-paste @active-kitty-window-id\n' "$k"
        done >> ~/.config/kitty/nekotron-keys-linux.conf
    fi
fi
# The first launch has no snapshot yet; never overwrite an existing workspace.
[ -e ~/.config/kitty/claude-restore.session ] || printf 'launch zsh -l\n' > ~/.config/kitty/claude-restore.session
echo "symlinks done. Manual steps (once):"
echo "  1. kitty.conf:  include $R/kitty/nekotron.conf"
echo "  2. ~/.zshrc:    source $R/zsh/nekotron.zsh"
echo "  3. ~/.claude/settings.json: merge claude/settings-wiring.json (hooks + statusLine)"
echo "Then restart kitty."
echo "Codex (optional): add at the TOP LEVEL of ~/.codex/config.toml:"
echo "  notify = [\"$R/hooks/codex-notify.sh\"]"
echo "Then open /hooks in Codex and review/trust the Nekotron hooks."
