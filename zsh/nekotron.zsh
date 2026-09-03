# Nekotron splash — kitty interactive shells only (remove block to disable)
if [[ -o interactive && -n "$KITTY_WINDOW_ID" && -z "$NEKOTRON_SPLASHED" ]]; then
    export NEKOTRON_SPLASHED=1
    "$HOME/Documents/GlowDevelopment/nekotron/kitty/splash.sh"
fi

# Nekotron kittens — inline images, diffs, HUD terminal, ssh, theme
alias ic="kitten icat"
alias kdiff="kitten diff"
alias hud="kitten quick-access-terminal"
alias kssh="kitten ssh"
alias theme="$HOME/Documents/GlowDevelopment/nekotron/kitty/nekotron-theme.sh"
alias costs="$HOME/bin/claude-costs"
export GLAMOUR_STYLE="$HOME/Documents/GlowDevelopment/nekotron/glow/nekotron.json"
alias md="glow -p"
docs() { glow "${1:-.}"; }  # markdown library browser (styled via GLAMOUR_STYLE)
