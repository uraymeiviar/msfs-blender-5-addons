"""Reference values of Refresh's scene rule from the Python code the C++ DLL replaced (bake-post-native journal,
Session 5; apply-native-copy decision 6).

The scene rule's geometry (the world-box and oriented-box gaps of `near`, `oriented_gaps`, `oriented_boxes_at`,
`moves_against`) moved into fss_ao_copy.dll (interface version 6) and its Python code was removed. Before that, the
Python code's results were recorded in tests/data/ao_scene_rule_reference.json:

- section 'suite': after every Refresh and every Detected-tree Refresh (detect_occluders) of tests/test_ao_bake.py,
  keyed by the test and the call's number in it, a digest (ao_native_reference.digest) of what Refresh stores or
  compares (each item's mesh_hash, surround_hash, grades, occluders, against, posed, poses, its copies', and the
  scene_rule lists) and the scene_gap values themselves (decision 70; compared within GAP_TOL m);
- section 'synthetic': seeded cases of the geometry alone (their inputs and the Python outputs), which
  tests/test_ao_copy_native.py runs through the DLL.

    rule = RuleReference('suite')
    rule.check('test_tree/03', digest_value, gaps)  # the digest equal, every gap within GAP_TOL
    rule.done(complete=True)

FSS_AO_RULE_RECORD=1 recorded the values while the Python code was still there; a recording run needs that code, so
it cannot be repeated: with FSS_AO_RULE_RECORD=1 RuleReference now refuses (it would record the C++ values over the
Python code's), and a key that is not in the file fails.
"""

import json
import os

from ao_native_reference import digest  # noqa: F401  (the same digest of values)

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'ao_scene_rule_reference.json')
RECORD_ENV = 'FSS_AO_RULE_RECORD'
DUMP_ENV = 'FSS_AO_RULE_DUMP'  # a path: every checked call's values written there as JSON (a diff after a failure)
GAP_TOL = 1e-9  # m: the gaps are not stored by Refresh; they may differ from the Python code's by rounding only


def load(section):
    if not os.path.isfile(PATH):
        return {}
    with open(PATH, encoding='utf-8') as f:
        return json.load(f).get(section, {})


def gap_diff(want, got):
    """(names differing, largest difference) of two {object: {occluder: gap}} dicts."""
    bad, worst = [], 0.0
    if set(want) != set(got):
        return sorted(set(want) ^ set(got))[:8], float('inf')
    for o, w in want.items():
        g = got[o]
        if list(w) != list(g):
            bad.append(o)
            continue
        for n, v in w.items():
            d = abs(float(v) - float(g[n]))
            if d != d:
                d = 0.0 if (v != v and g[n] != g[n]) else float('inf')
            worst = max(worst, d)
    return bad, worst


class RuleReference:
    """The recorded values of one section ('suite')."""

    def __init__(self, section):
        self.section = section
        if os.environ.get(RECORD_ENV) == '1':
            raise RuntimeError(f'{RECORD_ENV}=1: the scene rule reference values were recorded from the Python '
                               f'code decision 6 removed; they cannot be recorded again')
        self.want = load(section)
        self.got = {}
        self.full = {}
        self.worst = 0.0  # the largest gap difference of the run

    def check(self, key, d, gaps, full=None):
        assert key not in self.got, f'{self.section}/{key}: checked twice'
        self.got[key] = d
        if full is not None and os.environ.get(DUMP_ENV):  # the values themselves, for a diff (tests/_work)
            self.full[key] = dict(values=full, gaps=gaps)
        assert key in self.want, f'{self.section}/{key}: no reference value recorded'
        w = self.want[key]
        assert w['digest'] == d, f'{self.section}/{key}: {d}, the Python code gave {w["digest"]}'
        bad, worst = gap_diff(w['gaps'], gaps)
        assert not bad and worst <= GAP_TOL, f'{self.section}/{key}: gaps differ ({bad}, largest {worst})'
        self.worst = max(self.worst, worst)
        return d

    def done(self, complete=False):
        """complete: every recorded key was checked. Returns the number of keys checked."""
        if os.environ.get(DUMP_ENV):
            with open(os.environ[DUMP_ENV], 'w', encoding='utf-8') as f:
                json.dump(self.full, f, indent=0, sort_keys=True)
        if complete:
            missing = sorted(set(self.want) - set(self.got))
            assert not missing, f'{self.section}: {len(missing)} recorded keys not checked: {missing[:8]}'
        return len(self.got)


def state_values(st, names=None):
    """What Refresh stores or compares, from ao_bake_store._state: (exact values, gaps). names: only these objects'
    scene_rule and scene_gap (detect_occluders)."""
    items = {}
    for stem in sorted(st.get('items') or {}) if names is None else ():
        it = st['items'][stem]
        copies = [[c['object'], c['occluder_mode'], list(c['occluders']), list(c['against']), list(c['posed']),
                   c['poses'], bool(c['mover'])] for c in (it.get('copies') or [])]
        items[stem] = [it['mesh_hash'], it['surround_hash'], it['grade'], it.get('cm_grade'), it.get('dn_grade'),
                       it['occluder_mode'], list(it['occluders']), list(it['against']), list(it['posed']), it['poses'],
                       bool(it['mover']), it['pose_note'], copies]
    rule = st.get('scene_rule') or {}
    gap = st.get('scene_gap') or {}
    keys = sorted(rule) if names is None else sorted(names)
    exact = dict(items=items, rule={k: list(rule.get(k, [])) for k in keys},
                 gap_names={k: list((gap.get(k) or {}).keys()) for k in keys})
    if names is None:
        exact.update(excluded=dict(sorted((st.get('excluded') or {}).items())),
                     by_object=dict(sorted((st.get('by_object') or {}).items())),
                     motion_frames=st.get('motion_frames'), moving=st.get('moving'))
    gaps = {k: {n: float(v) for n, v in (gap.get(k) or {}).items()} for k in keys}
    return exact, gaps
