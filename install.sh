#!/bin/bash
# Idempotent installer: symlink repo files into their live locations.
set -e
R="$(cd "$(dirname "$0")" && pwd)"
mkdir -p ~/.config/kitty ~/bin ~/.claude/hooks
for f in "$R"/kitty/*; do
    b=$(basename "$f")
    [ "$b" = "nekotron.conf" ] && continue
    ln -sf "$f" ~/.config/kitty/"$b"
done
for f in "$R"/bin/*;   do ln -sf "$f" ~/bin/"$(basename "$f")"; done
for f in "$R"/hooks/*; do
    [ "$(basename "$f")" = codex-notify.sh ] && continue
    ln -sf "$f" ~/.claude/hooks/"$(basename "$f")"
done
mkdir -p ~/.codex/hooks
ln -sf "$R"/hooks/codex-notify.sh ~/.codex/hooks/codex-notify.sh
# Preserve existing user hooks; merge manually if this is not our symlink.
if [ ! -e ~/.codex/hooks.json ] && [ ! -L ~/.codex/hooks.json ]; then
    ln -s "$R"/codex/hooks.json ~/.codex/hooks.json
elif [ "$(readlink ~/.codex/hooks.json)" != "$R/codex/hooks.json" ]; then
    echo "Codex: merge $R/codex/hooks.json into your existing ~/.codex/hooks.json"
fi
mkdir -p ~/.claude/sounds ~/.config/crush
ln -sf "$R"/sounds/meow.wav ~/.claude/sounds/meow.wav          # attention meow
[ -e ~/.config/crush/crush.json ] || ln -sf "$R"/crush/crush.json ~/.config/crush/crush.json
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
