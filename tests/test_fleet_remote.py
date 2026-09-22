"""Regressions for board animation and native kitty tab mirroring."""
import importlib.util
import json
import os
from pathlib import Path
import pty
import select
import signal
import struct
import subprocess
import sys
import termios
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'kitty'))


class BoardAnimation(unittest.TestCase):
    def test_minimize_animation_does_not_use_invalidated_geometry(self):
        # Exercise the actual interactive loop over multiple animated frames.
        script = '''import importlib.util,sys
sys.path.insert(0,sys.argv[1]+"/kitty")
spec=importlib.util.spec_from_file_location("board",sys.argv[1]+"/kitty/fleet-board.py")
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
b._live_sock=lambda: "/tmp/kitty-ctl-123"
b.gather=lambda *a: [{"sid":None,"wid":1,"title":"Regression terminal","state":"neutral","s_epoch":None,"size":0,"repo":None,"meta":"","events":[],"ctx":None,"note":"","focused":False}]
b.vitals=lambda: {}
b.cat_mode=lambda: "ascii"
b._load_min=lambda: set()
b._save_min=lambda *a: None
b.main()
'''
        master, slave = pty.openpty()
        import fcntl
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 40, 140, 0, 0))
        p = subprocess.Popen([sys.executable, '-c', script, str(ROOT)],
                             stdin=slave, stdout=slave, stderr=slave)
        output = bytearray()
        try:
            deadline = time.monotonic()+8
            clicked = None
            quit_sent = False
            while time.monotonic()<deadline:
                if select.select([master], [], [], .03)[0]:
                    output.extend(os.read(master, 65536))
                if clicked is None and b'FLEET BOARD' in output:
                    os.write(master, b'm1')
                    clicked=time.monotonic()
                if clicked and time.monotonic()-clicked > .5 and not quit_sent:
                    os.write(master, b'q')
                    quit_sent=True
                if p.poll() is not None:
                    break
            self.assertIsNotNone(clicked, 'board never rendered')
            self.assertEqual(p.poll(), 0, output.decode(errors='replace')[-1600:])
            self.assertNotIn(b'Traceback', output)
        finally:
            if p.poll() is None:
                p.kill()
            p.wait()
            os.close(master); os.close(slave)


class TabMirror(unittest.TestCase):
    def setUp(self):
        import fleet_remote
        self.remote = fleet_remote
        self.sessions = {
            'neko-one': dict(name='neko-one', clients=[100], command='codex', cwd='/repo'),
            'neko-two': dict(name='neko-two', clients=[], command='claude', cwd='/other')}
        self.tree = [{'id': 8, 'tabs': [
            {'id': 1, 'title': 'First', 'layout': 'stack', 'is_active': True, 'windows': [
                {'id': 11, 'title': 'Codex', 'is_focused': True, 'foreground_processes': [{'pid': 100}],
                 'env': {'SECRET': 'must-not-export'}}]},
            {'id': 2, 'title': 'Old agent', 'windows': [{'id': 12, 'title': 'Old agent'}]},
            {'id': 3, 'title': 'Already mirrored', 'windows': [{'id': 13, 'user_vars': {
                'nekotron_remote_host': 'another-host'}}]}]}]

    def test_layout_keeps_order_labels_legacy_and_detached_without_secrets(self):
        data = self.remote.make_layout([('sock', self.tree)], self.sessions)
        self.assertEqual([t['title'] for t in data['windows'][0]['tabs']], ['First', 'Old agent'])
        self.assertEqual(data['windows'][0]['tabs'][0]['windows'][0]['session'], 'neko-one')
        self.assertIsNone(data['windows'][0]['tabs'][1]['windows'][0]['session'])
        self.assertEqual(data['windows'][1]['tabs'][0]['windows'][0]['session'], 'neko-two')
        self.assertNotIn('must-not-export', json.dumps(data))
        self.assertNotIn('Already mirrored', json.dumps(data))

    def test_native_tabs_share_one_os_window_and_never_start_replacement_agents(self):
        data = self.remote.make_layout([('sock', self.tree)], self.sessions)
        data['windows'] = data['windows'][:1]
        commands = []
        def kitty(sock, *args):
            commands.append(list(args))
            return '101' if args[0] == 'launch' and len([c for c in commands if c[0]=='launch']) == 1 else '102'
        with patch.object(self.remote, 'kitty', side_effect=kitty):
            self.assertEqual(self.remote.mirror('user@host', data, 'unix:test'), (2, 1))
        launches = [c for c in commands if c[0] == 'launch']
        self.assertEqual(launches[0][launches[0].index('--type')+1], 'os-window')
        self.assertEqual(launches[1][launches[1].index('--type')+1], 'tab')
        self.assertIn('window_id:101', launches[1])
        self.assertIn('--session-tab', launches[0])
        self.assertIn('--unshared-tab', launches[1])
        self.assertNotIn('resume', str(launches))
        self.assertTrue(any(c[:1]==['focus-window'] for c in commands))

    def test_host_cannot_be_interpreted_as_ssh_options(self):
        for host in ['-oProxyCommand=bad', 'user@host\ncommand', '']:
            with self.assertRaises(ValueError):
                self.remote.check_host(host)

    def test_panes_remain_grouped_with_their_remote_tab(self):
        self.tree[0]['tabs'][0]['windows'].append({'id': 14, 'title': 'split', 'foreground_processes': []})
        data = self.remote.make_layout([('sock', self.tree)], self.sessions)
        data['windows'] = data['windows'][:1]
        launches = []
        def kitty(sock, *args):
            if args[0] == 'launch': launches.append(list(args))
            return str(100+len(launches))
        with patch.object(self.remote, 'kitty', side_effect=kitty):
            self.remote.mirror('host', data, 'unix:test')
        self.assertEqual([a[a.index('--type')+1] for a in launches], ['os-window','window','tab'])
        self.assertIn('window_id:101', launches[1])



if __name__ == '__main__':
    unittest.main()
