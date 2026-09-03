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

# exit receipt — a tidy two-line card when a Claude session ends in this tab
claude() {
    local t0=$SECONDS
    command claude "$@"
    local rc=$? dur=$((SECONDS - t0))
    [ -t 1 ] || return $rc
    [ "$dur" -ge 30 ] || return $rc     # no ceremony for aborted launches
    local d="/tmp/claude-kitty-status" k="${KITTY_PID:-0}-${KITTY_WINDOW_ID:-0}"
    local cost ctx sid
    cost=$(cat "$d/usage-$k" 2>/dev/null)
    ctx=$(cat "$d/ctx-$k" 2>/dev/null)
    sid=$(awk -F'\t' -v w="$k" '$4 == w {s=$2} END {print s}' "$HOME/.claude/session-ledger.tsv" 2>/dev/null)
    local dim=$'\e[38;2;107;115;148m' cyan=$'\e[38;2;95;233;223m' amber=$'\e[38;2;255;182;92m' rst=$'\e[0m' b=$'\e[1m'
    local bits="$(printf '%dh %02dm' $((dur/3600)) $(((dur%3600)/60)))"
    [ -n "$cost" ] && bits="$bits ${dim}·${rst} ${amber}\$${cost}${rst}"
    [ -n "$ctx" ] && bits="$bits ${dim}·${rst} ctx ${ctx}%"
    printf '\n  %sᓚᘏᗢ%s  %s%bsession closed%b%s  %b\n' "$amber" "$rst" "$cyan" "$b" "$rst" "$rst" "$bits"
    [ -n "$sid" ] && printf '       %sresume: claude --resume %s%s\n' "$dim" "$sid" "$rst"
    return $rc
}
