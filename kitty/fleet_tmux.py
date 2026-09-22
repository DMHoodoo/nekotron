"""Persistent terminal sessions shared by the fleet launcher and board."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid

TMUX = (shutil.which('tmux') or
        next((p for p in ('/opt/homebrew/bin/tmux', '/usr/local/bin/tmux')
              if os.access(p, os.X_OK)), 'tmux'))


def call(*args, check=False):
    return subprocess.run([TMUX, *args], capture_output=True, text=True,
                          timeout=5, check=check)


def sessions():
    """Include detached managed sessions, which have no kitty window to inspect."""
    try:
        rows = call('list-sessions', '-F',
                    '#{session_name}\t#{session_id}\t#{session_attached}\t#{@nekotron_command}').stdout
        result = {}
        for row in rows.splitlines():
            name, ident, attached, command = row.split('\t', 3)
            if not name.startswith('neko-'):
                continue
            result[name] = dict(name=name, id=ident, attached=int(attached),
                                command=command, clients=[], panes=[], cwd='')
        if not result:
            return result
        for row in call('list-clients', '-F', '#{client_pid}\t#{session_name}').stdout.splitlines():
            pid, name = row.split('\t', 1)
            if name in result:
                result[name]['clients'].append(int(pid))
        for row in call('list-panes', '-a', '-F',
                        '#{session_name}\t#{pane_pid}\t#{pane_current_path}').stdout.splitlines():
            name, pid, cwd = row.split('\t', 2)
            if name in result:
                result[name]['panes'].append(int(pid))
                result[name]['cwd'] = result[name]['cwd'] or cwd
        return result
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}


def start(argv):
    """Start once, detached first, so loss of either client never kills the agent."""
    if not argv:
        raise ValueError('a command is required')
    binary = shutil.which(argv[0])
    if not binary:
        raise ValueError(f'command not found: {argv[0]}')
    name = 'neko-' + uuid.uuid4().hex[:12]
    size = shutil.get_terminal_size((120, 35))
    args = ['new-session', '-d', '-s', name, '-c', os.getcwd(),
            '-x', str(size.columns), '-y', str(size.lines),
            '-e', f'NEKOTRON_TMUX_SESSION={name}']
    for key in ('PATH', 'KITTY_PID', 'KITTY_WINDOW_ID', 'KITTY_LISTEN_ON',
                'AWS_PROFILE', 'AWS_DEFAULT_PROFILE', 'AWS_REGION', 'AWS_DEFAULT_REGION',
                'GLAMOUR_STYLE', 'COLORTERM', 'LANG', 'LC_ALL', 'SSH_AUTH_SOCK'):
        if key in os.environ:
            args += ['-e', f'{key}={os.environ[key]}']
    try:
        # Multiple arguments bypass tmux's shell-command parsing. exec preserves
        # the pane PID so Claude transcript discovery can find the agent itself.
        call(*args, '/bin/sh', '-c', 'exec "$@"', 'nekotron', binary, *argv[1:], check=True)
        call('set-option', '-t', name, '@nekotron_command', Path(binary).name, check=True)
        call('set-window-option', '-t', name, 'window-size', 'smallest', check=True)
        call('set-option', '-t', name, 'status', 'off', check=True)
    except Exception:
        # Only the session created by this invocation may be cleaned up.
        call('kill-session', '-t', '=' + name)
        raise
    return name


def attach(name):
    if not re.fullmatch(r'neko-[a-zA-Z0-9_-]+', name):
        raise ValueError('not a Nekotron session name')
    # -E preserves the agent environment; no -d, so the local view stays attached.
    os.execv(TMUX, [TMUX, 'attach-session', '-E', '-t', '=' + name])

