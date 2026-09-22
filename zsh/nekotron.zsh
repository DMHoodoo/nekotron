export PATH="$HOME/bin:/Applications/kitty.app/Contents/MacOS:$PATH"

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
    if _nekotron_share claude "$@"; then
        "$HOME/bin/fleet-session" run claude "$@"
        return $?
    fi
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

# Only interactive agent TUIs get a persistent terminal. Scripts/pipes and
# nested tmux calls keep their existing stdout and exit-status semantics.
_nekotron_share() {
    [[ -t 0 && -t 1 && -z "$TMUX" && -n "$KITTY_WINDOW_ID" ]] || return 1
    [[ -x "$HOME/bin/fleet-session" ]] || return 1
    command -v tmux >/dev/null || [[ -x /opt/homebrew/bin/tmux || -x /usr/local/bin/tmux ]] || return 1
    local agent="$1" arg
    shift
    for arg in "$@"; do
        case "$arg" in
            -h|--help|-V|--version) return 1 ;;
        esac
        if [[ "$agent" == claude ]]; then
            case "$arg" in -p|--print|--print=*) return 1 ;; esac
        fi
    done
    case "$agent:$1" in
        claude:auth|claude:doctor|claude:install|claude:update|claude:upgrade|claude:mcp|claude:plugin|claude:setup-token|claude:agents) return 1 ;;
        codex:exec|codex:e|codex:review|codex:login|codex:logout|codex:mcp|codex:mcp-server|codex:app|codex:app-server|codex:completion|codex:sandbox|codex:debug|codex:apply|codex:a|codex:cloud|codex:features|codex:help) return 1 ;;
    esac
    return 0
}

codex() {
    if _nekotron_share codex "$@"; then
        "$HOME/bin/fleet-session" run codex "$@"
    else
        command codex "$@"
    fi
}
