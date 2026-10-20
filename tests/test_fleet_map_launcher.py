"""Exercise the installed launcher with an isolated home and fake servers."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class FleetMapLauncher(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='fleet-map-launcher-')
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.info = self.home / '.config/nekotron/fleet-map.server.json'
        self.info.parent.mkdir(parents=True)
        self.env = dict(os.environ, HOME=str(self.home), FLEET_MAP_NO_OPEN='1')
        self.env.pop('FLEET_MAP_SERVER', None)

    def launch(self):
        return subprocess.run([str(ROOT / 'bin/fleet-map')], env=self.env,
                              capture_output=True, text=True, timeout=15, check=True)

    def test_launcher_reuses_live_server_info(self):
        self.info.write_text(json.dumps({'port': 1234, 'key': 'k', 'pid': os.getpid()}))
        self.assertEqual(self.launch().stdout.strip(), 'http://127.0.0.1:1234/?key=k')

    def fake_server(self, source):
        server = self.home / 'fake server.py'
        server.write_text(source)
        self.env['FLEET_MAP_SERVER'] = str(server)

    def test_launcher_ignores_dead_pid_and_starts_server(self):
        self.info.write_text(json.dumps({'port': 1234, 'key': 'k', 'pid': 2**22 - 1}))
        self.fake_server('import time\ntime.sleep(0.1)\n'
                         'print(\'{"url":"http://127.0.0.1:5678/?key=fresh"}\', flush=True)\n')
        self.assertEqual(self.launch().stdout.strip(), 'http://127.0.0.1:5678/?key=fresh')

    def test_launcher_recovers_from_malformed_server_info(self):
        self.fake_server('print(\'{"url":"http://127.0.0.1:5678/?key=fresh"}\')\n')
        for info in ('not JSON', 'null', '[]', '{"pid":0,"port":1234,"key":"k"}'):
            with self.subTest(info=info):
                self.info.write_text(info)
                self.assertEqual(self.launch().stdout.strip(), 'http://127.0.0.1:5678/?key=fresh')

    def test_launcher_runs_symlinked_package_with_relative_imports(self):
        package = self.home / 'repo with spaces/kitty/fleetmap'
        package.mkdir(parents=True)
        (package / '__init__.py').touch()
        (package / 'settings.py').write_text('URL = "http://127.0.0.1:5678/?key=package"\n')
        (package / 'server.py').write_text(
            'import json\nfrom .settings import URL\nprint(json.dumps({"url": URL}))\n')
        installed = self.home / '.config/kitty/fleetmap'
        installed.parent.mkdir(parents=True)
        installed.symlink_to(package, target_is_directory=True)
        self.assertEqual(self.launch().stdout.strip(), 'http://127.0.0.1:5678/?key=package')

    def test_launcher_reports_server_start_failure(self):
        self.fake_server('raise SystemExit("fake startup failure")\n')
        with self.assertRaises(subprocess.CalledProcessError) as caught:
            self.launch()
        self.assertIn('fake startup failure', caught.exception.stderr)
        self.assertEqual(caught.exception.stdout, '')

    def test_launcher_passes_url_to_open(self):
        self.info.write_text(json.dumps({'port': 1234, 'key': 'k', 'pid': os.getpid()}))
        bindir = self.home / 'bin'
        bindir.mkdir()
        opener = bindir / 'open'
        opener.write_text('#!/bin/bash\nprintf "opened %s\\n" "$1"\n')
        opener.chmod(0o755)
        self.env['PATH'] = str(bindir) + os.pathsep + os.environ['PATH']
        self.env.pop('FLEET_MAP_NO_OPEN')
        self.assertEqual(self.launch().stdout.strip(), 'opened http://127.0.0.1:1234/?key=k')

    def test_launcher_adds_orca_app_to_path_when_missing(self):
        bindir = self.home / 'minimal-bin'
        bindir.mkdir()
        for name, target in (('python3', sys.executable), ('nohup', '/usr/bin/nohup'),
                             ('mktemp', '/usr/bin/mktemp'), ('rm', '/bin/rm')):
            (bindir / name).symlink_to(target)
        self.env['PATH'] = str(bindir)
        self.fake_server(
            'import os\n'
            'assert os.environ["PATH"].endswith(":/Applications/Orca.app/Contents/Resources/bin")\n'
            'print(\'{"url":"http://127.0.0.1:5678/?key=path"}\')\n')
        self.assertEqual(self.launch().stdout.strip(), 'http://127.0.0.1:5678/?key=path')


if __name__ == '__main__':
    unittest.main()
