from __future__ import annotations

"""Check the standalone fleet map page's public integration markers."""
import json
import re
import subprocess
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def page_functions(*names):
    source = (ROOT / 'kitty/fleetmap/page.html').read_text()
    functions = []
    for name in names:
        start = re.search(r'^function ' + name + r'\(', source, re.MULTILINE).start()
        first_line = source[start:].splitlines()[0]
        if first_line.endswith('}'):
            functions.append(first_line)
        else:
            functions.append(re.search(r'^function .*?^}', source[start:],
                                       re.MULTILINE | re.DOTALL).group())
    return '\n'.join(functions)


def run_js(source):
    result = subprocess.run(['node', '-e', source], capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


DOM = """
class Element {
  constructor() { this.children = []; this.textContent = ''; this.style = {}; }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; }
  setAttribute() {}
  addEventListener() {}
}
const elements = new Map();
const $ = id => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); };
const document = {createElement: () => new Element(), createTextNode: text => String(text)};
const text = element => typeof element === 'string' ? element : element.textContent + element.children.map(text).join(' ');
"""


class FleetMapPage(unittest.TestCase):
    def test_fallback_objective_and_identity_render_in_header_and_rail(self):
        source = DOM + page_functions('html', 'button', 'clusterInfo', 'clusterRun',
                                     'clusterItems', 'renderCluster', 'detailLine',
                                     'renderFallback', 'renderContext')
        output = run_js(source + """
const objective = 'Handoff scheduling: wave 1 running; waiting for approval | full objective';
const info = {run: 'run_full_identity', fallbacks: [{run: 'run_full_identity', now: objective,
  note: 'projection v1, Chief must re-render'}]};
const snapshot = {clusters: {Handoff: info}, runs: {}, nodes: []};
const cluster = {id: 'cluster', name: 'Handoff', host: 'local', panel: new Element()};
const expanded = new Set(), nodes = new Map();
let selectedId = null, selectedContext = {cluster: 'Handoff'}, miniViews = [];
renderCluster(cluster); renderContext();
console.log(JSON.stringify([text(cluster.panel), text($('context-details'))]));
""")
        for rendered in output:
            self.assertIn('run_full_identity', rendered)
            self.assertIn('Handoff scheduling: wave 1 running; waiting for approval | full objective', rendered)
            self.assertIn('projection v1, Chief must re-render', rendered)

    def test_fallback_renders_beside_projected_matrix(self):
        source = DOM + page_functions('html', 'button', 'clusterInfo', 'clusterRun',
                                     'clusterItems', 'renderCluster', 'detailLine',
                                     'renderFallback', 'matrixTable', 'miniNode')
        output = run_js(source + """
const objective = 'Review run: legacy work; waiting';
const info = {run: 'run_test', matrix_host: 'laptop2', fallbacks: [
  {run: 'run_legacy', now: objective, note: 'projection v1, Chief must re-render'}]};
const run = {run: 'run_test', title: 'Review run', rows: [], proofs: [], chief_node: null};
const snapshot = {clusters: {'Review run': info}, runs: {run_test: run}, nodes: []};
const cluster = {id: 'cluster', name: 'Review run', host: 'laptop2', panel: new Element()};
const expanded = new Set(), nodes = new Map(), stageLabels = ['Goal', 'Review'];
let selectedId = null, selectedContext = null, miniViews = [];
renderCluster(cluster);
const collapsed = text(cluster.panel);
expanded.add(cluster.id); renderCluster(cluster);
console.log(JSON.stringify({collapsed, expanded: text(cluster.panel),
  matrices: cluster.panel.children.filter(child => child.className === 'matrix').length,
  run: clusterRun(cluster).run}));
""")
        self.assertEqual(output['run'], 'run_test')
        self.assertEqual(output['matrices'], 1)
        self.assertIn('Chief:', output['expanded'])
        for rendered in (output['collapsed'], output['expanded']):
            self.assertIn('Open run plan', rendered)
            self.assertIn('run_legacy', rendered)
            self.assertIn('Review run: legacy work; waiting', rendered)
            self.assertIn('projection v1, Chief must re-render', rendered)

    def test_layout_preserves_positions_across_membership_thresholds_and_hosts(self):
        source = DOM + page_functions('ensureRegion', 'ensureCluster', 'clusterInfo',
                                     'clusterRun', 'layoutFleet', 'endpoint')
        output = run_js(source + """
const svg = () => new Element();
const positions = new Map(), regions = new Map(), clusters = new Map(), expanded = new Set();
const MIN_REGION = 420, CELL = 70, GAP = 16;
let layoutSignature = '', layoutModeSignature = '';
const clusterKey = node => JSON.stringify([node.host, node.cluster]);
const member = (id, host = 'local', cluster = 'A') => ({id, host, cluster, kind: 'claude'});
let snapshot = {nodes: Array.from({length: 16}, (_, i) => member('s' + String(i).padStart(2, '0')))
  .concat([member('remote', 'laptop2', 'R'), member('neighbor', 'local', 'B')]), clusters: {}, runs: {}};
let nodes = new Map();
$('map-scroll').clientWidth = 1600;
const hosts = [{name: 'local'}, {name: 'laptop2'}];
function layout() { nodes = new Map(snapshot.nodes.map(n => [n.id, n])); layoutFleet(hosts); }
function capture() { return Object.fromEntries(snapshot.nodes.map(n => [n.id, endpoint(n.id)])); }
function geometry() { return [...clusters.values()].map(c => [c.id, c.x, c.y, c.geometry.width, c.geometry.headerHeight]); }
layout();
const first = capture(), boxes = geometry(), regionBoxes = JSON.stringify([...regions.values()].map(r => r.geometry));
const stages = [];
snapshot.nodes.push(member('s16')); layout(); stages.push(capture());
snapshot.nodes.push(...Array.from({length: 25}, (_, i) => member('new' + i, 'laptop2', 'R')));
layout(); stages.push(capture());
snapshot.nodes = snapshot.nodes.filter(n => !['s00', 's01', 's16'].includes(n.id));
layout(); stages.push(capture());
snapshot.nodes.push(member('replacement')); layout(); stages.push(capture());
// A late run binding moves its own node without repacking unrelated nodes.
snapshot.nodes.find(n => n.id === 'replacement').cluster = 'B'; layout(); stages.push(capture());
const stableBoxes = geometry(), stableRegions = JSON.stringify([...regions.values()].map(r => r.geometry));
const occupied = capture();
$('map-scroll').clientWidth = 1100; layout();
console.log(JSON.stringify({first, stages, boxes, stableBoxes, regionBoxes, stableRegions,
  occupied, resized: capture()}));
""")
        for stage in output['stages']:
            for node_id in output['first'].keys() & stage.keys():
                self.assertEqual(stage[node_id], output['first'][node_id], node_id)
        self.assertEqual(output['boxes'], output['stableBoxes'])
        self.assertEqual(output['regionBoxes'], output['stableRegions'])
        coordinates = [(p['x'], p['y']) for p in output['occupied'].values()]
        self.assertEqual(len(coordinates), len(set(coordinates)))
        self.assertNotEqual(output['occupied']['remote'], output['resized']['remote'])

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
