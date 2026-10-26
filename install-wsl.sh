#!/bin/bash
# One-shot setup for Windows (WSL2 + WSLg) or Debian/Ubuntu: system packages,
# kitty, Claude Code, the checkout, install.sh and its manual steps.
# Idempotent: skips what is already there and never overwrites your configs.
#   curl -fsSL https://raw.githubusercontent.com/DMHoodoo/nekotron/master/install-wsl.sh | bash
set -e
NK=~/Documents/GlowDevelopment/nekotron   # bin/ and zsh/ expect this path
step() { printf '\n\033[38;2;95;233;223mᓚᘏᗢ %s\033[0m\n' "$*"; }

step "system packages"
pkgs="zsh tmux git jq curl pulseaudio-utils libnotify-bin wl-clipboard wslu
      libxkbcommon-x11-0 libxcb-xkb1 libfontconfig1 libgl1 libegl1
      libgl1-mesa-dri fonts-noto-color-emoji"
missing=$(for p in $pkgs; do dpkg -s "$p" >/dev/null 2>&1 || printf '%s ' "$p"; done)
if [ -n "$missing" ]; then
    echo "installing: $missing(sudo will ask for your password)"
    sudo apt-get update -q && sudo apt-get install -y $missing
else
    echo "all present"
fi
# An empty machine-id breaks D-Bus (kitty logs warnings); --ensure won't fix an empty file.
if [ ! -s /etc/machine-id ]; then
    sudo sh -c 'dbus-uuidgen > /etc/machine-id' ||
        echo "skipped /etc/machine-id (only costs harmless D-Bus warnings)"
fi

step "kitty"   # Ubuntu's package is far older than the 0.48 nekotron needs
if [ ! -x ~/.local/kitty.app/bin/kitty ]; then
    curl -fsSL https://sw.kovidgoyal.net/kitty/installer.sh | sh /dev/stdin launch=n
fi
mkdir -p ~/.local/bin ~/.local/share/applications
ln -sf ~/.local/kitty.app/bin/kitty ~/.local/kitty.app/bin/kitten ~/.local/bin/
# A .desktop entry lets WSLg list kitty in the Windows Start menu.
sed "s|Exec=kitty|Exec=$HOME/.local/kitty.app/bin/kitty|; s|Icon=kitty|Icon=$HOME/.local/kitty.app/share/icons/hicolor/256x256/apps/kitty.png|" \
    ~/.local/kitty.app/share/applications/kitty.desktop > ~/.local/share/applications/kitty.desktop
~/.local/bin/kitty --version

step "Claude Code"
[ -x ~/.local/bin/claude ] || curl -fsSL https://claude.ai/install.sh | bash
~/.local/bin/claude --version

step "nekotron checkout"
if [ ! -d "$NK/.git" ]; then
    mkdir -p "$(dirname "$NK")"
    git clone https://github.com/DMHoodoo/nekotron "$NK"
else
    echo "$NK"
fi
"$NK/install.sh" >/dev/null

step "wiring"
mkdir -p ~/.config/kitty ~/.claude
add_line() {   # add_line FILE LINE: append once
    grep -qxF "$2" "$1" 2>/dev/null || { printf '%s\n' "$2" >> "$1"; echo "  $1 += $2"; }
}
add_line ~/.config/kitty/kitty.conf "shell /usr/bin/zsh -l"
add_line ~/.config/kitty/kitty.conf "include $NK/kitty/nekotron.conf"
add_line ~/.zshrc 'export PATH="$HOME/.local/bin:$PATH"'
add_line ~/.zshrc "source $NK/zsh/nekotron.zsh"
if [ ! -e ~/.claude/settings.json ]; then
    cp "$NK/claude/settings-wiring.json" ~/.claude/settings.json
    echo "  ~/.claude/settings.json = claude/settings-wiring.json"
elif ! grep -q kitty-tab-status ~/.claude/settings.json; then
    echo "  ~/.claude/settings.json exists: merge $NK/claude/settings-wiring.json (hooks + statusLine)"
fi

step "done"
echo "Start kitty from the Start menu (may need 'wsl --shutdown' once to appear)"
echo "or from PowerShell:  wsl -- ~/.local/bin/kitty"
echo "Then run 'claude' in kitty to log in."
