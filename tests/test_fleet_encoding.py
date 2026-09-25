"""Raw subprocess bytes must not hide SSH errors or discard terminal metadata."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'kitty'))
import fleet_remote
import fleet_tmux


class OutputEncoding(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def tool(self, name, stdout=b'', stderr=b'', code=0):
        path=self.base/name
        path.write_text('#!' + sys.executable + '\nimport os,sys\n' +
                        f'os.write(1,{stdout!r})\nos.write(2,{stderr!r})\nsys.exit({code})\n')
        path.chmod(0o755)
        return str(path)

    def test_invalid_ssh_stderr_preserves_actual_authentication_error(self):
        self.tool('ssh', stderr=b'Permission denied (publickey,password).\n' + b'x'*27 + b'\xe2!\n', code=255)
        with patch.dict(os.environ, PATH=str(self.base)+os.pathsep+os.environ['PATH']):
            with self.assertRaisesRegex(RuntimeError, 'Permission denied'):
                fleet_remote.fetch_layout('test-host')

    def test_invalid_title_bytes_do_not_prevent_valid_layout(self):
        raw=b'{"version":1,"windows":[{"title":"terminal \xe2!"}]}'
        self.tool('ssh', stdout=raw)
        with patch.dict(os.environ, PATH=str(self.base)+os.pathsep+os.environ['PATH']):
            self.assertEqual(fleet_remote.fetch_layout('test-host')['windows'][0]['title'], 'terminal \ufffd!')

    def test_valid_unicode_titles_are_preserved(self):
        payload={'version':1,'windows':[{'title':'ᓚᘏᗢ café 日本語'}]}
        self.tool('ssh', stdout=json.dumps(payload,ensure_ascii=False).encode('utf-8'))
        with patch.dict(os.environ, PATH=str(self.base)+os.pathsep+os.environ['PATH']):
            self.assertEqual(fleet_remote.fetch_layout('test-host'), payload)

    def test_kitty_and_tmux_metadata_tolerate_invalid_bytes(self):
        binary=self.tool('probe',stdout=b'terminal \xe2!',stderr=b'warning \xe2!')
        with patch.object(fleet_remote,'KITTEN',binary):
            self.assertEqual(fleet_remote.kitty('unused','ls'), 'terminal \ufffd!')
        with patch.object(fleet_tmux,'TMUX',binary):
            self.assertEqual(fleet_tmux.call('list-sessions').stdout, 'terminal \ufffd!')

    def test_malformed_json_is_still_rejected(self):
        self.tool('ssh',stdout=b'not JSON \xe2!')
        with patch.dict(os.environ, PATH=str(self.base)+os.pathsep+os.environ['PATH']):
            with self.assertRaisesRegex(ValueError,'Remote layout is not valid JSON'):
                fleet_remote.fetch_layout('test-host')

    def test_invalid_host_file_reports_its_path(self):
        path=self.base/'remote-host'
        path.write_bytes(b'hok@host\xe2!')
        with self.assertRaisesRegex(ValueError,'remote-host.*UTF-8'):
            fleet_remote.read_host(path)


if __name__=='__main__':
    unittest.main()
