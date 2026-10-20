from __future__ import annotations

"""Turn validated run projections into seven-column evidence matrices."""
from .edges import Resolver
from .projection import Projection, STAGES

REVIEW_GATES = ('test-quality', 'code-standards', 'commenting', 'general-code')
SIZE_UNITS = {'S': 1, 'M': 2, 'L': 3}


def derive_stage(projection: Projection) -> str:
    """Place a run without slices using its gate evidence and acceptance."""
    if projection.acceptance['state'] in ('accepted', 'merged'):
        return 'accepted'
    gates = {gate['id']: gate for gate in projection.gates}
    if gates.get('delivery', {}).get('verdict') == 'pass':
        return 'delivery'
    if any(gate_id in gates for gate_id in REVIEW_GATES):
        return 'review'
    for stage in ('goal', 'design', 'plan'):
        if gates.get(stage, {}).get('verdict') != 'pass':
            return stage
    return 'implementing'


def _gate_cell(gates, gate_id):
    gate = gates.get(gate_id, {})
    return {'verdict': gate.get('verdict', 'pending'), 'at': gate.get('at'),
            'ref': gate.get('ref'), 'stale': None}


def build_matrix(p: Projection, resolver: Resolver) -> dict:
    """Build ordered slice rows; only independently verified units earn credit.

    Slice package lists define membership and ordering. Without slices, all
    packages belong to the run row. Staleness and stalls are later overlays.
    """
    packages = {package['id']: package for package in p.packages}
    slices = p.slices or [{'id': p.run, 'name': p.title, 'stage': derive_stage(p),
                          'gates': [], 'packages': list(packages)}]
    run_gates = {gate['id']: gate for gate in p.gates}
    rows = []
    notes = []
    for slice_record in slices:
        gates = dict(run_gates)
        gates.update((gate['id'], gate) for gate in slice_record['gates'])
        segments = []
        live = []
        verified_units = total_units = 0
        for package_id in slice_record['packages']:
            package = packages.get(package_id)
            if package is None:
                notes.append(f"slice {slice_record['id']}: unknown package {package_id}; skipped")
                continue
            units = SIZE_UNITS.get(package['size'], 1)
            if package['size'] not in SIZE_UNITS:
                notes.append(f"package {package_id}: unknown size {package['size']}; using weight 1")
            node = None
            if package['dispatchId']:
                node = resolver.node_for_handle('dispatch:' + package['dispatchId'],
                                                package['machine'] or 'local')
            segments.append({'id': package_id, 'size': units,
                             'state': package['state'], 'node': node})
            total_units += units
            if package['state'] == 'verified':
                verified_units += units
            if node is not None and node not in live:
                live.append(node)
        cells = {stage: _gate_cell(gates, stage) for stage in ('goal', 'design', 'plan')}
        cells['implementing'] = {'segments': segments, 'verified_units': verified_units,
                                 'total_units': total_units}
        cells['review'] = {'chips': [dict(id=gate_id, **_gate_cell(gates, gate_id))
                                     for gate_id in REVIEW_GATES]}
        cells['delivery'] = _gate_cell(gates, 'delivery')
        cells['accepted'] = dict(p.acceptance)
        stage = slice_record['stage']
        rows.append({'id': slice_record['id'], 'name': slice_record['name'],
                     'stage': stage,
                     'stepper': [int(i <= STAGES.index(stage)) for i in range(len(STAGES))],
                     'cells': cells, 'live': live})
    return {'run': p.run, 'title': p.title, 'now': p.now,
            'chief_node': resolver.node_for_handle(p.chiefTerminal, 'local'),
            'waiting': sum(decision['class'] in ('B', 'C', 'D') for decision in p.decisions),
            'stalled': 0, 'proofs': [dict(proof) for proof in p.proofs],
            'merge_gate': dict(p.mergeGate), 'rows': rows, 'notes': notes}
