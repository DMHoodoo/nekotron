from __future__ import annotations

"""Route fleet map actions to the terminal that hosts a snapshot node."""
import glob
import os
import shutil
import subprocess

import fleet_tmux
from .orca import OrcaClient, OrcaError

KITTEN = shutil.which('kitten') or '/Applications/kitty.app/Contents/MacOS/kitten'


class ActionError(RuntimeError):
    """An action has no usable target or its hosting CLI failed."""


def _kitty_socket(node=None):
    if node is not None:
        pid = node.get('kitty_pid')
        if type(pid) is not int or pid <= 0:
            raise ActionError('No owning kitty PID for node')
        path = f'/tmp/kitty-ctl-{pid}'
        if not os.path.exists(path):
            raise ActionError(f'Owning kitty control socket disappeared: {path}')
        try:
            os.kill(pid, 0)
        except OSError as error:
            raise ActionError(f'Owning kitty process disappeared: {pid}') from error
        return path
    # New overlays/tmux attachments have no existing kitty destination.
    candidates = []
    for path in glob.glob('/tmp/kitty-ctl-*'):
        try:
            pid = int(path.rsplit('-', 1)[1])
            if pid > 0:
                candidates.append((os.stat(path).st_mtime, path, pid))
        except (OSError, ValueError):
            continue
    for _, path, pid in sorted(candidates, reverse=True):
        try:
            os.kill(pid, 0)
        except OSError:
            continue
        return path
    raise ActionError('No live kitty control socket found')


class Actions:
    def __init__(self, orca: OrcaClient, kitten: str = KITTEN,
                 tmux: str = fleet_tmux.TMUX, jump: str = '~/bin/fleet-jump'):
        self.orca = orca
        self.kitten = kitten
        self.tmux = tmux
        self.jump_binary = os.path.expanduser(jump)

    @staticmethod
    def _target(node):
        hosting = node.get('hosting')
        if hosting in ('orca', 'laptop2'):
            route, key = 'orca', 'terminal'
        elif hosting in ('kitty', 'tmux'):
            route, key = hosting, 'kitty_window' if hosting == 'kitty' else 'tmux'
        else:
            raise ActionError(f'Unsupported hosting: {hosting}')
        target = node.get(key)
        if target is None or target == '':
            raise ActionError(f'No {key} target for {hosting} node')
        return route, str(target)

    @staticmethod
    def _run(args, text=''):
        try:
            process = subprocess.run(args, input=text, capture_output=True,
                                     text=True, encoding='utf-8', errors='replace', timeout=5)
        except subprocess.TimeoutExpired as error:
            diagnostic = error.stderr or str(error)
            if isinstance(diagnostic, bytes):
                diagnostic = diagnostic.decode('utf-8', errors='replace')
            raise ActionError(diagnostic) from error
        except OSError as error:
            raise ActionError(str(error)) from error
        if process.returncode:
            raise ActionError(process.stderr)
        return process.stdout

    def _kitty(self, command, *args, text='', node=None):
        return self._run([self.kitten, '@', '--to', f'unix:{_kitty_socket(node)}',
                          command, *args], text=text)

    def _orca(self, method, node, target, *args):
        env = None if node['host'] == 'local' else node['host']
        try:
            return getattr(self.orca, method)(target, *args, env=env)
        except OrcaError as error:
            raise ActionError(str(error)) from error

    def peek(self, node) -> str:
        route, target = self._target(node)
        if route == 'orca':
            return self._orca('screen', node, target)
        if route == 'kitty':
            return self._kitty('get-text', '--match', f'id:{target}', node=node)
        return self._run([self.tmux, 'capture-pane', '-p', '-t', target])

    def jump(self, node) -> None:
        route, target = self._target(node)
        if route == 'orca':
            self._orca('switch', node, target)
        elif route == 'kitty':
            self._kitty('focus-window', '--match', f'id:{target}', node=node)
        elif node.get('kitty_window') is not None:
            self._run([self.jump_binary, str(node['kitty_window'])])
        else:
            self._kitty('launch', '--type=tab', self.tmux, 'attach', '-t', target)

    def send(self, node, text) -> None:
        route, target = self._target(node)
        if route == 'orca':
            self._orca('send', node, target, text)
        elif route == 'kitty':
            # stdin avoids kitten's Python-escape interpretation of arguments.
            self._kitty('send-text', '--match', f'id:{target}', '--stdin', text=text + '\r', node=node)
        else:
            # Literal mode prevents text such as "Enter" from becoming a key.
            self._run([self.tmux, 'send-keys', '-t', target, '-l', '--', text])
            self._run([self.tmux, 'send-keys', '-t', target, 'Enter'])

    def broadcast(self, nodes, text) -> list[dict]:
        results = []
        for node in nodes:
            try:
                self.send(node, text)
            except Exception as error:
                results.append({'node': node['id'], 'ok': False, 'error': str(error)})
            else:
                results.append({'node': node['id'], 'ok': True, 'error': None})
        return results

    def open_plan(self, path) -> None:
        self._kitty('launch', '--type=overlay', '--env', 'MD_PREVIEW_FROM_HEADING=Resume here',
                    os.path.expanduser('~/bin/md-preview'), os.fspath(path))

    def close(self, node) -> None:
        route, target = self._target(node)
        if route == 'orca':
            self._orca('close', node, target)
        elif route == 'kitty':
            self._kitty('close-window', '--match', f'id:{target}', node=node)
        else:
            self._run([self.tmux, 'kill-session', '-t', target])

    def describe_close(self, node) -> str:
        route, target = self._target(node)
        if route == 'orca':
            target = target[:9] + '…' if len(target) > 9 else target
        label = {'orca': 'Orca terminal', 'kitty': 'kitty window', 'tmux': 'tmux session'}[route]
        return (f'Close {label} {target} on {node["host"]}. '
                'The Claude process ends; the transcript stays resumable.')
