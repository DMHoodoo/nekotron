"""Mirror a remote kitty workspace into native local tabs over SSH/tmux."""
import glob
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

import fleet_tmux

APP_KITTEN = '/Applications/kitty.app/Contents/MacOS/kitten'
KITTEN = APP_KITTEN if os.access(APP_KITTEN, os.X_OK) else shutil.which('kitten') or 'kitten'
LAUNCHER = str(Path(__file__).resolve().parents[1] / 'bin/fleet-remote')


def kitty(sock, *args):
    p = subprocess.run([KITTEN, '@', '--to', sock, *args], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=8)
    if p.returncode:
        raise RuntimeError(p.stderr.strip() or 'kitty remote control failed')
    return p.stdout.strip()


def sockets():
    preferred = os.environ.get('KITTY_LISTEN_ON', '')
    candidates = ([preferred] if preferred.startswith('unix:') else [])
    for path in sorted(glob.glob('/tmp/kitty-ctl-*'), key=os.path.getmtime, reverse=True):
        try:
            os.kill(int(path.rsplit('-', 1)[1]), 0)
        except (ValueError, ProcessLookupError):
            continue
        except PermissionError:
            pass
        address = 'unix:' + path
        if address not in candidates:
            candidates.append(address)
    return candidates


def local_socket():
    for sock in sockets():
        try:
            kitty(sock, 'ls')
            return sock
        except (OSError, RuntimeError, subprocess.SubprocessError):
            continue
    raise RuntimeError('No live local kitty window found')


def title(value):
    return ''.join(c for c in str(value) if c.isprintable())[:160] or 'Terminal'


def make_layout(trees, sessions):
    """Export only display metadata, never process environments or screen text."""
    result, seen = [], set()
    for socket_key, tree in trees:
        for osw in tree:
            tabs = []
            for tab in osw.get('tabs', []):
                windows = []
                for w in tab.get('windows', []):
                    # Don't recursively mirror windows already connected elsewhere.
                    if w.get('user_vars', {}).get('nekotron_remote_host'):
                        continue
                    pids = {p.get('pid') for p in w.get('foreground_processes', [])}
                    session = next((s['name'] for s in sessions.values()
                                    if pids.intersection(s['clients'])), None)
                    if session:
                        seen.add(session)
                    windows.append({'id': str(w['id']), 'title': title(w.get('title', 'Terminal')),
                                    'session': session, 'focused': bool(w.get('is_focused'))})
                if windows:
                    tabs.append({'id': str(tab['id']), 'title': title(tab.get('title', 'Terminal')),
                                 'layout': tab.get('layout', 'stack'),
                                 'active': bool(tab.get('is_active') or tab.get('is_focused')),
                                 'windows': windows})
            if tabs:
                result.append({'id': f"{socket_key}:{osw['id']}", 'tabs': tabs})
    detached = []
    for s in sessions.values():
        if s['name'] not in seen:
            label = title(f"{s['command'] or 'terminal'} · {os.path.basename(s['cwd'])}")
            detached.append({'id': s['name'], 'title': label, 'layout': 'stack', 'active': False,
                             'windows': [{'id': s['name'], 'title': label, 'session': s['name'], 'focused': True}]})
    if detached:
        result.append({'id': 'detached', 'tabs': detached})
    return {'version': 1, 'windows': result}


def layout():
    trees = []
    for sock in sockets():
        try:
            trees.append((sock, json.loads(kitty(sock, 'ls'))))
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
            continue
    return make_layout(trees, fleet_tmux.sessions())


def check_host(host):
    if not host or host.startswith('-') or any(c.isspace() or not c.isprintable() for c in host):
        raise ValueError('Use an SSH hostname/IP or user@host')
    return host


def read_host(path):
    try:
        return path.read_text(encoding='utf-8').strip()
    except UnicodeDecodeError as e:
        raise ValueError(f'{path} is not valid UTF-8; recreate it with only user@hostname') from e


def fetch_layout(host):
    p = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', host,
                        '~/bin/fleet-session layout --json'], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
    if p.returncode:
        raise RuntimeError(p.stderr.strip() or 'Remote layout query failed; update Nekotron on that machine')
    try:
        data = json.loads(p.stdout)
    except json.JSONDecodeError as e:
        raise ValueError('Remote layout is not valid JSON; check remote shell startup output '
                         'and update Nekotron on the remote laptop') from e
    if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('windows'), list):
        raise ValueError('Unsupported remote layout; update Nekotron on both machines')
    return data


def mirror(host, data, sock):
    count, shared = 0, 0
    for osw in data['windows']:
        os_anchor = None
        active_window = None
        for tab in osw['tabs']:
            tab_anchor = None
            for w in tab['windows']:
                session = w.get('session')
                if session and not re.fullmatch(r'neko-[a-zA-Z0-9_-]+', session):
                    raise ValueError('Invalid shared session name from remote machine')
                kind = 'os-window' if os_anchor is None else 'tab' if tab_anchor is None else 'window'
                label = title(tab['title'])
                if not any(win.get('session') for win in tab['windows']):
                    label += ' [local only]'
                args = ['launch', '--type', kind, '--keep-focus', '--cwd', str(Path.home()),
                        '--title', title(w['title']), '--tab-title', label,
                        '--var', f'nekotron_remote_host={host}']
                if kind == 'os-window':
                    args += ['--os-window-title', f'NEKOTRON @ {host}']
                else:
                    args += ['--match', f'window_id:{tab_anchor or os_anchor}', '--location', 'last']
                command = [sys.executable, LAUNCHER]
                if session:
                    command += ['--session-tab', host, session]
                    shared += 1
                else:
                    command += ['--unshared-tab', title(w['title'])]
                wid = int(kitty(sock, *args, *command))
                os_anchor = os_anchor or wid
                tab_anchor = tab_anchor or wid
                if tab.get('active') and w.get('focused'):
                    active_window = wid
            if tab_anchor:
                count += 1
                layout_name = tab.get('layout', 'stack')
                if layout_name in {'fat', 'grid', 'horizontal', 'splits', 'stack', 'tall', 'vertical'}:
                    kitty(sock, 'goto-layout', '--match', f'window_id:{tab_anchor}', layout_name)
        if active_window or os_anchor:
            kitty(sock, 'focus-window', '--match', f'id:{active_window or os_anchor}')
    if not count:
        raise RuntimeError('The remote machine has no kitty tabs or shared sessions to open')
    return count, shared


def session_tab(host, session):
    check_host(host)
    if not re.fullmatch(r'neko-[a-zA-Z0-9_-]+', session):
        raise ValueError('Invalid shared session name')
    while True:
        subprocess.run([KITTEN, 'ssh', '-t', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', host,
                        'exec ~/bin/fleet-session attach ' + shlex.quote(session)])
        print('\nDetached or disconnected. The remote session is not stopped.')
        input('Press Enter to reconnect, or Ctrl-C to close this tab. ')


def show_error(message):
    """The shortcut runs in the background, so give failures a visible terminal."""
    try:
        kitty(local_socket(), 'launch', '--type', 'os-window', '--title', 'Nekotron connection error',
              sys.executable, LAUNCHER, '--error-tab', message)
    except (OSError, RuntimeError, subprocess.SubprocessError):
        pass


def main(args=None):
    args = list(sys.argv[1:] if args is None else args)
    if len(args) == 2 and args[0] == '--error-tab':
        print('Unable to open the remote workspace:\n\n' + args[1])
        input('\nPress Enter to close. ')
        return
    if len(args) == 3 and args[0] == '--session-tab':
        return session_tab(args[1], args[2])
    if len(args) == 2 and args[0] == '--unshared-tab':
        print(title(args[1]) + '\n\nThis terminal was started outside tmux and is local only.\n'
              'Finish and exit the agent on that laptop, then reload Nekotron\n'
              'and resume the conversation. Reopen the mirror afterward.\n'
              'No replacement agent has been started here.\n')
        input('Press Enter to close this placeholder. ')
        return
    if args and args[0] in ('-h', '--help'):
        print('fleet-remote [--board] [user@host]\n'
              'Default: mirror remote kitty tabs. --board: open the fleet dashboard.')
        return
    board = '--board' in args
    if board:
        args.remove('--board')
    if len(args) > 1:
        raise ValueError('usage: fleet-remote [--board] [user@host]')
    host = args[0] if args else read_host(Path.home()/'.config/nekotron/remote-host')
    check_host(host)
    sock = local_socket()
    if board:
        kitty(sock, 'launch', '--type', 'os-window', '--os-window-title', f'Fleet @ {host}',
              '--var', f'nekotron_remote_host={host}', KITTEN, 'ssh', '-t', host,
              'exec ~/.config/kitty/fleet-board.py --remote')
    else:
        count, shared = mirror(host, fetch_layout(host), sock)
        print(f'Opened {count} remote tabs ({shared} shared terminals) from {host}.')
