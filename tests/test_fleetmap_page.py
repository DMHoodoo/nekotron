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
  focus() { document.activeElement = this; }
  blur() { if (document.activeElement === this) document.activeElement = null; }
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
document.listeners = {};
document.activeElement = null;
document.addEventListener = (name, action) => { (document.listeners[name] = document.listeners[name] || []).push(action); };
document.dispatch = (name, event) => { event.preventDefault = event.preventDefault || (() => {}); (document.listeners[name] || []).forEach(action => action(event)); };
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


FALLBACK_FIXTURE = """
snapshot = {hosts: [{name: 'local'}], runs: {}, edges: [], clusters: {
  Fallback: {name: 'Fallback', run: 'run_missing', matrix_host: 'local',
    fallbacks: [{run: 'run_missing', now: '', note: 'projection v1, Chief must re-render'}]}},
  nodes: [{id: 'worker', title: 'Worker', state: 'idle', kind: 'claude',
    host: 'local', cluster: 'Fallback'}]};
$('map-scroll').clientWidth = 1200;
const fallback = snapshot.clusters.Fallback.fallbacks[0];
const cluster = () => [...clusters.values()][0];
const gridTop = () => cluster().y + 28;
"""


class FleetMapPage(unittest.TestCase):
    def test_fallback_now_line_wraps_inside_panel(self):
        output = run_page_js(FALLBACK_FIXTURE + """
fallback.now = 'x'.repeat(200);
render();
const panel = cluster().panel;
const now = descendants(panel).find(el => text(el).startsWith('Now:') && el.tagName === 'p');
const chain = [];
// Every element between the panel and the Now line must allow wrapping.
const walk = (el, trail) => el === now ? chain.push(trail) :
  (el.children || []).forEach(child => walk(child, [...trail, el]));
walk(panel, []);
console.log(JSON.stringify({text: text(panel), found: Boolean(now), chains: chain.length,
  noWrap: chain.flat().concat([now]).some(el => /nowrap|pre$/.test(el.style.whiteSpace || '')),
  contentHeight: Number(cluster().content.attributes.height),
  workerY: endpoint('worker').y, top: cluster().y - cluster().headerHeight}));
""")
        self.assertIn('x' * 200, output['text'])
        self.assertTrue(output['found'])
        self.assertEqual(output['chains'], 1)
        self.assertFalse(output['noWrap'])
        rule = re.search(r'\.cluster-content\s*\{[^}]*\}',
                         (ROOT / 'kitty/fleetmap/page.html').read_text()).group()
        self.assertRegex(rule, r'overflow-wrap:\s*anywhere')
        # Heading 32 + run 30 + five-line Now 102 + projection 30 + 20 padding.
        self.assertGreaterEqual(output['contentHeight'], 214)
        self.assertGreater(output['workerY'], output['top'] + 214)

    def test_node_grid_starts_below_cluster_content(self):
        output = run_page_js(FALLBACK_FIXTURE + """
snapshot.clusters.Fallback.fallbacks = [];
render();
const empty = {header: cluster().headerHeight, top: gridTop(), y: endpoint('worker').y};
snapshot.clusters.Fallback.fallbacks = [{run: 'run_missing',
  now: 'Working on the next delivery '.repeat(4), note: 'projection v1, Chief must re-render'}];
render();
const three = {header: cluster().headerHeight, top: gridTop(), y: endpoint('worker').y};
const stable = {x: endpoint('worker').x};
render();
const again = {y: endpoint('worker').y};
snapshot.clusters.Fallback.fallbacks[0].now += ' more details'.repeat(35);
render();
const longer = {header: cluster().headerHeight, y: endpoint('worker').y,
  height: Number(cluster().content.attributes.height)};
console.log(JSON.stringify({empty, three, again, longer, stable}));
""")
        self.assertEqual(output['empty']['header'], 125)
        # Heading 32 + run 30 + three-line Now 66 + projection 30 + 20 padding.
        self.assertGreaterEqual(output['three']['header'], 178)
        self.assertGreater(output['three']['y'], output['empty']['y'])
        self.assertEqual(output['three']['y'], output['again']['y'])
        self.assertGreater(output['longer']['header'], output['three']['header'])
        self.assertGreater(output['longer']['y'], output['three']['y'])
        self.assertGreaterEqual(output['longer']['height'], output['longer']['header'])

    def test_run_backed_grid_starts_below_slice_bars_under_long_now(self):
        output = run_page_js("""
const row = id => ({id, name: 'Slice ' + id, stage: 'implementing',
  stepper: [1, 1, 1, 1, 0, 0, 0], live: [], cells: {
    goal: {verdict: 'pass'}, design: {verdict: 'pass'}, plan: {verdict: 'pass'},
    implementing: {verified_units: 2, total_units: 6, segments: [
      {id: id + '-S', size: 1, state: 'planned', node: null},
      {id: id + '-L', size: 3, state: 'running', node: null}]},
    review: {chips: []}, delivery: {verdict: 'pending'}, accepted: {state: 'pending'}}});
snapshot = {hosts: [{name: 'local'}], edges: [], runs: {run_test: {run: 'run_test',
  title: 'Review run', now: 'n'.repeat(290), rows: [row('1'), row('2'), row('3')],
  proofs: [], chief_node: null}},
  clusters: {'Review run': {name: 'Review run', run: 'run_test', matrix_host: 'local',
    waiting: 0, stalled: 0}},
  nodes: [{id: 'worker', title: 'Worker', state: 'idle', kind: 'claude',
    host: 'local', cluster: 'Review run'}]};
$('map-scroll').clientWidth = 1200;
render();
const cluster = [...clusters.values()][0];
console.log(JSON.stringify({y: endpoint('worker').y, top: cluster.y - cluster.headerHeight,
  slices: byClass(cluster.panel, 'slice-row').length}));
""")
        self.assertEqual(output['slices'], 3)
        # Heading 32 + six-line Now 120 + three slice rows 180 + 20 padding.
        self.assertGreater(output['y'], output['top'] + 352)

    def test_growing_cluster_pushes_lower_cluster_and_shrinks_back(self):
        output = run_page_js("""
const make = (id, cluster, now) => ({node: {id, title: id, state: 'idle', kind: 'claude',
  host: 'local', cluster}, info: {name: cluster, run: 'run_' + id, matrix_host: 'local',
  fallbacks: [{run: 'run_' + id, now, note: ''}]}});
const state = {Upper: make('up', 'Upper', 'short'), Lower: make('low', 'Lower', 'short'),
  Other: make('oth', 'Other', 'short')};
const publish = names => {
  snapshot = {hosts: [{name: 'local'}, {name: 'remote'}], runs: {}, edges: [],
    clusters: Object.fromEntries(names.map(n => [n, state[n].info])),
    nodes: names.map(n => state[n].node)};
  state.Other.node.host = 'remote'; state.Other.info.matrix_host = 'remote';
  render();
};
$('map-scroll').clientWidth = 1200;
const box = name => { const c = [...clusters.values()].find(c => c.name === name);
  return {top: c.geometry.top, bottom: c.geometry.top + c.geometry.height, y: c.y}; };
publish(['Upper', 'Other']);
publish(['Upper', 'Other', 'Lower']);
const first = {upper: box('Upper'), lower: box('Lower'), other: box('Other')};
state.Upper.info.fallbacks[0].now = 'word '.repeat(60);
publish(['Upper', 'Other', 'Lower']);
const grown = {upper: box('Upper'), lower: box('Lower'), other: box('Other')};
state.Upper.info.fallbacks[0].now = 'short';
publish(['Upper', 'Other', 'Lower']);
console.log(JSON.stringify({first, grown, shrunk: {upper: box('Upper'), lower: box('Lower'),
  other: box('Other')}}));
""")
        self.assertGreater(output['grown']['upper']['bottom'], output['first']['upper']['bottom'])
        self.assertGreaterEqual(output['grown']['lower']['top'], output['grown']['upper']['bottom'])
        self.assertGreater(output['first']['lower']['top'], output['first']['upper']['top'])
        self.assertEqual(output['shrunk'], output['first'])
        self.assertEqual(output['grown']['other'], output['first']['other'])

    def test_empty_fallback_cluster_panel_is_not_clipped(self):
        output = run_page_js(FALLBACK_FIXTURE + """
snapshot.nodes = [];
// Two wrapped lines at the 340px default width.
fallback.now = 'Audit the integration layer. '.repeat(3);
render();
const first = {height: Number(cluster().content.attributes.height)};
fallback.now += 'And then the delivery pipeline. '.repeat(2);
render();
console.log(JSON.stringify({first, height: Number(cluster().content.attributes.height),
  header: cluster().headerHeight, grid: cluster().grid.attributes.transform,
  now: text(cluster().panel).length}));
""")
        # Heading 32 + run 30 + Now (two lines at 48 columns) 48 + projection 30 + margin.
        self.assertGreaterEqual(output['first']['height'], 32 + 30 + 2 * 18 + 12 + 30)
        self.assertGreater(output['height'], output['first']['height'])
        self.assertEqual(output['height'], output['header'])

    def test_wrapping_cluster_name_adds_heading_lines(self):
        output = run_page_js(FALLBACK_FIXTURE + """
snapshot.clusters.Fallback.fallbacks = [];
render();
const plain = Number(cluster().content.attributes.height);
snapshot.clusters.Fallback.short_name = 'Glow commissions integrity audit 2026-10-08 backlog';
snapshot.clusters.Fallback.fallbacks = [{run: 'r', now: 'n', note: ''}];
render();
const long = Number(cluster().content.attributes.height);
snapshot.clusters.Fallback.short_name = 'Audit';
render();
console.log(JSON.stringify({plain, long, short: Number(cluster().content.attributes.height)}));
""")
        # The name (51 characters, 433px) takes two lines of the 320px content width.
        self.assertGreaterEqual(output['long'] - output['short'], 2 * 20)

    def test_removed_hovered_node_clears_hovered_id(self):
        output = run_page_js(EDGE_FIXTURE + """
nodeViews.get('b').group.listeners.mouseenter();
const before = hoveredId;
snapshot.nodes = snapshot.nodes.filter(node => node.id !== 'b');
snapshot.edges = [];
render();
console.log(JSON.stringify({before, hoveredId, edges: drawn()}));
""")
        self.assertEqual(output, {'before': 'b', 'hoveredId': None, 'edges': []})

    def test_selecting_isolated_node_draws_no_edge(self):
        output = run_page_js(EDGE_FIXTURE + """
snapshot.edges = [snapshot.edges[1]];
render();
selectNode('a');
console.log(JSON.stringify({selectedId, edges: drawn()}));
""")
        self.assertEqual(output, {'selectedId': 'a', 'edges': []})

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
            'selectCluster', 'renderRail', 'lastTouched', 'stateLine', 'renderContext', 'openBroadcast',
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
        output = run_js(DOM + page_functions('age', 'hoverText', 'nodeState', 'nodeMatches', 'nodeDimmed', 'paintNode') + """
const svg = (tag, attrs = {}) => {
  const element = new Element(tag);
  for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, value);
  return element;
};
const stateFilter = null, searchQuery = '', selectedId = null, hoveredId = null, snapshot = {edges: []};
const colors = {idle: '#888'}, secondsSince = () => 0;
const view = Object.fromEntries(['hatch', 'group', 'title', 'label', 'center',
  'rim', 'body', 'pulse', 'ring', 'badge'].map(key => [key, new Element()]));
const titles = ['Handoff scheduling engineering OS run', 'Report-task-four',
  'Short', 'Eleven chars', 'One two three four five', 'Longfirstword second'];
const results = titles.map(title => {
  paintNode({id: 'node', title, state: 'idle', kind: 'claude'}, view);
  return {lines: view.label.children.length ? view.label.children.map(child => child.textContent)
    : [view.label.textContent], aria: view.group.attributes['aria-label'],
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
            self.assertEqual(result['aria'], title + ', idle, claude')
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
                                     'clusterRun', 'nodeText', 'panelContentHeight', 'layoutFleet', 'endpoint',
                                     'foldable', 'isFolded', 'clusterRetired')
        output = run_js(source + """
const svg = () => new Element();
const positions = new Map(), regions = new Map(), clusters = new Map(), expanded = new Set(), unfolded = new Set();
const MIN_REGION = 420, CELL = 70, GAP = 16;
let layoutSignature = '', layoutModeSignature = '';
function renderCluster() {}
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

    def run_decision_js(self, source, chief=True):
        return self.run_selection_js(page_functions(
            'renderDecisions', 'openRun', 'showDecision', 'decisionCard', 'openSend', 'openRunPlan',
            'clusterKey', 'svg') + """
let decisionSignature = '', actionBusy = false;
const makeNode = () => ({group: new Element(), label: new Element()}), paintNode = () => {};
const requests = [], NS = 'svg';
document.createElementNS = (_, tag) => new Element(tag);
const request = async (path, body) => requests.push([path, body]);
const runAction = async work => work();
$('send-form').hidden = true; $('send-text').value = 'stale'; $('send-text').focus = () => {};
run.chief_node = 'chief';
Object.assign(run, {merge_gate: {ready: false, classDOpen: 0, classBUnratified: 0},
  run_plan: {path: 'plan.md', commit: 'abc'}, notes: []});
""" + ("""
const chief = {id: 'chief', title: 'Chief', cluster: 'Review run', host: 'local',
  state: 'idle', kind: 'claude'};
snapshot.nodes = [chief]; nodes.set('chief', chief);
""" if chief else "") + """
snapshot.decisions = [{run: 'run_test', title: 'Review run', id: 'E3', class: 'C',
  text: 'Approve the delivery order for slice 2', packet: 'P-12', applyAt: null}];
const chip = () => descendants($('decisions')).find(el => el.tagName === 'button');
const card = () => byClass($('decision-slot'), 'decision-card')[0];
const buttonNamed = (root, name) => descendants(root).find(el => el.tagName === 'button' && text(el) === name);
renderDecisions();
""" + source)

    def test_decision_chip_has_three_lines(self):
        output = self.run_decision_js("""
console.log(JSON.stringify(chip().children.map(text)));
""")
        self.assertEqual(output, ['Review run', 'Approve the delivery order for slice 2',
                                  'Class C · E3 · apply-by —'])

    def test_clicking_decision_opens_run_and_card(self):
        output = self.run_decision_js("""
chip().click();
const found = card();
console.log(JSON.stringify({expanded: [...expanded], decision: selectedContext?.decision,
  run: selectedContext?.run, card: found ? text(found) : null,
  mini: found ? byClass(found, 'live-node').length : 0,
  buttons: found ? descendants(found).filter(el => el.tagName === 'button').map(text) : []}));
""")
        self.assertEqual(output['expanded'], ['["local","Review run"]'])
        self.assertEqual(output['decision'], 'E3')
        self.assertEqual(output['run'], 'run_test')
        for part in ('Approve the delivery order for slice 2', 'P-12',
                     'Clears when the Chief records it'):
            self.assertIn(part, output['card'])
        self.assertEqual(output['mini'], 1)
        self.assertEqual(output['buttons'], ['Reply to Chief', 'Open run plan'])

    def test_reply_to_chief_prefills_send_overlay(self):
        output = self.run_decision_js("""
chip().click();
buttonNamed(card(), 'Reply to Chief').click();
console.log(JSON.stringify({dialog: $('overlay').open, node: dialogNodeId,
  title: $('overlay-title').textContent, formHidden: $('send-form').hidden,
  value: $('send-text').value}));
""")
        self.assertTrue(output['dialog'])
        self.assertEqual(output['node'], 'chief')
        self.assertIn('Chief', output['title'])
        self.assertFalse(output['formHidden'])
        self.assertEqual(output['value'], 'Decision E3: ')

    def test_decision_card_without_chief_node(self):
        output = self.run_decision_js("""
chip().click();
const found = card();
console.log(JSON.stringify({card: found ? text(found) : null,
  mini: found ? byClass(found, 'live-node').length : 0,
  buttons: found ? descendants(found).filter(el => el.tagName === 'button').map(text) : []}));
""", chief=False)
        self.assertIn('Approve the delivery order for slice 2', output['card'])
        self.assertEqual(output['mini'], 0)
        self.assertEqual(output['buttons'], ['Open run plan'])


    def test_decision_card_is_first_in_rail_and_renders_once(self):
        output = self.run_decision_js("""
let renders = 0; const inner = renderRail;
renderRail = function() { renders++; return inner(); };
chip().click();
console.log(JSON.stringify({first: $('decision-slot').children[0] === card(),
  renders, runCard: text($('context-details')).includes('Merge gate')}));
""")
        self.assertTrue(output['first'])
        self.assertEqual(output['renders'], 1)
        self.assertTrue(output['runCard'])
        html = (ROOT / 'kitty/fleetmap/page.html').read_text()
        rail = html[html.index('<aside id="rail"'):]
        self.assertLess(rail.index('id="decision-slot"'), rail.index('id="action-error"'))

    def test_decision_card_open_run_plan_requests_the_decision_run(self):
        output = self.run_decision_js("""
chip().click();
buttonNamed(card(), 'Open run plan').click();
await Promise.resolve();
console.log(JSON.stringify(requests));
""".replace('await Promise.resolve();', ''))
        self.assertEqual(output, [['/api/open-plan', {'run': 'run_test'}]])


    HEADER_FIXTURE = """
const states = [...Array(2).fill('working'), 'attention', ...Array(10).fill('idle'),
  ...Array(5).fill('done'), ...Array(4).fill('unknown')];
snapshot = {hosts: [{name: 'local'}], clusters: {}, runs: {}, edges: [], generated_at: Date.now() / 1000,
  nodes: states.map((state, index) => ({id: 'n' + index, title: 'n' + index, state, kind: 'claude',
    host: 'local', cluster: 'Traffic'}))};
$('map-scroll').clientWidth = 1200;
render();
renderStatus();
const counts = () => descendants($('status')).filter(item => item.dataset?.state);
const countFor = state => counts().find(item => item.dataset.state === state);
const opacities = () => Object.fromEntries(snapshot.nodes.map(node =>
  [node.id, nodeViews.get(node.id).group.style.opacity]));
"""

    def test_header_counts_by_state(self):
        output = run_page_js(self.HEADER_FIXTURE + """
console.log(JSON.stringify({text: text($('status')).replace(/\\s+/g, ' ').trim(),
  states: counts().map(item => item.dataset.state)}));
""")
        self.assertTrue(output['text'].startswith(
            '22 sessions · 2 working · 1 need you · 15 idle'), output['text'])
        self.assertEqual(output['states'], ['working', 'attention', 'idle'])

    def test_state_filter_dims_others_and_toggles_off(self):
        output = run_page_js(self.HEADER_FIXTURE + """
countFor('working').click();
const on = {filter: stateFilter, opacities: opacities()};
countFor('working').click();
const off = {filter: stateFilter, opacities: opacities()};
countFor('idle').click();
const idle = opacities();
countFor('attention').click();
console.log(JSON.stringify({on, off, idleDone: [idle.n13, idle.n0], filter: stateFilter,
  attention: opacities().n2}));
""")
        self.assertEqual(output['on']['filter'], 'working')
        self.assertEqual(output['on']['opacities']['n0'], 1)
        self.assertEqual(output['on']['opacities']['n2'], 0.25)
        self.assertEqual(output['on']['opacities']['n5'], 0.25)
        self.assertIsNone(output['off']['filter'])
        self.assertEqual(set(output['off']['opacities'].values()), {1})
        self.assertEqual(output['idleDone'], [1, 0.25])
        self.assertEqual(output['filter'], 'attention')
        self.assertEqual(output['attention'], 1)

    def test_region_status_word(self):
        output = run_page_js("""
$('map-scroll').clientWidth = 1200;
const word = host => {
  snapshot = {hosts: [Object.assign({name: 'local'}, host)], clusters: {}, runs: {}, nodes: [], edges: []};
  render();
  return regions.get('local').metrics.textContent;
};
console.log(JSON.stringify([
  word({memory: {free_pct: 55, swap_gb: 0}, workers: 1, cap: 4}),
  word({memory: {free_pct: 39.9, swap_gb: 0}, workers: 1, cap: 4}),
  word({memory: {free_pct: 55, swap_gb: 0}, workers: 5, cap: 4}),
  word({memory: {free_pct: 40, swap_gb: 0}, workers: 4, cap: 4})]));
""")
        self.assertTrue(output[0].startswith('OK · 55.0% free'), output[0])
        self.assertTrue(output[1].startswith('Tight · '), output[1])
        self.assertTrue(output[2].startswith('Over cap · '), output[2])
        self.assertTrue(output[3].startswith('OK · '), output[3])

    FOLD_FIXTURE = """
$('map-scroll').clientWidth = 1200;
const hours = h => Date.now() / 1000 - h * 3600;
const mk = (id, state, h, extra = {}) => Object.assign({id, title: id, state, kind: 'claude',
  host: 'local', cluster: 'Box', you_at: hours(h), it_at: hours(h)}, extra);
const load = list => {
  snapshot = {generated_at: Date.now() / 1000, hosts: [{name: 'local'}], clusters: {}, runs: {},
    nodes: list, edges: []};
  render(); renderStatus();
};
const cluster = () => [...clusters.values()][0];
const unique = list => [...new Set(list)];
const drawnNodes = () => unique(byClass(cluster().grid, 'node')).filter(g => g.style.display !== 'none');
const chips = () => unique(byClass(cluster().grid, 'fold-chip')).filter(g => g.style.display !== 'none');
"""

    def test_old_idle_nodes_fold_into_a_chip(self):
        output = run_page_js(self.FOLD_FIXTURE + """
load([mk('a', 'idle', 30), mk('b', 'idle', 30), mk('c', 'done', 30)]);
console.log(JSON.stringify({nodes: drawnNodes().length, chips: chips().map(text)}));
""")
        self.assertEqual(output['nodes'], 0)
        self.assertEqual([chip.strip() for chip in output['chips']], ['3 idle'])

    def test_working_and_recent_nodes_never_fold(self):
        output = run_page_js(self.FOLD_FIXTURE + """
load([mk('w', 'working', 30), mk('r', 'idle', 2), mk('t', 'attention', 30), mk('o', 'idle', 30)]);
console.log(JSON.stringify({nodes: drawnNodes().length, chips: chips().map(text)}));
""")
        self.assertEqual(output['nodes'], 3)
        self.assertEqual([chip.strip() for chip in output['chips']], ['1 idle'])

    def test_never_prompted_idle_node_folds(self):
        output = run_page_js(self.FOLD_FIXTURE + """
load([{id: 'n', title: 'n', state: 'idle', kind: 'claude', host: 'local', cluster: 'Box',
  never_prompted: true, you_at: null, it_at: null}]);
console.log(JSON.stringify({nodes: drawnNodes().length, chips: chips().length}));
""")
        self.assertEqual(output, {'nodes': 0, 'chips': 1})

    def test_retired_chip_lists_in_rail(self):
        output = run_page_js(self.FOLD_FIXTURE + """
const retired = [
  {title: 'Worker one', dispatchId: 'd1', state: 'released', retainedFor: 7200, host: 'local'},
  {title: 'Worker two', dispatchId: 'd2', state: 'abandoned', retainedFor: 90, host: 'local'}];
const shownRetired = () => unique(byClass(cluster().grid, 'retired-chip')).filter(g => g.style.display !== 'none');
snapshot = {generated_at: Date.now() / 1000, hosts: [{name: 'local'}],
  clusters: {Box: {name: 'Box', full_name: 'Box', short_name: 'Box', retired_workers: retired}},
  runs: {}, nodes: [mk('a', 'working', 1)], edges: []};
render(); renderStatus();
const shown = shownRetired().map(text);
const slot = positions.get('retired:' + cluster().id);
const overlap = [...positions].filter(([id, p]) => id !== 'retired:' + cluster().id && p.cluster === cluster().id && p.x === slot.x && p.y === slot.y).length;
shownRetired()[0].click();
const rail = text($('context-details'));
const railHidden = $('context-rail').hidden;
stateFilter = 'idle'; render();
const dimmed = shownRetired()[0].style.opacity;
stateFilter = null;
snapshot.clusters.Box.retired_workers = []; render();
console.log(JSON.stringify({shown, overlap, rail, railHidden, dimmed, gone: shownRetired().length,
  nodes: drawnNodes().length}));
""")
        self.assertEqual([c.strip() for c in output['shown']], ['2 retired workers'])
        self.assertEqual(output['overlap'], 0)
        self.assertFalse(output['railHidden'])
        for expected in ('Worker one', 'released', '2h', 'Worker two', 'abandoned', '1m'):
            self.assertIn(expected, output['rail'])
        self.assertEqual(output['dimmed'], .25)
        self.assertEqual((output['gone'], output['nodes']), (0, 1))

    def test_clicking_chip_unfolds_cluster(self):
        output = run_page_js(self.FOLD_FIXTURE + """
load([mk('a', 'idle', 30), mk('b', 'idle', 30), mk('c', 'idle', 30)]);
chips()[0].click();
const after = {nodes: drawnNodes().length, chips: chips().length};
load(snapshot.nodes);
console.log(JSON.stringify({after, reload: {nodes: drawnNodes().length, chips: chips().length}}));
""")
        self.assertEqual(output['after'], {'nodes': 3, 'chips': 0})
        self.assertEqual(output['reload'], {'nodes': 3, 'chips': 0})

    def test_retired_only_cluster_renders_box_and_chip(self):
        output = run_page_js(self.FOLD_FIXTURE + """
const retired = ['a', 'b', 'c', 'd', 'e'].map(n => ({title: 'Worker ' + n, dispatchId: 'd' + n,
  state: 'released', retainedFor: 600, host: 'local'}));
snapshot = {generated_at: Date.now() / 1000, hosts: [{name: 'local'}],
  clusters: {Past: {name: 'Past', full_name: 'Past', short_name: 'Past', retired_workers: retired}},
  runs: {}, nodes: [], edges: []};
render(); renderStatus();
const box = [...clusters.values()].filter(c => c.group.style.display !== 'none').length;
const shown = unique(byClass(cluster().grid, 'retired-chip')).filter(g => g.style.display !== 'none');
shown[0].click();
console.log(JSON.stringify({box, shown: shown.map(text), rail: text($('context-details'))}));
""")
        self.assertEqual(output['box'], 1)
        self.assertEqual([c.strip() for c in output['shown']], ['5 retired workers'])
        for title in ('Worker a', 'Worker b', 'Worker c', 'Worker d', 'Worker e'):
            self.assertIn(title, output['rail'])

    def test_unfolding_restores_node_positions(self):
        output = run_page_js(self.FOLD_FIXTURE + """
const list = [mk('a', 'idle', 1), mk('b', 'idle', 1), mk('c', 'idle', 1)];
load(list);
const before = Object.fromEntries(list.map(n => [n.id, endpoint(n.id)]));
list[0].you_at = list[0].it_at = hours(30); list[1].you_at = list[1].it_at = hours(30);
load(list);
const folded = {nodes: drawnNodes().length, chips: chips().length, c: endpoint('c')};
chips()[0].click();
console.log(JSON.stringify({before, folded, after: Object.fromEntries(list.map(n => [n.id, endpoint(n.id)]))}));
""")
        self.assertEqual(output['folded'], {'nodes': 1, 'chips': 1, 'c': output['before']['c']})
        self.assertEqual(output['after'], output['before'])
    def test_chip_never_shares_a_slot_with_a_reactivated_node(self):
        output = run_page_js(self.FOLD_FIXTURE + """
const list = [mk('a', 'idle', 1), mk('b', 'idle', 1), mk('c', 'idle', 1)];
load(list);
for (const node of list) node.you_at = node.it_at = hours(30);
load(list);
list[0].state = 'working'; list[0].you_at = list[0].it_at = hours(0);
load(list);
const chip = chips()[0].attributes.transform;
console.log(JSON.stringify({chip, chips: chips().map(text), drawn: drawnNodes().length,
  node: nodeViews.get('a').group.attributes.transform}));
""")
        self.assertEqual([c.strip() for c in output['chips']], ['2 idle'])
        self.assertEqual(output['drawn'], 1)
        self.assertNotEqual(output['chip'], output['node'])

    def test_chip_dims_with_the_state_filter(self):
        output = run_page_js(self.FOLD_FIXTURE + """
load([mk('a', 'idle', 30), mk('b', 'working', 1)]);
const opacity = () => chips()[0].style.opacity;
const none = opacity();
setStateFilter('working'); const working = opacity();
setStateFilter('working'); setStateFilter('idle'); const idle = opacity();
console.log(JSON.stringify({none, working, idle}));
""")
        self.assertEqual(output, {'none': 1, 'working': 0.25, 'idle': 1})

    def test_header_counts_include_folded(self):
        output = run_page_js(self.FOLD_FIXTURE + """
load([mk('a', 'idle', 30), mk('b', 'done', 30), mk('c', 'working', 30), mk('d', 'attention', 1)]);
console.log(JSON.stringify({chips: chips().length, text: text($('status')).replace(/\\s+/g, ' ').trim()}));
""")
        self.assertEqual(output['chips'], 1)
        self.assertTrue(output['text'].startswith(
            '4 sessions · 1 working · 1 need you · 2 idle'), output['text'])

    def test_region_status_word_omitted_when_unknown(self):
        output = run_page_js("""
$('map-scroll').clientWidth = 1200;
const word = host => {
  snapshot = {hosts: [Object.assign({name: 'local'}, host)], clusters: {}, runs: {}, nodes: [], edges: []};
  render();
  return regions.get('local').metrics.textContent;
};
console.log(JSON.stringify([
  word({memory: {swap_gb: 0}, workers: 1, cap: 4}),
  word({memory: {free_pct: 55, swap_gb: 0}, cap: 4}),
  word({memory: {free_pct: 55, swap_gb: 0}, workers: 1}),
  word({})]));
""")
        for line in output:
            for status in ('OK', 'Tight', 'Over cap'):
                self.assertFalse(line.startswith(status), line)
            self.assertFalse(line.startswith(' ·'), line)
        self.assertTrue(output[1].startswith('55.0% free'), output[1])


    SEARCH_FIXTURE = """
const list = [
  {id: 'n1', title: 'Fix PR 6897 flaky test', state: 'working', kind: 'claude', host: 'local', cluster: 'Box'},
  {id: 'n2', title: 'Other', state: 'idle', kind: 'claude', host: 'local', cluster: 'Box', branch: 'main'},
  {id: 'n3', title: 'Third', state: 'working', kind: 'claude', host: 'local', cluster: 'Box', last_said: 'Done'}];
snapshot = {generated_at: Date.now() / 1000, hosts: [{name: 'local'}], clusters: {}, runs: {},
  nodes: list, edges: []};
$('map-scroll').clientWidth = 1200;
render(); renderStatus();
const statusText = () => text($('status')).replace(/\\s+/g, ' ').trim();
const opacities = () => Object.fromEntries(snapshot.nodes.map(node =>
  [node.id, nodeViews.get(node.id).group.style.opacity]));
const type = value => { $('search').value = value; $('search').listeners.input({target: $('search')}); };
"""

    def test_search_dims_non_matches_and_counts(self):
        output = run_page_js(self.SEARCH_FIXTURE + """
type('6897');
console.log(JSON.stringify({opacities: opacities(), status: statusText(),
  fields: ['main', 'DONE'].map(q => snapshot.nodes.filter(n => nodeMatches(n, q)).map(n => n.id))}));
""")
        self.assertEqual(output['opacities'], {'n1': 1, 'n2': 0.25, 'n3': 0.25})
        self.assertTrue(output['status'].endswith('· 1 match'), output['status'])
        self.assertEqual(output['fields'], [['n2'], ['n3']])

    def test_search_matches_the_repository_name_as_well_as_the_worktree_name(self):
        output = run_page_js(self.SEARCH_FIXTURE + """
const node = {title: 'T', repository: 'glow-core', repo: 'lookdown', branch: 'main'};
console.log(JSON.stringify(['glow-core', 'GLOW', 'lookdown', 'nekotron'].map(q => nodeMatches(node, q))));
""")
        self.assertEqual(output, [True, True, True, False])

    def test_search_unfolds_matching_folded_node(self):
        output = run_page_js(self.FOLD_FIXTURE + """
load([mk('a', 'idle', 30, {title: 'Fix PR 6897'}), mk('b', 'idle', 30), mk('c', 'idle', 30)]);
const state = () => ({nodes: drawnNodes().length, chips: chips().length});
const before = state();
$('search').value = '6897'; $('search').listeners.input({target: $('search')});
const during = Object.assign(state(), {opacity: drawnNodes()[0].style.opacity});
const unfoldedKept = unfolded.size;
$('search').value = ''; $('search').listeners.input({target: $('search')});
console.log(JSON.stringify({before, during, after: state(), unfoldedKept}));
""")
        self.assertEqual(output['before'], {'nodes': 0, 'chips': 1})
        self.assertEqual(output['during'], {'nodes': 1, 'opacity': 1, 'chips': 1})
        self.assertEqual(output['after'], {'nodes': 0, 'chips': 1})

    def test_slash_focuses_and_escape_clears(self):
        output = run_page_js(self.SEARCH_FIXTURE + """
document.dispatch('keydown', {key: '/'});
const focused = document.activeElement === $('search');
const other = new Element('input'); document.activeElement = other;
let prevented = false;
document.dispatch('keydown', {key: '/', preventDefault: () => { prevented = true; }});
const stolen = document.activeElement !== other;
document.activeElement = null;
type('6897');
document.dispatch('keydown', {key: 'Escape'});
console.log(JSON.stringify({focused, stolen, prevented, query: searchQuery, value: $('search').value,
  opacities: opacities(), status: statusText()}));
""")
        self.assertTrue(output['focused'])
        self.assertFalse(output['stolen'])
        self.assertFalse(output['prevented'])
        self.assertEqual(output['query'], '')
        self.assertEqual(output['value'], '')
        self.assertEqual(set(output['opacities'].values()), {1})
        self.assertNotIn('match', output['status'])

    def test_hover_has_title_doing_said_ages_repo(self):
        output = run_page_js(self.SEARCH_FIXTURE + """
const now = 1000000;
const long = 'x'.repeat(200);
const full = {id: 'h', title: 'Fix it', purpose: 'the first prompt', doing: long, last_said: long,
  you_at: now - 7300, it_at: now - 310, repository: 'glow-core', repo: 'wt-dir', branch: 'fix/it'};
const legacy = Object.assign({}, full, {repository: undefined});
console.log(JSON.stringify({lines: hoverText(full, now).split('\\n'), legacy: hoverText(legacy, now).split('\\n')[4]}));
""")
        cut = 'x' * 79 + '…'
        self.assertEqual(output['lines'], ['Fix it', 'Doing: ' + cut, 'Said: ' + cut,
                                           'You: 2h · It: 5m', 'glow-core · fix/it'])
        self.assertEqual(output['legacy'], 'wt-dir · fix/it')

    def test_rail_repo_row_shows_the_repository_name(self):
        output = run_page_js(self.FOLD_FIXTURE + """
load([mk('a', 'working', 1, {repository: 'glow-core', repo: 'lookdown'}), mk('b', 'working', 1, {repo: 'wt'})]);
selectNode('a');
const first = $('repo').textContent;
selectNode('b');
console.log(JSON.stringify([first, $('repo').textContent]));
""")
        self.assertEqual(output, ['glow-core', 'wt'])

    def test_hover_omits_missing_lines_and_never_shows_prompt(self):
        output = run_page_js(self.SEARCH_FIXTURE + """
const now = 1000000;
const node = {id: 'h', title: 'Fix it', purpose: 'p'.repeat(10000), you_at: now - 60, it_at: now - 5,
  repo: 'wt', branch: 'b'};
const card = hoverText(node, now);
console.log(JSON.stringify({lines: card.split('\\n'), hasPrompt: card.includes('ppp')}));
""")
        self.assertEqual(output['lines'], ['Fix it', 'You: 1m · It: 5s', 'wt · b'])
        self.assertFalse(output['hasPrompt'])

    def test_rendered_node_hover_never_contains_prompt(self):
        output = run_page_js("""
const now = 1000000;
const node = {id: 'untitled-1', title: '', purpose: 'SECRET '.repeat(1430), state: 'idle', kind: 'claude'};
snapshot = {hosts: [], clusters: {}, runs: {}, nodes: [node], edges: []};
const view = makeNode(node);
paintNode(node, view);
console.log(JSON.stringify({title: view.title.textContent, expected: hoverText(node, now),
  attr: view.group.attributes.title ?? null, aria: view.group.attributes['aria-label']}));
""")
        self.assertEqual(output['title'], output['expected'])
        self.assertEqual(output['title'], 'untitled-1')
        self.assertIsNone(output['attr'])
        self.assertEqual(output['aria'], 'untitled-1, idle, claude')
        for text in (output['title'], output['aria']):
            self.assertNotIn('SECRET', text)

    def test_rendered_node_hover_shows_full_card(self):
        output = run_page_js("""
const now = Date.now() / 1000;
const node = {id: 'full', title: 'Full card', purpose: 'SECRET prompt', doing: 'Fixing the test',
  last_said: 'Tests pass', you_at: now - 7300, it_at: now - 310, repository: 'glow-core',
  branch: 'fix/it', state: 'idle', kind: 'claude'};
snapshot = {hosts: [], clusters: {}, runs: {}, nodes: [node], edges: []};
const view = makeNode(node);
paintNode(node, view);
console.log(JSON.stringify({lines: view.title.textContent.split('\\n')}));
""")
        self.assertEqual(output['lines'], ['Full card', 'Doing: Fixing the test', 'Said: Tests pass',
                                           'You: 2h · It: 5m', 'glow-core · fix/it'])

    def test_on_map_label_never_falls_back_to_the_purpose(self):
        output = run_page_js("""
const node = {id: 'untitled-1', title: '', purpose: 'Write the quarterly report', state: 'idle', kind: 'claude'};
snapshot = {hosts: [], clusters: {}, runs: {}, nodes: [node], edges: []};
const view = makeNode(node);
paintNode(node, view);
console.log(JSON.stringify({label: text(view.label)}));
""")
        self.assertNotIn('Write', output['label'])
        self.assertIn('untitled-1', output['label'])

    def test_search_box_sits_next_to_the_help_button(self):
        html = (ROOT / 'kitty/fleetmap/page.html').read_text()
        self.assertIn('header input#search { margin-left: auto', html)
        self.assertNotIn('#legend-toggle { margin-left', html)

    RAIL_FIXTURE = """
const now = Date.now() / 1000;
const worker = {id: 'w', title: 'Worker', state: 'working', kind: 'claude', host: 'local', cluster: 'Box',
  doing: 'Fixing', last_said: 'Hi', you_at: now - 60, it_at: now - 300, purpose: 'First words',
  tmux: 'sess', hosting: 'tmux'};
snapshot = {generated_at: now, hosts: [{name: 'local'}], clusters: {}, runs: {}, nodes: [worker], edges: []};
$('map-scroll').clientWidth = 1200;
render();
document.querySelectorAll = () => [];
$('overlay').showModal = () => {}; $('screen').focus = () => {};
const reasonOf = async (node, behavior) => {
  nodes.set(node.id, node); selectedId = node.id;
  request = behavior;
  await $('actions').listeners.click({target: {dataset: {action: 'peek'}}});
  await new Promise(resolve => setTimeout(resolve, 5));
  return {text: $('overlay-text').textContent, screenHidden: $('screen').hidden};
};
"""

    def test_rail_leads_with_state_doing_said_ages(self):
        html = (ROOT / 'kitty/fleetmap/page.html').read_text()
        rail = html[html.index('<aside id="rail"'):html.index('</aside>')]
        order = re.findall(r'<(?:section|h2|p|dd|div|details|form)[^>]* id="([^"]+)"', rail)
        wanted = ['node-title', 'state-line', 'doing', 'said', 'you-age', 'it-age', 'actions',
                  'context-rail', 'first-prompt']
        positions = [order.index(name) for name in wanted]
        self.assertEqual(positions, sorted(positions), order)
        self.assertRegex(rail, r'<details id="first-prompt">\s*<summary>First prompt</summary>')
        output = run_page_js(self.RAIL_FIXTURE + """
const lines = {};
for (const [name, patch] of Object.entries({working: {}, stalled: {stalled: true}, attention: {state: 'attention'},
  idle: {state: 'idle', you_at: now - 5 * 86400, it_at: now - 3 * 86400},
  youNewer: {state: 'idle', you_at: now - 120, it_at: now - 3 * 86400},
  done: {state: 'done', you_at: now - 3 * 86400, it_at: now - 7200},
  doneYouNewer: {state: 'done', you_at: now - 600, it_at: now - 7200},
  quiet: {state: 'idle', you_at: null, it_at: null}}))
  lines[name] = stateLine(Object.assign({}, worker, patch), now);
selectNode('w');
console.log(JSON.stringify({lines, rendered: text($('state-line')), doing: $('doing').textContent, said: $('said').textContent}));
""")
        self.assertEqual(output['lines'], {
            'working': 'working · pulsing 5m', 'stalled': 'stalled', 'attention': 'needs you',
            'idle': 'idle 3d', 'youNewer': 'idle 2m', 'done': 'done 2h', 'doneYouNewer': 'done 10m',
            'quiet': 'idle'})
        self.assertEqual(output['rendered'], 'working · pulsing 5m')
        self.assertEqual((output['doing'], output['said']), ('Fixing', 'Hi'))

    def test_rail_omits_unavailable_actions_and_parent(self):
        output = run_page_js(self.RAIL_FIXTURE + """
const sub = {id: 's', title: 'Sub', state: 'idle', kind: 'subagent', host: 'local', cluster: 'Box', parent: 'gone'};
const bare = {id: 'b', title: 'Bare', state: 'idle', kind: 'claude', host: 'local', cluster: 'Box'};
const kid = {id: 'k', title: 'Kid', state: 'idle', kind: 'subagent', host: 'local', cluster: 'Box', parent: 'w'};
snapshot.nodes.push(sub, bare, kid);
for (const node of snapshot.nodes) nodes.set(node.id, node);
const seen = {};
for (const id of ['w', 's', 'b', 'k']) {
  selectNode(id);
  seen[id] = {actionsHidden: $('actions').hidden, parentHidden: $('parent-row').hidden,
    parent: text($('parent-link')), railText: text($('details'))};
}
console.log(JSON.stringify(seen));
""")
        self.assertFalse(output['w']['actionsHidden'])
        self.assertTrue(output['b']['actionsHidden'])
        self.assertTrue(output['s']['parentHidden'])
        self.assertFalse(output['k']['parentHidden'])
        self.assertEqual(output['k']['parent'], 'Open parent: Worker')
        for view in output.values():
            self.assertNotIn('unavailable', view['railText'] + view['parent'])
        html = (ROOT / 'kitty/fleetmap/page.html').read_text()
        self.assertNotIn("|| 'unavailable'", html)

    def test_rail_button_labels(self):
        html = (ROOT / 'kitty/fleetmap/page.html').read_text()
        rail = html[html.index('<aside id="rail"'):html.index('</aside>')]
        labels = re.findall(r'<button[^>]*>([^<]+)</button>', rail)
        for label in ('Peek', 'Jump', 'Send', 'Close', 'Add to a project', 'Move to another box'):
            self.assertIn(label, labels)
        for old in ('Save slice / stage', 'Move session'):
            self.assertNotIn(old, labels)

    def test_first_prompt_is_collapsed(self):
        html = (ROOT / 'kitty/fleetmap/page.html').read_text()
        tag = re.search(r'<details id="first-prompt"([^>]*)>(.*?)</details>', html, re.DOTALL)
        self.assertNotIn('open', tag.group(1))
        self.assertIn('id="purpose"', tag.group(2))
        output = run_page_js(self.RAIL_FIXTURE + """
selectNode('w');
console.log(JSON.stringify({purpose: $('purpose').textContent}));
""")
        self.assertEqual(output['purpose'], 'First words')

    def test_peek_empty_screen_states_reason(self):
        output = run_page_js(self.RAIL_FIXTURE + """
(async () => {
  const away = {id: 'a', title: 'Away', state: 'idle', kind: 'claude', host: 'laptop2', cluster: 'Box', terminal: 't1', hosting: 'orca'};
  const unbound = {id: 'u', title: 'Unbound', state: 'idle', kind: 'claude', host: 'local', cluster: 'Box'};
  const result = {
    none: await reasonOf(unbound, async () => { throw new Error('should not be called'); }),
    down: await reasonOf(away, async () => { const e = new Error('ssh: connect timed out'); e.reason = 'host_unreachable'; throw e; }),
    empty: await reasonOf(away, async () => ({ok: true, output: ''})),
    shown: await reasonOf(away, async () => ({ok: true, output: 'hello screen'}))};
  result.screen = $('screen').textContent;
  console.log(JSON.stringify(result));
})();
""")
        self.assertEqual(output['none']['text'], 'No terminal is bound to this session')
        self.assertEqual(output['down']['text'], 'laptop2 is unreachable')
        self.assertEqual(output['empty']['text'], 'The terminal returned nothing')
        for name in ('none', 'down', 'empty'):
            self.assertTrue(output[name]['screenHidden'], name)
        self.assertEqual(output['shown']['text'], '')
        self.assertFalse(output['shown']['screenHidden'])
        self.assertEqual(output['screen'], 'hello screen')

    def test_selecting_cluster_hides_previous_node_rail(self):
        output = run_page_js(self.RAIL_FIXTURE + """
selectNode('w');
const shown = {rest: $('node-rest').hidden, details: $('details').hidden};
const clusterIds = [...clusters.keys()];
selectCluster(clusterIds.length ? clusterIds[0] : 'Box');
console.log(JSON.stringify({shown, selectedId, rest: $('node-rest').hidden,
  promote: $('promote-form').hidden, assign: $('assign-form').hidden,
  details: $('details').hidden, card: $('context-rail').hidden}));
""")
        self.assertEqual(output['shown'], {'rest': False, 'details': False})
        self.assertIsNone(output['selectedId'])
        self.assertTrue(output['rest'])
        self.assertTrue(output['details'])
        self.assertFalse(output['card'])

    def test_peek_reason_lines_follow_the_response(self):
        output = run_page_js(self.RAIL_FIXTURE + """
(async () => {
  const away = {id: 'a', title: 'Away', state: 'idle', kind: 'claude', host: 'laptop2', cluster: 'Box', terminal: 't1', hosting: 'orca'};
  const fail = (reason, message) => async () => { const e = new Error(message); e.reason = reason; throw e; };
  const result = {
    none: await reasonOf(away, fail('no_terminal', 'pane gone')),
    down: await reasonOf(away, fail('host_unreachable', 'ssh timed out')),
    empty: await reasonOf(away, async () => ({ok: true, output: '', reason: 'empty'})),
    error: await reasonOf(away, fail('error', 'tmux exploded'))};
  result.errorText = $('overlay-error').textContent; result.errorShown = !$('overlay-error').hidden;
  console.log(JSON.stringify(result));
})();
""")
        self.assertEqual(output['none']['text'], 'No terminal is bound to this session')
        self.assertEqual(output['down']['text'], 'laptop2 is unreachable')
        self.assertEqual(output['empty']['text'], 'The terminal returned nothing')
        self.assertEqual(output['errorText'], 'tmux exploded')
        self.assertTrue(output['errorShown'])

    def test_escape_in_dialog_leaves_search_alone(self):
        output = run_page_js(self.SEARCH_FIXTURE + """
type('6897');
$('overlay').open = true;
document.dispatch('keydown', {key: 'Escape'});
console.log(JSON.stringify({query: searchQuery, value: $('search').value}));
""")
        self.assertEqual(output['query'], '6897')
        self.assertEqual(output['value'], '6897')

    def test_search_combines_with_state_filter(self):
        output = run_page_js(self.SEARCH_FIXTURE + """
type('o');
const query = opacities();
setStateFilter('working');
const both = opacities();
console.log(JSON.stringify({query, both, status: statusText()}));
""")
        self.assertEqual(output['query'], {'n1': 0.25, 'n2': 1, 'n3': 1})
        self.assertEqual(output['both'], {'n1': 0.25, 'n2': 0.25, 'n3': 1})
        self.assertTrue(output['status'].endswith('· 2 match'), output['status'])


if __name__ == "__main__":
    unittest.main()
