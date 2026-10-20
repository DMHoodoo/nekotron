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
  constructor(tag = '') {
    this.tagName = tag; this.children = []; this.textContent = '';
    this.style = {}; this.attributes = {}; this.listeners = {}; this.dataset = {};
  }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(name, action) { this.listeners[name] = action; }
  click() { this.listeners.click?.(); }
}
const elements = new Map();
const $ = id => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); };
const document = {createElement: tag => new Element(tag), createTextNode: text => String(text),
  createDocumentFragment: () => new Element()};
const text = element => typeof element === 'string' ? element : element.textContent + element.children.map(text).join(' ');
const descendants = element => [element, ...(element.children || []).flatMap(descendants)];
const byClass = (element, name) => descendants(element).filter(child => (child.className || child.attributes?.class || '').split(' ').includes(name));
"""


def run_page_js(source, storage="{}"):
    page = (ROOT / 'kitty/fleetmap/page.html').read_text()
    script = re.search(r'<script>(.*?)</script>', page, re.DOTALL).group(1)
    script = script.replace("const $ = id => document.getElementById(id);", "")
    return run_js(DOM + """
document.createElementNS = (_, tag) => new Element(tag);
document.addEventListener = () => {};
document.visibilityState = 'hidden';
const location = {search: ''};
const ResizeObserver = class { observe() {} };
$('empty').lastElementChild = new Element('p');
const Option = class extends Element {
  constructor(label, value) { super('option'); this.textContent = label; this.value = value; }
};
""" + f"let localStorage = {storage};\n" + script + source)


EDGE_FIXTURE = """
snapshot = {hosts: [{name: 'local'}], clusters: {}, runs: {}, nodes:
  ['a', 'b', 'c'].map(id => ({id, title: id, state: 'idle', kind: 'claude',
    host: 'local', cluster: 'Traffic'})),
  edges: [
    {src: 'a', dst: 'b', kind: 'message', count: 8, newest: Date.now() / 1000},
    {src: 'b', dst: 'c', kind: 'dispatch', count: 3, newest: Date.now() / 1000 - 3600}
  ]};
$('map-scroll').clientWidth = 1200;
render();
const traffic = () => byClass($('edges'), 'edge').filter(line => line.tagName === 'line');
const drawn = () => traffic().map(line => [line.attributes.x1, line.attributes.x2]);
"""


RUN_CLUSTER = """
const stages = ['goal', 'design', 'plan', 'implementing', 'review', 'delivery', 'accepted'];
const stageLabels = ['Goal', 'Design', 'Plan (readiness)', 'Implementing', 'Review', 'Delivery', 'Accepted'];
const packageColors = {planned: '#6b7394', verified: '#298456', running: '#4f8ef7'};
const makeRow = id => ({id, name: 'Slice ' + id, stage: 'implementing',
  stepper: [1, 1, 1, 1, 0, 0, 0], live: [], cells: {
    goal: {verdict: 'pass'}, design: {verdict: 'pass'}, plan: {verdict: 'pass'},
    implementing: {verified_units: 2, total_units: 6, segments: [
      {id: id + '-S', size: 1, state: 'planned', node: null},
      {id: id + '-M', size: 2, state: 'verified', node: 'worker'},
      {id: id + '-L', size: 3, state: 'running', node: null}]},
    review: {chips: []}, delivery: {verdict: 'pending'}, accepted: {state: 'pending'}}});
const run = {run: 'run_test', title: 'Review run', now: 'Checking the next delivery',
  rows: [makeRow('1'), makeRow('2'), makeRow('3')],
  proofs: [{id: 'E1', status: 'pass'}], chief_node: null};
const info = {run: 'run_test', matrix_host: 'local', waiting: 0, stalled: 0};
const snapshot = {clusters: {'Review run': info}, runs: {run_test: run}, nodes: [], edges: []};
const cluster = {id: 'cluster', name: 'Review run', host: 'local', panel: new Element()};
const expanded = new Set(), nodes = new Map();
let selectedId = null, selectedContext = null, miniViews = [];
const selections = [];
function showContext(context, node) { selections.push({context, node}); }
"""


class FleetMapPage(unittest.TestCase):
    def test_legend_closed_by_default_and_toggle_persists(self):
        page = (ROOT / 'kitty/fleetmap/page.html').read_text()
        self.assertRegex(page, r'<footer\b[^>]*\bhidden\b')
        self.assertRegex(page, r'<header>.*<button\b[^>]*>\?</button>.*</header>')
        output = run_page_js("""
const initial = $('legend').hidden;
toggleLegend();
const opened = {hidden: $('legend').hidden, saved: localStorage['fleetmap.legend'],
  expanded: $('legend-toggle').attributes['aria-expanded']};
$('legend-toggle').click();
console.log(JSON.stringify({initial, opened, closed: $('legend').hidden,
  saved: localStorage['fleetmap.legend']}));
""")
        self.assertEqual(output, {'initial': True, 'opened': {
            'hidden': False, 'saved': '1', 'expanded': 'true'},
            'closed': True, 'saved': '0'})
        self.assertEqual(run_page_js("""
console.log(JSON.stringify($('legend').hidden));
""", storage="{'fleetmap.legend': '1'}"), False)
        self.assertEqual(run_page_js("""
const initial = $('legend').hidden;
toggleLegend(true); toggleLegend(false);
console.log(JSON.stringify([initial, $('legend').hidden]));
""", storage="""new Proxy({}, {
  get() { throw new Error('Storage blocked'); },
  set() { throw new Error('Storage blocked'); }
})"""), [True, True])

    def test_edges_drawn_only_for_selected_or_hovered(self):
        output = run_page_js(EDGE_FIXTURE + """
const initial = drawn();
const before = [...positions];
selectNode('b');
const incomingAndOutgoing = drawn();
selectNode('a');
const selected = drawn();
nodeViews.get('c').group.listeners.mouseenter();
const both = drawn();
selectCluster(positions.get('a').cluster);
const hovered = drawn();
const fadedDispatch = traffic()[0]?.attributes;
nodeViews.get('c').group.listeners.mouseleave();
const cleared = drawn();
snapshot.edges.push({src: 'a', dst: 'c', kind: 'subagent', newest: Date.now() / 1000});
drawEdges();
console.log(JSON.stringify({initial, selected, both, hovered, cleared,
  incomingAndOutgoing, positionsStable: JSON.stringify(before) === JSON.stringify([...positions]),
  points: ['a', 'b', 'c'].map(id => endpoint(id).x), fadedDispatch,
  parentLines: descendants($('edges')).filter(item => item.tagName === 'line').length}));
""")
        a, b, c = output['points']
        self.assertEqual(output['initial'], [])
        self.assertEqual(output['incomingAndOutgoing'], [[a, b], [b, c]])
        self.assertTrue(output['positionsStable'])
        self.assertEqual(output['selected'], [[a, b]])
        self.assertEqual(output['both'], [[a, b], [b, c]])
        self.assertEqual(output['hovered'], [[b, c]])
        self.assertEqual(output['cleared'], [])
        self.assertEqual(output['fadedDispatch']['stroke-dasharray'], '6 4')
        self.assertEqual(output['fadedDispatch']['stroke-opacity'], .25)
        self.assertEqual(output['parentLines'], 1)

    def test_edge_badges_count_and_hide_on_focus(self):
        output = run_page_js(EDGE_FIXTURE + """
const badge = id => byClass(nodeViews.get(id).group, 'edge-badge')[0];
const visible = id => badge(id).style.display !== 'none';
const initial = {text: badge('b').textContent, visible: visible('b')};
selectNode('b');
const selected = visible('b');
showContext({cluster: 'Traffic'});
const deselected = visible('b');
nodeViews.get('b').group.listeners.mouseenter();
const hovered = visible('b');
nodeViews.get('b').group.listeners.mouseleave();
const left = visible('b');
snapshot.edges = Array.from({length: 10}, (_, i) =>
  ({src: 'b', dst: 'peer' + i, kind: 'message', count: 20}));
render();
const capped = badge('b').textContent;
const noEdges = visible('a');
snapshot.edges = [{src: 'a', dst: 'b', kind: 'subagent'}];
render();
console.log(JSON.stringify({initial, selected, deselected, hovered, left, capped,
  noEdges, parentOnly: visible('b')}));
""")
        self.assertEqual(output, {'initial': {'text': '2', 'visible': True},
                                 'selected': False, 'deselected': True,
                                 'hovered': False, 'left': True, 'capped': '9+',
                                 'noEdges': False, 'parentOnly': False})

    def test_heading_has_only_caret_and_name(self):
        output = self.run_cluster_js("""
renderCluster(cluster);
const heading = byClass(cluster.panel, 'cluster-heading')[0];
console.log(JSON.stringify({children: heading.children.map(text),
  buttons: descendants(heading).filter(child => child.tagName === 'button').map(text)}));
""")
        self.assertEqual(output, {'children': ['▸', 'Review run'], 'buttons': ['▸']})

    def run_selection_js(self, source):
        return self.run_cluster_js(page_functions(
            'selectCluster', 'renderRail', 'renderContext', 'openBroadcast',
            'openOverlay', 'updateBroadcastCount', 'broadcastTargets',
            'selectNode', 'showContext', 'setText', 'age', 'secondsSince',
            'paintFocus', 'drawEdges') + """
const clusters = new Map([[cluster.id, cluster]]), nodeViews = new Map();
let selectedCluster = null, assignmentChoices = '', overlayVersion = 0;
let dialogNodeId = null, closeToken = null, broadcastCluster = null;
const Option = class extends Element {
  constructor(label, value) { super('option'); this.textContent = label; this.value = value; }
};
$('empty').append(new Element('h2'), new Element('p'));
$('empty').lastElementChild = $('empty').children[1];
$('overlay').showModal = () => { $('overlay').open = true; };
function render() { renderCluster(cluster); renderRail(); }
""" + source)

    def test_clicking_name_selects_cluster_and_rail_shows_send_to_all(self):
        output = self.run_selection_js("""
info.short_name = 'Short review';
info.full_name = 'Review run: finish the pending delivery with all evidence';
selectedId = 'previous-node'; selectedContext = {package: 'previous-package'};
renderCluster(cluster);
const before = [...expanded];
byClass(cluster.panel, 'cluster-name')[0].click();
const details = $('context-details');
const send = descendants(details).find(child => child.tagName === 'button' && text(child) === 'Send to all');
send.click();
console.log(JSON.stringify({selectedCluster, selectedId, selectedContext,
  before, after: [...expanded], title: text($('context-title')), details: text(details),
  hidden: [$('empty').hidden, $('details').hidden, $('context-rail').hidden],
  counts: byClass(details, 'cluster-summary').map(text),
  broadcast: broadcastCluster, dialog: $('overlay').open, formHidden: $('broadcast-form').hidden}));
""")
        self.assertEqual(output['selectedCluster'], 'cluster')
        self.assertIsNone(output['selectedId'])
        self.assertIsNone(output['selectedContext'])
        self.assertEqual(output['before'], output['after'])
        self.assertEqual(output['title'],
                         'Review run: finish the pending delivery with all evidence')
        self.assertIn('Host:  local', output['details'])
        self.assertIn('Open run plan', output['details'])
        self.assertEqual(output['hidden'], [True, True, False])
        self.assertEqual(output['counts'], [])
        self.assertEqual(output['broadcast'], 'Review run')
        self.assertTrue(output['dialog'])
        self.assertFalse(output['formHidden'])

    def test_caret_alone_expands(self):
        output = self.run_selection_js("""
renderCluster(cluster);
byClass(cluster.panel, 'cluster-name')[0].click();
const afterName = [...expanded];
byClass(cluster.panel, 'cluster-toggle')[0].click();
const afterCaret = [...expanded];
byClass(cluster.panel, 'cluster-name')[0].click();
const afterExpandedName = [...expanded];
byClass(cluster.panel, 'cluster-toggle')[0].click();
console.log(JSON.stringify([afterName, afterCaret, afterExpandedName, [...expanded]]));
""")
        self.assertEqual(output, [[], ['cluster'], ['cluster'], []])

    def test_cluster_rail_counts_and_run_plan_follow_snapshot(self):
        output = self.run_selection_js("""
renderCluster(cluster); byClass(cluster.panel, 'cluster-name')[0].click();
const results = [];
for (const projected of [true, false]) {
  info.run = projected ? 'run_test' : null;
  for (const [waiting, stalled] of [[0, 0], [1, 0], [0, 2], [0, 0]]) {
    Object.assign(info, {waiting, stalled}); renderRail();
    results.push({counts: byClass($('context-details'), 'cluster-summary').map(text),
      plan: text($('context-details')).includes('Open run plan')});
  }
}
console.log(JSON.stringify(results));
""")
        counts = [[], ['waiting on you: 1 · 0 stalled'],
                  ['waiting on you: 0 · 2 stalled'], []]
        self.assertEqual(output, [
            {'counts': count, 'plan': projected}
            for projected in (True, False) for count in counts])

    def test_cluster_selection_yields_to_node_and_context_selection(self):
        output = self.run_selection_js("""
snapshot.edges = [];
nodes.set('worker', {id: 'worker', title: 'Worker', cluster: 'Review run', host: 'local',
  state: 'idle', kind: 'claude'});
renderCluster(cluster);
byClass(cluster.panel, 'cluster-name')[0].click();
selectNode('worker');
const node = {selectedCluster, selectedId, hidden: $('details').hidden,
  title: text($('node-title')), broadcast: text($('context-details')).includes('Send to all')};
selectCluster(cluster.id);
showContext({cluster: 'Review run'});
console.log(JSON.stringify({node, context: {selectedCluster, selectedId,
  hidden: $('context-rail').hidden, broadcast: text($('context-details')).includes('Send to all')}}));
""")
        self.assertEqual(output, {
            'node': {'selectedCluster': None, 'selectedId': 'worker', 'hidden': False,
                     'title': 'Worker', 'broadcast': False},
            'context': {'selectedCluster': None, 'selectedId': None, 'hidden': False,
                        'broadcast': False}})

    def test_cluster_name_supports_keyboard_selection(self):
        output = self.run_selection_js("""
renderCluster(cluster);
const name = byClass(cluster.panel, 'cluster-name')[0], results = [];
for (const key of ['Enter', ' ']) {
  selectedCluster = null;
  let prevented = false;
  name.listeners.keydown({key, preventDefault() { prevented = true; }});
  results.push({selectedCluster, prevented, expanded: [...expanded]});
}
console.log(JSON.stringify({role: name.attributes.role, tabindex: name.attributes.tabindex, results}));
""")
        self.assertEqual(output, {'role': 'button', 'tabindex': '0', 'results': [
            {'selectedCluster': 'cluster', 'prevented': True, 'expanded': []}] * 2})

    def test_cluster_heading_uses_short_name_with_full_title(self):
        output = self.run_cluster_js("""
info.name = cluster.name;
info.full_name = 'Review run: finish the pending delivery with all evidence';
info.short_name = 'Short review';
renderCluster(cluster);
let name = byClass(cluster.panel, 'cluster-name')[0];
const collapsed = {text: text(name), title: name.attributes.title};
expanded.add(cluster.id); renderCluster(cluster);
name = byClass(cluster.panel, 'cluster-name')[0];
console.log(JSON.stringify([collapsed, {text: text(name), title: name.attributes.title}]));
""")
        self.assertEqual(output, [
            {'text': 'Short review',
             'title': 'Review run: finish the pending delivery with all evidence'},
            {'text': 'Short review',
             'title': 'Review run: finish the pending delivery with all evidence'}])

    def test_node_label_wraps_to_two_lines_at_a_space(self):
        output = run_js(DOM + page_functions('paintNode') + """
const svg = (tag, attrs = {}) => {
  const element = new Element(tag);
  for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, value);
  return element;
};
const selectedId = null, hoveredId = null, snapshot = {edges: []};
const colors = {idle: '#888'}, secondsSince = () => 0;
const view = Object.fromEntries(['hatch', 'group', 'title', 'label', 'center',
  'rim', 'body', 'pulse', 'ring', 'badge'].map(key => [key, new Element()]));
const titles = ['Handoff scheduling engineering OS run', 'Report-task-four',
  'Short', 'Eleven chars', 'One two three four five', 'Longfirstword second'];
const results = titles.map(title => {
  paintNode({id: 'node', title, state: 'idle', kind: 'claude'}, view);
  return {lines: view.label.children.length ? view.label.children.map(child => child.textContent)
    : [view.label.textContent], title: view.group.attributes.title,
    positions: view.label.children.map(child => [child.attributes.x, child.attributes.dy])};
});
console.log(JSON.stringify(results));
""")
        for result, title, lines in zip(output, [
                'Handoff scheduling engineering OS run', 'Report-task-four', 'Short',
                'Eleven chars', 'One two three four five', 'Longfirstword second'], [
                ['Handoff', 'scheduling…'], ['Report-tas…'], ['Short'],
                ['Eleven', 'chars'], ['One two', 'three four…'],
                ['Longfirstw…', 'second']]):
            self.assertEqual(result['lines'], lines)
            self.assertEqual(result['title'], title)
            if len(lines) == 2:
                self.assertEqual(result['positions'], [[0, 0], [0, 12]])

    def run_cluster_js(self, source):
        return run_js(DOM + page_functions(
            'html', 'button', 'clusterInfo', 'clusterRun', 'clusterItems',
            'renderCluster', 'renderFallback', 'detailLine', 'stepper',
            'matrixTable', 'gateContent', 'segmentBar', 'miniNode') + RUN_CLUSTER + source)

    def test_collapsed_run_cluster_renders_now_line_and_slice_bars(self):
        output = self.run_cluster_js("""
renderCluster(cluster);
const rows = byClass(cluster.panel, 'slice-row');
for (const row of rows) byClass(row, 'segments')[0]?.children[1].click();
console.log(JSON.stringify({panel: text(cluster.panel),
  rows: rows.map(row => ({text: text(row), bars: byClass(row, 'segments').length,
    parts: byClass(row, 'segments').flatMap(bar => bar.children.map(part => ({
      flex: part.style.flex, color: part.style.background, label: part.attributes['aria-label']
    })))})),
  steppers: byClass(cluster.panel, 'stepper').length, selections}));
""")
        self.assertIn('Checking the next delivery', output['panel'])
        self.assertNotIn('Proofs:', output['panel'])
        self.assertEqual(len(output['rows']), 3)
        for index, row in enumerate(output['rows'], 1):
            self.assertIn(f'Slice {index}', row['text'])
            self.assertIn('verified 2 of 6 units', row['text'])
            self.assertEqual(row['bars'], 1)
            self.assertEqual([part['flex'] for part in row['parts']],
                             ['1 1 0', '2 1 0', '3 1 0'])
            self.assertEqual(row['parts'][1]['color'], '#298456')
            self.assertEqual(row['parts'][1]['label'],
                             f'{index}-M: verified, M (2 units)')
        self.assertEqual(output['steppers'], 0)
        self.assertEqual(output['selections'], [
            {'context': {'run': 'run_test', 'package': f'{index}-M'}, 'node': 'worker'}
            for index in range(1, 4)])

    def test_collapsed_counts_line_only_when_nonzero(self):
        output = self.run_cluster_js("""
const results = [];
for (const projected of [true, false]) {
  info.run = projected ? 'run_test' : null;
  for (const [waiting, stalled] of [[0, 0], [1, 0], [0, 2], [0, 0]]) {
    Object.assign(info, {waiting, stalled}); renderCluster(cluster);
    results.push(byClass(cluster.panel, 'cluster-summary').map(text));
  }
}
console.log(JSON.stringify(results));
""")
        self.assertEqual(output, [
            [], ['waiting on you: 1 · 0 stalled'], ['waiting on you: 0 · 2 stalled'], []
        ] * 2)

    def test_matrix_holds_stepper_and_proofs(self):
        output = self.run_cluster_js("""
expanded.add(cluster.id); renderCluster(cluster);
const table = byClass(cluster.panel, 'matrix')[0];
const rows = table.children[1].children;
const proof = cluster.panel.children[cluster.panel.children.indexOf(table) + 1];
for (const row of rows) byClass(row.children[4], 'segments')[0].children[1].click();
console.log(JSON.stringify({
  rows: rows.map(row => ({first: text(row.children[0]),
    steppers: byClass(row.children[0], 'stepper').length,
    dots: descendants(row.children[0]).filter(child => child.tagName === 'i').length,
    bars: byClass(row.children[4], 'segments').length})),
  steppers: byClass(cluster.panel, 'stepper').length,
  slices: byClass(cluster.panel, 'slice-row').length,
  proof: proof ? {tag: proof.tagName, text: text(proof)} : null, selections}));
""")
        self.assertEqual(len(output['rows']), 3)
        for index, row in enumerate(output['rows'], 1):
            self.assertIn(f'Slice {index}', row['first'])
            self.assertEqual(row['steppers'], 1)
            self.assertEqual(row['dots'], 7)
            self.assertEqual(row['bars'], 1)
        self.assertEqual(output['steppers'], 3)
        self.assertEqual(output['slices'], 0)
        self.assertEqual(output['proof'], {'tag': 'p', 'text': 'Proofs: E1 pass'})
        self.assertEqual(output['selections'], [
            {'context': {'run': 'run_test', 'package': f'{index}-M'}, 'node': 'worker'}
            for index in range(1, 4)])

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
            self.assertNotIn('Open run plan', rendered)
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
