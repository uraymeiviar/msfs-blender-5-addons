"""Leading '@' markers: stripped from exported names, allowed by Scan Names, clashes reported (UV journal decision 87).

To run:
"<blender>" -b --factory-startup --python tests/test_markers.py
"""

import sys
from pathlib import Path

# If an addons_core copy was loaded during Blender startup, unregister and purge it
if 'fss_blender_tools' in sys.modules:
    try:
        sys.modules['fss_blender_tools'].unregister()
    except Exception:
        pass
    for mod in list(sys.modules.keys()):
        if mod == 'fss_blender_tools' or mod.startswith('fss_blender_tools.'):
            del sys.modules[mod]

REPO_ROOT = str(Path(__file__).resolve().parents[1])
while REPO_ROOT in sys.path:
    sys.path.remove(REPO_ROOT)
sys.path.insert(0, REPO_ROOT)

from fss_blender_tools import merge, name_check  # noqa: E402


class _Node:
    def __init__(self, name):
        self.name = name


def test_strip_markers():
    cases = {
        '@MERGE_PANEL': 'PANEL',
        '@NOMERGE_BRACKET': 'BRACKET',
        '@ZONE_FWD': 'ZONE_FWD',
        '@ABCD': 'ABCD',
        '@@ABCD': 'ABCD',
        'A@B': 'A@B',
        'PANEL': 'PANEL',
        '@': '@',
        '@MERGE_': 'MERGE_',
    }
    for name, expected in cases.items():
        assert merge.strip_markers(name) == expected, (name, merge.strip_markers(name), expected)
    print("PASS: test_strip_markers")


def test_export_hooks():
    hooks = merge.glTF2ExportUserExtension()
    for name, expected in (('@ZONE_FWD', 'ZONE_FWD'), ('@ABCD', 'ABCD'), ('@MERGE_PANEL', 'PANEL')):
        node, mesh = _Node(name), _Node(name)
        hooks.gather_node_hook(node, None, {})
        hooks.gather_mesh_hook(mesh, None, None, None, None, None, {})
        assert node.name == expected and mesh.name == expected, (name, node.name, mesh.name)
    print("PASS: test_export_hooks")


def test_scan_names():
    names = ['@ZONE_FWD', '@ABCD', '@MERGE_PANEL', 'A@B', '@zone_low', 'XY', '@XY']
    findings = name_check.check_names(names, set(names))
    for clean in ('@ZONE_FWD', '@ABCD', '@MERGE_PANEL'):
        assert clean not in findings, (clean, findings.get(clean))
    assert 'CHARS' in findings['A@B'][0], findings.get('A@B')
    rules, proposal = findings['@zone_low']
    assert rules == {'CASE'} and proposal == '@ZONE_LOW', findings['@zone_low']
    for clash in ('XY', '@XY'):
        assert 'CLASH' in findings[clash][0], (clash, findings.get(clash))
    print("PASS: test_scan_names")


def main():
    test_strip_markers()
    test_export_hooks()
    test_scan_names()
    print("ALL TESTS PASSED")


main()
