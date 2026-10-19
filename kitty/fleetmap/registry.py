"""Discover local Claude sessions and their transcript locations."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess

SESSIONS = Path.home() / '.claude' / 'sessions'
PROJECTS = Path.home() / '.claude' / 'projects'
STATE_DIR = Path('/tmp/claude-kitty-status')


@dataclass
class Subagent:
    agent_id: str
    transcript: str
    mtime: float


@dataclass
class LocalSession:
    pid: int
    session_id: str
    name: str
    cwd: str
    status: str
    started_at: float
    status_updated_at: float
    transcript: str | None
    orca_pane: tuple[str, str] | None
    hook_state: str | None
    kitty_key: str | None
    ctx_pct: int | None
    cost: float | None
    subagents: list[Subagent]


def run_ps(pid: int) -> str:
    """Read the full command and environment; a vanished process is empty."""
    try:
        result = subprocess.run(['ps', 'eww', '-p', str(pid), '-o', 'command='],
                                capture_output=True, text=True, timeout=5)
        return result.stdout
    except (OSError, subprocess.SubprocessError):
        return ''


def _project_dir(cwd, projects_dir):
    return Path(projects_dir) / re.sub(r'[/_.]', '-', cwd)


def transcript_path(cwd: str, session_id: str, projects_dir) -> str | None:
    """Locate a transcript without reading its contents."""
    path = _project_dir(cwd, projects_dir) / f'{session_id}.jsonl'
    return str(path) if path.is_file() else None


def _read(path):
    try:
        return path.read_text(encoding='utf-8').strip()
    except (OSError, UnicodeError):
        return None


def _hook_state(path):
    value = _read(path)
    return value if value in ('working', 'done', 'attention') else None


def _number(path, convert):
    try:
        return convert(_read(path))
    except (TypeError, ValueError):
        return None


def _env(command, key):
    match = re.search(r'(?:^|\s)' + key + r'=(\S+)', command)
    return match.group(1) if match else None


def _subagents(project, session_id):
    agents = []
    for path in sorted((project / session_id / 'subagents').glob('agent-*.jsonl')):
        try:
            if path.is_file():
                agents.append(Subagent(path.stem[len('agent-'):], str(path), path.stat().st_mtime))
        except OSError:
            continue  # A session may disappear during discovery.
    return agents


def list_local_sessions(*, sessions_dir=SESSIONS, projects_dir=PROJECTS,
                        state_dir=STATE_DIR, ps=run_ps) -> list[LocalSession]:
    """Read live registry entries, host metadata, and optional hook state."""
    sessions = []
    state = Path(state_dir)
    for path in sorted(Path(sessions_dir).glob('*.json')):
        try:
            data = json.loads(_read(path))
            if not isinstance(data, dict):
                continue
            pid, sid, cwd = data['pid'], data['sessionId'], data['cwd']
            if (type(pid) is not int or pid <= 0 or not isinstance(sid, str)
                    or not sid or not isinstance(cwd, str)):
                continue
            started_at = float(data.get('startedAt', 0)) / 1000
            status_updated_at = float(data.get('statusUpdatedAt', 0)) / 1000
            os.kill(pid, 0)
            command = ps(pid)
            if 'claude' not in command:
                continue
        except (OSError, subprocess.SubprocessError, TypeError, ValueError,
                KeyError, OverflowError):
            continue

        pane = (_env(command, 'ORCA_AGENT_PANE') or '').split(':')
        orca_pane = (pane[0], pane[1]) if len(pane) == 2 and all(pane) else None
        kitty_pid = _env(command, 'KITTY_PID')
        kitty_window = _env(command, 'KITTY_WINDOW_ID')
        kitty_key = None
        if (kitty_pid and kitty_window
                and os.path.exists(f'/tmp/kitty-ctl-{kitty_pid}')):
            kitty_key = f'{kitty_pid}-{kitty_window}'

        hook_state = _hook_state(state / f'sid-{sid}')
        ctx_pct = cost = None
        if kitty_key:
            hook_state = hook_state or _hook_state(state / kitty_key)
            ctx_pct = _number(state / f'ctx-{kitty_key}', int)
            cost = _number(state / f'usage-{kitty_key}', float)
        sessions.append(LocalSession(
            pid=pid, session_id=sid, name=data.get('name') or '', cwd=cwd,
            status=data.get('status') or 'idle', started_at=started_at,
            status_updated_at=status_updated_at,
            transcript=transcript_path(cwd, sid, projects_dir), orca_pane=orca_pane,
            hook_state=hook_state, kitty_key=kitty_key, ctx_pct=ctx_pct, cost=cost,
            subagents=_subagents(_project_dir(cwd, projects_dir), sid)))
    return sessions
