#!/bin/bash
# PreToolUse guardrail: bare jest in depechetoi spawns 11 ts-jest workers and
# has hard-crashed this Mac three times (24GB, no swap headroom under the full
# dev stack). Deny unless workers are explicitly capped.

input=$(cat)
cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // empty' 2>/dev/null)
cwd=$(printf '%s' "$input" | jq -r '.cwd // empty' 2>/dev/null)

# match actual jest INVOCATIONS only — not commands that merely mention jest
# (README edits and docs about this very guardrail kept tripping it)
case "$cmd" in
    *"npx jest"*|*"yarn jest"*|*"pnpm jest"*|*"bunx jest"*|*".bin/jest"*|"jest "*) ;;
    *) exit 0 ;;
esac
case "$cmd$cwd" in *depechetoi*) ;; *) exit 0 ;; esac
case "$cmd" in *runInBand*|*maxWorkers*|*workerIdleMemoryLimit*) exit 0 ;; esac

cat <<'JSON'
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"jest guardrail: bare jest in depechetoi spawns cores-1 ts-jest workers and has hard-crashed this machine 3x (2026-07-09). Re-run with workers capped and an explicit spec path, e.g.: npx jest --runInBand <path/to/file.spec.ts> — ideally with the dev stack down."}}
JSON
exit 0
