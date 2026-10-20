from __future__ import annotations

"""Check the installed session skill's read-only documentation contract."""
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class FleetMapSkill(unittest.TestCase):
    def test_skill_metadata_and_read_only_contract(self):
        text = (ROOT / 'claude/skills/fleet-map/SKILL.md').read_text()
        parts = text.split('---', 2)
        self.assertEqual(parts[0], '')
        self.assertEqual(len(parts), 3)
        metadata, body = parts[1:]
        self.assertRegex(metadata, r'(?m)^name: fleet-map$')
        self.assertRegex(metadata, r'(?m)^description: \S.+$')
        for required in ('fleet-map.server.json', '/api/state', 'X-Fleet-Key'):
            self.assertIn(required, body)
        self.assertEqual(set(re.findall(r'/api/[\w-]+', body)), {'/api/state'})
        self.assertLess(len(text.splitlines()), 80)


if __name__ == '__main__':
    unittest.main()
