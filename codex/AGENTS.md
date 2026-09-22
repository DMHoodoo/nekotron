# Hassan’s shared agent knowledge

Hassan’s skills are plain Markdown under `~/.claude/skills`, symlinked into
`~/Documents/GlowDevelopment/dotclaude/skills`. For relevant Glow tasks, read
the matching skill’s `SKILL.md` and its referenced resources before acting.
Follow the current project’s AGENTS.md and the user’s instructions.

Per-project memories live under `~/.claude/projects/<project-path>/memory`;
dotclaude’s `memory/MANIFEST.tsv` maps projects to their stored memories.
Treat memories as context and verify current facts against the repository.

Edit shared skills and configuration in their owning repositories. Live
locations symlink into those repositories. Never commit credentials; only
Hassan provisions secret files by AirDrop/scp, with file mode 600.
