"""Exercise the Orca CLI boundary using temporary executables only."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kitty'))
from fleetmap.orca import OrcaClient, OrcaError


class OrcaCLI(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='fleetmap-orca-')
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.log = self.base / 'argv.jsonl'

    def tool(self, name, stdout=b'', stderr=b'', code=0, sleep=0,
             plain_stdout=None):
        path = self.base / name
        path.write_text(
            '#!' + sys.executable + '\nimport json,os,sys,time\n' +
            f'with open({str(self.log)!r}, "a") as log:\n'
            '    log.write(json.dumps(sys.argv[1:]) + "\\n")\n' +
            f'time.sleep({sleep!r})\n' +
            f'if "--json" not in sys.argv and {plain_stdout!r} is not None:\n'
            f'    os.write(1, {plain_stdout!r})\n    sys.exit(0)\n' +
            f'os.write(1, {stdout!r})\nos.write(2, {stderr!r})\nsys.exit({code})\n')
        path.chmod(0o755)
        return str(path)

    def fake_orca(self, stdout):
        return self.tool('orca', stdout=stdout.encode('utf-8'))

    def fake_orca_sleeping(self, seconds):
        return self.tool('orca', sleep=seconds)

    def argv(self):
        return json.loads(self.log.read_text().splitlines()[-1])

    def client(self, result):
        return OrcaClient(binary=self.fake_orca(json.dumps({'ok': True, 'result': result})))

    def test_call_adds_environment_and_json_flags(self):
        c = OrcaClient(binary=self.fake_orca('{"ok":true,"result":{"terminals":[]}}'))
        self.assertEqual(c.terminals(env='laptop2'), [])
        self.assertEqual(self.argv(), ['--environment', 'laptop2', 'terminal', 'list', '--json'])

    def test_call_returns_unwrapped_result(self):
        result = {'value': '日本語 café'}
        self.assertEqual(self.client(result).call(['probe']), result)
        self.assertEqual(self.argv(), ['probe', '--json'])

    def test_last_output_at_ms_normalized_to_seconds(self):
        c = self.client({'terminals': [
            {'handle': 't1', 'lastOutputAt': 1792440607029},
            {'handle': 't2', 'lastOutputAt': 1792438294}]})
        terminals = c.terminals()
        self.assertEqual([t['lastOutputAt'] for t in terminals], [1792440607.029, 1792438294])
        self.assertTrue(all(isinstance(t['lastOutputAt'], float) for t in terminals))

    def test_terminal_metadata_is_preserved_and_missing_fields_are_present(self):
        terminal = dict(handle='t1', title='Agent', worktreePath='/w/project',
                        branch='fleet-map', connected=True, lastOutputAt=1e11,
                        tabId='tab1', leafId='leaf1', agentIdentity={'kind': 'codex'})
        complete, minimal = self.client({'terminals': [terminal, {'handle': 't2'}]}).terminals()
        self.assertEqual(complete, terminal)
        self.assertTrue(set(terminal).issubset(minimal))
        self.assertEqual(minimal['lastOutputAt'], 0.0)

    def test_timeout_raises_orca_error(self):
        c = OrcaClient(binary=self.fake_orca_sleeping(10), timeout=0.2)
        with self.assertRaisesRegex(OrcaError, '^timeout$'):
            c.terminals(env='laptop2')

    def test_missing_binary_raises_orca_error(self):
        with self.assertRaises(OrcaError):
            OrcaClient(binary='/nonexistent/orca').terminals()

    def test_nonzero_exit_preserves_stderr_with_replacement_decoding(self):
        c = OrcaClient(binary=self.tool('orca', stderr=b'Connection failed \xff\n', code=1))
        with self.assertRaises(OrcaError) as caught:
            c.terminals()
        self.assertEqual(str(caught.exception), 'Connection failed \ufffd\n')

    def test_failed_envelope_preserves_error_code_and_message(self):
        c = OrcaClient(binary=self.fake_orca(json.dumps({
            'ok': False, 'error': {'code': 'OFFLINE', 'message': 'Host unavailable'}})))
        with self.assertRaisesRegex(OrcaError, 'OFFLINE.*Host unavailable'):
            c.terminals()

    def test_failed_envelope_preserves_string_error(self):
        c = OrcaClient(binary=self.fake_orca(json.dumps({
            'ok': False, 'error': 'offline'})))
        with self.assertRaises(OrcaError) as caught:
            c.terminals()
        self.assertEqual(str(caught.exception), 'offline')

    def test_failed_envelope_preserves_list_error(self):
        c = OrcaClient(binary=self.fake_orca(json.dumps({
            'ok': False, 'error': ['OFFLINE', 'Host unavailable']})))
        with self.assertRaises(OrcaError) as caught:
            c.terminals()
        self.assertEqual(str(caught.exception), "['OFFLINE', 'Host unavailable']")

    def test_invalid_utf8_stdout_preserves_valid_json(self):
        c = OrcaClient(binary=self.tool('orca', stdout=b'{"ok":true,"result":{"text":"x\xff"}}'))
        self.assertEqual(c.screen('t1'), 'x\ufffd')

    def test_malformed_json_raises_orca_error(self):
        with self.assertRaises(OrcaError):
            OrcaClient(binary=self.fake_orca('not JSON')).call(['probe'])

    def test_list_commands_unwrap_their_result_lists(self):
        for method, command, key in (
                ('runs', 'run-list', 'runs'), ('inbox', 'inbox', 'messages'),
                ('workers', 'worker-list', 'workers'), ('tasks', 'task-list', 'tasks')):
            with self.subTest(method=method):
                records = [{'id': 'one'}, {'id': 'two'}]
                self.assertEqual(getattr(self.client({key: records}), method)(env='laptop2'), records)
                self.assertEqual(self.argv(), ['--environment', 'laptop2', 'orchestration', command, '--json'])

    def test_screen_uses_first_string_field_in_priority_order(self):
        for result, expected in (({'screen': 'screen', 'text': 'text'}, 'screen'),
                                 ({'screen': '', 'text': 'text'}, ''),
                                 ({'screen': None, 'text': 'text'}, 'text'),
                                 ({'preview': 'preview'}, 'preview'), ({}, '')):
            with self.subTest(result=result):
                self.assertEqual(self.client(result).screen('t1', env='laptop2'), expected)
                self.assertEqual(self.argv(), ['--environment', 'laptop2', 'terminal', 'read',
                                              '--terminal', 't1', '--screen', '--json'])

    def test_send_appends_enter(self):
        self.client({}).send('t1', 'hello')
        self.assertEqual(self.argv(), ['terminal', 'send', '--terminal', 't1', '--text', 'hello', '--enter', '--json'])

    def test_remote_actions_preserve_arguments_without_shell_expansion(self):
        c = self.client({})
        text = 'hello "world"; $(echo nope)\n日本語'
        c.send('t1', text, env='laptop2')
        self.assertEqual(self.argv(), ['--environment', 'laptop2', 'terminal', 'send',
                                      '--terminal', 't1', '--text', text, '--enter', '--json'])
        for action in ('switch', 'close'):
            with self.subTest(action=action):
                getattr(c, action)('t1', env='laptop2')
                self.assertEqual(self.argv(), ['--environment', 'laptop2', 'terminal', action,
                                              '--terminal', 't1', '--json'])

    def test_environments_returns_names_from_json(self):
        c = self.client({'environments': [{'name': 'laptop2'}, {'name': 'desktop'}]})
        self.assertEqual(c.environments(), ['laptop2', 'desktop'])
        self.assertEqual(self.argv(), ['environment', 'list', '--json'])

    def test_empty_environment_list_does_not_fall_back(self):
        self.assertEqual(self.client({'environments': []}).environments(), [])
        self.assertEqual(len(self.log.read_text().splitlines()), 1)

    def test_environments_fall_back_to_second_column_of_plain_listing(self):
        for stdout, code in ((b'JSON unsupported', 0), (b'', 1)):
            with self.subTest(code=code):
                binary = self.tool('orca', stdout=stdout, code=code,
                                   plain_stdout=b'ID  NAME  HOST\nid1 laptop2 host1\nid2 desktop host2\n')
                self.assertEqual(OrcaClient(binary=binary).environments(), ['laptop2', 'desktop'])
                self.assertEqual(self.argv(), ['environment', 'list'])

    def test_plain_listing_without_environments_is_empty(self):
        binary = self.tool('orca', code=1, plain_stdout=b'No saved environments.\n')
        self.assertEqual(OrcaClient(binary=binary).environments(), [])


if __name__ == '__main__':
    unittest.main()
