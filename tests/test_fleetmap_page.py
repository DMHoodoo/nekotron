from __future__ import annotations

"""Check the standalone fleet map page's public integration markers."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class FleetMapPage(unittest.TestCase):
    def test_page_references_every_endpoint_and_encoding(self):
        html = (ROOT / "kitty/fleetmap/page.html").read_text()
        for value in ["/api/state", "/api/action", "/api/assign", "/api/confirm",
                      "X-Fleet-Key", "visibilitychange", "#4f8ef7", "#4cc38a",
                      "#f0803c", "#6b7394", "Legend", "subagents_shown", "layoutFleet"]:
            self.assertIn(value, html)
        self.assertNotIn("<script src=", html)
        self.assertIn("regionOrder.map(name => hostMap.get(name))", html)
        self.assertNotIn("a.name.localeCompare(b.name)", html)


if __name__ == "__main__":
    unittest.main()
