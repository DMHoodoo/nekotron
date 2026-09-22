"""Real, isolated tmux tests: shared input, detach/reconnect, board and hooks."""
import importlib.util
import json
import os
from pathlib import Path
import pty
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kitty'))
import fleet_tmux
spec = importlib.util.spec_from_file_location('fleet_board', ROOT / 'kitty/fleet-board.py')
board = importlib.util.module_from_spec(spec)
spec.loader.exec_module(board)
REAL_TMUX = shutil.which('tmux') or '/opt/homebrew/bin/tmux'


@unittest.skipUnless(os.path.isfile(REAL_TMUX), 'tmux required')
class SharedTerminal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='nekotron-test-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.wrapper = self.base / 'tmux'
        self.socket = 'nekotron-test-' + self.base.name
        import shlex
        self.wrapper.write_text('#!/bin/sh\nexec ' + shlex.quote(REAL_TMUX) +
                                ' -L ' + shlex.quote(self.socket) + ' -f /dev/null "$@"\n')
        self.wrapper.chmod(0o755)
        self.patch = patch.object(fleet_tmux, 'TMUX', str(self.wrapper))
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.addCleanup(lambda: fleet_tmux.call('kill-server'))
        self.clients = []
        self.addCleanup(self.close_clients)
        self.probe = self.base / 'probe.py'
        self.probe.write_text('import os,sys\nprint("READY",os.getpid(),flush=True)\n'
                              'for line in sys.stdin: print("REPLY:"+line.strip(),flush=True)\n')
        self.name = fleet_tmux.start([sys.executable, str(self.probe)])
        self.addCleanup(lambda: Path('/tmp/claude-kitty-status/tmux-' + self.name).unlink(missing_ok=True))

    def close_clients(self):
        for pid, fd in self.clients:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                os.waitpid(pid, 0)
            except ChildProcessError:
                pass

    def client(self):
        pid, fd = pty.fork()
        if pid == 0:
            os.environ['TERM'] = 'xterm-256color'
            os.environ.pop('TMUX', None)
            os.execv(str(self.wrapper), [str(self.wrapper), 'attach-session', '-E', '-t', '=' + self.name])
        self.clients.append((pid, fd))
        self.wait(lambda: len(fleet_tmux.sessions()[self.name]['clients']) >= len(self.clients))
        return fd

    def wait(self, condition):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            if condition():
                return
            time.sleep(.05)
        self.fail('condition not reached')

    def screen(self):
        return fleet_tmux.call('capture-pane', '-pt', self.name).stdout

    def test_two_clients_share_input_and_agent_survives_disconnect(self):
        original_pid = fleet_tmux.sessions()[self.name]['panes'][0]
        first = self.client()
        second = self.client()
        os.write(second, b'from-remote\r')
        self.wait(lambda: 'REPLY:from-remote' in self.screen())
        os.write(first, b'from-local\r')
        self.wait(lambda: 'REPLY:from-local' in self.screen())
        os.write(second, b'\x02d')
        self.wait(lambda: len(fleet_tmux.sessions()[self.name]['clients']) == 1)
        self.close_clients()
        self.clients = []
        self.wait(lambda: fleet_tmux.sessions()[self.name]['attached'] == 0)
        self.client()
        self.assertEqual(fleet_tmux.sessions()[self.name]['panes'][0], original_pid)
        self.assertIn('REPLY:from-remote', self.screen())
        self.assertIn('REPLY:from-local', self.screen())

    def test_board_finds_detached_session_and_hook_state(self):
        env = dict(os.environ, PATH=str(self.base) + ':' + os.environ['PATH'],
                   NEKOTRON_TMUX_SESSION=self.name, KITTY_PID='', KITTY_WINDOW_ID='', TMUX='')
        for state in ['working', 'done', 'attention']:
            subprocess.run([str(ROOT/'hooks/kitty-tab-status.sh'), state], env=env, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cards = board._with_tmux([], 2)
        card = next(c for c in cards if c.get('tmux') == self.name)
        self.assertEqual(card['state'], 'done')  # late attention cannot downgrade completion
        self.assertIn('attachable', card['meta'])
        self.assertIsNone(card['tab_id'])

    def test_board_merges_local_client_without_duplicate_cards(self):
        self.client()
        pid = fleet_tmux.sessions()[self.name]['clients'][0]
        card = {'pids': [pid], 'meta': '', 'state': 'neutral'}
        cards = board._with_tmux([card], 2)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]['tmux'], self.name)

    def test_arguments_are_literal_not_shell_code(self):
        marker = self.base / 'should-not-exist'
        arg = 'spaces; $(touch ' + str(marker) + ') "quotes"'
        name = fleet_tmux.start([sys.executable, '-u', '-c',
                                'import sys,time; print(repr(sys.argv[1])); time.sleep(10)', arg])
        self.wait(lambda: 'spaces;' in fleet_tmux.call('capture-pane', '-pt', name).stdout)
        self.assertFalse(marker.exists())
        self.assertIn('quotes', fleet_tmux.call('capture-pane', '-pt', name).stdout)

    def test_board_still_lists_sessions_when_kitty_stalls(self):
        with patch.object(board, 'kitty_ls', side_effect=subprocess.TimeoutExpired('kitten', 5)):
            cards = board.gather('/tmp/stalled-socket', '123', 2)
        self.assertIn(self.name, [c.get('tmux') for c in cards])

    def test_shell_wrapper_only_selects_interactive_agents(self):
        home = self.base / 'home'
        (home/'bin').mkdir(parents=True)
        (home/'bin/fleet-session').symlink_to(ROOT/'bin/fleet-session')
        master, slave = pty.openpty()
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, slave)
        env = dict(os.environ, HOME=str(home), KITTY_WINDOW_ID='123', TMUX='',
                   NEKOTRON_SPLASHED='1')
        script = ('source "$1"; '
                  '_nekotron_share claude && print CLAUDE_SHARED; '
                  '_nekotron_share codex resume && print CODEX_SHARED; '
                  '_nekotron_share codex exec || print EXEC_DIRECT; '
                  '_nekotron_share claude -p hello || print PRINT_DIRECT; '
                  '_nekotron_share claude --version || print VERSION_DIRECT; '
                  'TMUX=inside; _nekotron_share claude || print NESTED_DIRECT')
        p = subprocess.Popen(['zsh', '-c', script, 'test', str(ROOT/'zsh/nekotron.zsh')],
                             env=env, stdin=slave, stdout=slave, stderr=slave)
        self.assertEqual(p.wait(timeout=5), 0)
        output = os.read(master, 8192).decode()
        for expected in ['CLAUDE_SHARED', 'CODEX_SHARED', 'EXEC_DIRECT', 'PRINT_DIRECT',
                         'VERSION_DIRECT', 'NESTED_DIRECT']:
            self.assertIn(expected, output)


    def test_remote_selection_attaches_and_returns_to_board(self):
        with patch.object(board, 'remote_mode', return_value=True), patch.object(board.subprocess, 'run') as run:
            self.assertTrue(board.select_card({'tmux': self.name}, '/tmp/unused'))
            self.assertEqual(run.call_args.args[0][-2:], ['attach', self.name])
            self.assertNotIn('-d', run.call_args.args[0])


class Noninteractive(unittest.TestCase):
    def test_launcher_preserves_pipe_output_and_exit_status(self):
        result = subprocess.run([str(ROOT/'bin/fleet-session'), 'run', sys.executable, '-c',
                                 'import sys; print(sys.stdin.read(),end=""); sys.exit(7)'],
                                input='literal stdin\n', text=True, capture_output=True)
        self.assertEqual(result.returncode, 7)
        self.assertEqual(result.stdout, 'literal stdin\n')
        self.assertEqual(result.stderr, '')


if __name__ == '__main__':
    unittest.main()
