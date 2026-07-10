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
for f in "$R"/hooks/*; do ln -sf "$f" ~/.claude/hooks/"$(basename "$f")"; done
echo "symlinks done. Manual steps (once):"
echo "  1. kitty.conf:  include $R/kitty/nekotron.conf"
echo "  2. ~/.zshrc:    source $R/zsh/nekotron.zsh"
echo "  3. ~/.claude/settings.json: merge claude/settings-wiring.json (hooks + statusLine)"
echo "Then restart kitty."
