from __future__ import annotations

"""Check the standalone fleet map page's public integration markers."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class FleetMapPage(unittest.TestCase):
    def test_page_references_every_endpoint_and_encoding(self):
        html = (ROOT / "kitty/fleetmap/page.html").read_text()
        for value in ["/api/state", "/api/action", "/api/assign", "/api/confirm",
                      "/api/promote", "/api/move", "/api/broadcast", "/api/open-plan",
                      "stepper", "stalled", "Decision", "X-Fleet-Key", "visibilitychange",
                      "#4f8ef7", "#4cc38a",
                      "#f0803c", "#6b7394", "Legend", "subagents_shown", "layoutFleet"]:
            self.assertIn(value, html)
        self.assertNotIn("<script src=", html)
        self.assertIn("regionOrder.map(name => hostMap.get(name))", html)
        self.assertNotIn("a.name.localeCompare(b.name)", html)

    def test_stage_edits_use_membership_route_without_slice_name(self):
        html = (ROOT / "kitty/fleetmap/page.html").read_text()
        self.assertIn("'/api/stage'", html)
        self.assertIn("const body = {node: selectedId, stage:", html)
        self.assertIn("$('slice-name').disabled = editingStage", html)

    def test_close_all_uses_snapshot_human_prompt_flag(self):
        html = (ROOT / "kitty/fleetmap/page.html").read_text()
        predicate = html.split('function isNeverPrompted(node)', 1)[1].split('}', 1)[0]
        self.assertIn("node.never_prompted === true", predicate)
        for field in ('you_at', 'never_addressed', 'purpose'):
            self.assertNotIn(field, predicate)
        self.assertIn("const never = items.filter(isNeverPrompted)", html)
        self.assertNotIn("node.you_at == null && !node.purpose", html)

    def test_batch_confirmation_loads_descriptions_and_full_targets(self):
        html = (ROOT / "kitty/fleetmap/page.html").read_text()
        self.assertIn("async function prepareBatchClose", html)
        self.assertIn("request(`/api/confirm?node=${encodeURIComponent(node.id)}`)", html)
        for value in ("node.terminal", "node.tmux", "node.kitty_window",
                      "Confirmation unavailable", "closeBatch.every(node => node.description)"):
            self.assertIn(value, html)


if __name__ == "__main__":
    unittest.main()
