from __future__ import annotations

"""Test action routing with disposable CLI executables, never live terminals."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kitty'))
from fleetmap.actions import ActionError, Actions
from fleetmap.orca import OrcaClient


def node(**fields):
    return dict(dict(hosting='orca', host='local', terminal='term_z',
                     tmux=None, kitty_window=None), **fields)


class ActionRouting(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='fleetmap-actions-')
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.orca = OrcaClient(binary=self.fake(
            'orca', stdout=b'{"ok":true,"result":{"screen":"hello screen\\n"}}'))
        self.actions = Actions(self.orca, kitten=self.fake('kitten'),
                               tmux=self.fake('tmux'), jump=self.fake('fleet-jump'))
        self.sock = self.base / f'kitty-ctl-{os.getpid()}'
        self.sock.touch()
        self.addCleanup(patch.stopall)
        patch('fleetmap.actions.glob.glob', return_value=[str(self.sock)]).start()

    def fake(self, name, stdout=b'', stderr=b'', code=0):
        path = self.base / name
        path.write_text(
            '#!' + sys.executable + '\nimport json,os,sys\n' +
            f'with open({str(self.base / (name + ".jsonl"))!r}, "a") as log:\n'
            '    log.write(json.dumps({"argv": sys.argv[1:], '
            '"stdin": sys.stdin.read()}) + "\\n")\n' +
            f'os.write(1, {stdout!r})\nos.write(2, {stderr!r})\nsys.exit({code})\n')
        path.chmod(0o755)
        return str(path)

    def calls(self, name):
        return [json.loads(line) for line in
                (self.base / (name + '.jsonl')).read_text().splitlines()]

    def argv(self, name):
        return self.calls(name)[-1]['argv']

    def kitty_args(self, command):
        return ['@', '--to', f'unix:{self.sock}', command, '--match', 'id:42']

    def test_broadcast_continues_after_a_target_failure(self):
        targets = [node(id='bad', hosting='unknown'), node(id='good')]
        self.assertEqual(self.actions.broadcast(targets, 'hello'), [
            {'node': 'bad', 'ok': False, 'error': 'Unsupported hosting: unknown'},
            {'node': 'good', 'ok': True, 'error': None}])
        self.assertIn('hello', self.argv('orca'))

    def test_open_plan_uses_overlay_and_literal_path(self):
        path = '/work/tree with spaces/plan.md'
        self.assertIsNone(self.actions.open_plan(path))
        self.assertEqual(self.argv('kitten'), ['@', '--to', f'unix:{self.sock}',
            'launch', '--type=overlay', '--env', 'MD_PREVIEW_FROM_HEADING=Resume here',
            os.path.expanduser('~/bin/md-preview'), path])
        with patch('fleetmap.actions.glob.glob', return_value=[]):
            with self.assertRaises(ActionError):
                self.actions.open_plan(path)

    def test_md_preview_starts_at_middle_heading_and_falls_back_to_whole_document(self):
        # Exercise both real preview scripts; only glow's rendering is replaced.
        binaries = self.base / 'bin'
        binaries.mkdir()
        for name, source in {
                'glow': '#!/bin/sh\ncat\n',
                'python3': '#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' "$@"\n'}.items():
            script = binaries / name
            script.write_text(source)
            script.chmod(0o755)
        path = self.base / 'run plan.md'
        before = '# Run plan\n\nOld status\n\n```markdown\n## Resume here\nexample only\n```\n\n'
        after = '## Resume here\n\nNext: verify the candidate.\n\n## Evidence\n\nFinal proof.\n'
        document = before + after
        path.write_text(document)
        for heading, expected in [('Resume here', after), ('Absent heading', document), ('', document)]:
            with self.subTest(heading=heading):
                env = dict(os.environ, MD_PREVIEW_FROM_HEADING=heading,
                           PATH=str(binaries) + os.pathsep + os.environ.get('PATH', ''))
                result = subprocess.run([str(ROOT / 'bin/md-preview'), str(path)],
                                        input='x', capture_output=True, text=True, env=env, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.split('\033', 1)[0], expected + '\n')

    def test_orca_actions_use_host_environment(self):
        for hosting, host in [('orca', 'local'), ('orca', 'laptop2'),
                              ('laptop2', 'laptop2')]:
            target = node(hosting=hosting, host=host)
            prefix = [] if host == 'local' else ['--environment', host]
            for action, command, extra in [
                    ('peek', 'read', ['--screen']), ('jump', 'switch', []),
                    ('send', 'send', ['--text', 'hello', '--enter']),
                    ('close', 'close', [])]:
                with self.subTest(hosting=hosting, host=host, action=action):
                    result = getattr(self.actions, action)(
                        target, *(['hello'] if action == 'send' else []))
                    self.assertEqual(result, 'hello screen\n' if action == 'peek' else None)
                    self.assertEqual(self.argv('orca'), prefix + [
                        'terminal', command, '--terminal', 'term_z', *extra, '--json'])

    def test_close_orca_node_on_remote_host(self):
        Actions(self.orca).close(node(hosting='laptop2', host='laptop2'))
        self.assertEqual(self.argv('orca'), ['--environment', 'laptop2', 'terminal',
                                           'close', '--terminal', 'term_z', '--json'])

    def test_kitty_peek_jump_and_close(self):
        self.fake('kitten', stdout=b'kitty screen\n')
        target = node(hosting='kitty', kitty_window=42)
        for action, command in [('peek', 'get-text'), ('jump', 'focus-window'),
                                ('close', 'close-window')]:
            with self.subTest(action=action):
                result = getattr(self.actions, action)(target)
                self.assertEqual(result, 'kitty screen\n' if action == 'peek' else None)
                self.assertEqual(self.argv('kitten'), self.kitty_args(command))

    def test_kitty_send_preserves_literal_text_and_appends_enter(self):
        text = r'--hello "world"; $(echo nope)\n café'
        self.actions.send(node(hosting='kitty', kitty_window=42), text)
        self.assertEqual(self.argv('kitten'), self.kitty_args('send-text') + ['--stdin'])
        self.assertEqual(self.calls('kitten')[-1]['stdin'], text + '\r')

    def test_tmux_peek(self):
        self.fake('tmux', stdout=b'tmux screen\n')
        self.assertEqual(self.actions.peek(node(hosting='tmux', tmux='neko-abc')),
                         'tmux screen\n')
        self.assertEqual(self.argv('tmux'), ['capture-pane', '-p', '-t', 'neko-abc'])

    def test_tmux_send_uses_literal_text_then_enter(self):
        for text in ('Enter', '--flag', 'hello; $(echo nope)'):
            with self.subTest(text=text):
                self.actions.send(node(hosting='tmux', tmux='neko-abc'), text)
                self.assertEqual([call['argv'] for call in self.calls('tmux')[-2:]], [
                    ['send-keys', '-t', 'neko-abc', '-l', '--', text],
                    ['send-keys', '-t', 'neko-abc', 'Enter']])

    def test_close_tmux_kills_session_only(self):
        self.actions.close(node(hosting='tmux', tmux='neko-abc'))
        self.assertEqual(self.argv('tmux'), ['kill-session', '-t', 'neko-abc'])
        self.assertEqual(len(self.calls('tmux')), 1)

    def test_tmux_jump_with_window_uses_fleet_jump(self):
        self.actions.jump(node(hosting='tmux', tmux='neko-abc', kitty_window=42))
        self.assertEqual(self.argv('fleet-jump'), ['42'])

    def test_tmux_jump_without_window_launches_attach_in_kitty_tab(self):
        self.actions.jump(node(hosting='tmux', tmux='neko-abc'))
        self.assertEqual(self.argv('kitten'), ['@', '--to', f'unix:{self.sock}',
                         'launch', '--type=tab', str(self.base / 'tmux'),
                         'attach', '-t', 'neko-abc'])

    def test_describe_close_names_host_and_terminal(self):
        self.assertEqual(self.actions.describe_close(node(host='laptop2')),
                         'Close Orca terminal term_z on laptop2. '
                         'The Claude process ends; the transcript stays resumable.')
        self.assertEqual(self.actions.describe_close(node(
            host='laptop2', terminal='term_c7bf123456789')),
            'Close Orca terminal term_c7bf… on laptop2. '
            'The Claude process ends; the transcript stays resumable.')
        for fields, label in [(dict(hosting='kitty', kitty_window=42), 'kitty window 42'),
                              (dict(hosting='tmux', tmux='neko-abc'), 'tmux session neko-abc')]:
            with self.subTest(fields=fields):
                description = self.actions.describe_close(node(**fields))
                self.assertIn(label + ' on local.', description)
                self.assertIn('transcript stays resumable.', description)

    def test_vanished_terminal_raises_action_error_with_cli_text(self):
        self.fake('orca', stderr=b'{"ok":false,"error":"terminal_not_found"}', code=1)
        with self.assertRaisesRegex(ActionError, 'terminal_not_found'):
            self.actions.peek(node(terminal='gone'))
        self.assertEqual(len(self.calls('orca')), 1)

    def test_failed_orca_envelope_is_action_error(self):
        self.fake('orca', stdout=b'{"ok":false,"error":"terminal_not_found"}')
        with self.assertRaisesRegex(ActionError, 'terminal_not_found'):
            self.actions.close(node())
        self.assertEqual(len(self.calls('orca')), 1)

    def test_cli_stderr_is_preserved_without_retries(self):
        for name, target, action in [
                ('kitten', node(hosting='kitty', kitty_window=42), 'close'),
                ('tmux', node(hosting='tmux', tmux='neko-abc'), 'send'),
                ('fleet-jump', node(hosting='tmux', tmux='neko-abc', kitty_window=42), 'jump')]:
            with self.subTest(name=name):
                self.fake(name, stderr=b'vanished \xff\n', code=1)
                with self.assertRaises(ActionError) as caught:
                    getattr(self.actions, action)(target, *(['hello'] if action == 'send' else []))
                self.assertEqual(str(caught.exception), 'vanished \ufffd\n')
                self.assertEqual(len(self.calls(name)), 1)

    def test_missing_binary_and_timeout_are_action_errors(self):
        actions = Actions(self.orca, tmux=str(self.base / 'missing'))
        target = node(hosting='tmux', tmux='neko-abc')
        with self.assertRaises(ActionError):
            actions.peek(target)
        with patch('fleetmap.actions.subprocess.run', side_effect=
                   subprocess.TimeoutExpired('tmux', 5, stderr=b'timed out text')):
            with self.assertRaisesRegex(ActionError, 'timed out text'):
                actions.peek(target)

    def test_newest_live_socket_skips_dead_and_malformed_names(self):
        old = self.base / 'kitty-ctl-101'
        new = self.base / 'kitty-ctl-102'
        dead = self.base / 'kitty-ctl-103'
        malformed = self.base / 'kitty-ctl-invalid'
        for stamp, path in enumerate((old, new, dead, malformed), 1):
            path.touch()
            os.utime(path, (stamp, stamp))
        with patch('fleetmap.actions.glob.glob', return_value=list(map(str, (old, dead, new, malformed)))):
            with patch('fleetmap.actions.os.kill', side_effect=lambda pid, sig:
                       (_ for _ in ()).throw(ProcessLookupError()) if pid == 103 else None) as kill:
                self.actions.peek(node(hosting='kitty', kitty_window=42))
        self.assertEqual(self.argv('kitten')[2], f'unix:{new}')
        self.assertEqual(kill.call_args_list, [unittest.mock.call(103, 0), unittest.mock.call(102, 0)])

    def test_no_live_socket_raises_action_error(self):
        with patch('fleetmap.actions.glob.glob', return_value=[]):
            with self.assertRaisesRegex(ActionError, 'kitty.*socket'):
                self.actions.peek(node(hosting='kitty', kitty_window=42))

    def test_missing_targets_and_unknown_hosts_do_not_run_commands(self):
        for target in (node(terminal=None), node(hosting='kitty'),
                       node(hosting='tmux'), node(hosting='unknown')):
            for action in ('peek', 'jump', 'send', 'close', 'describe_close'):
                with self.subTest(target=target, action=action):
                    with self.assertRaises(ActionError):
                        getattr(self.actions, action)(target, *(['hello'] if action == 'send' else []))
        self.assertEqual(list(self.base.glob('*.jsonl')), [])


if __name__ == '__main__':
    unittest.main()
