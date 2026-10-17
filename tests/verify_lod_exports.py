"""Verify synthetic glTF membership, transforms, animations, geometry and reports."""

import json
from pathlib import Path
import re
import sys

import numpy as np

from harness.compare import Gltf, canonical, diff


def worlds(document):
    nodes = document.get('nodes', [])
    result = {}

    def visit(index, parent):
        node = nodes[index]
        if 'matrix' in node:
            local = np.array(node['matrix']).reshape(4, 4).T
        else:
            x, y, z, w = node.get('rotation', [0, 0, 0, 1])
            local = np.eye(4)
            local[:3, :3] = np.array([
                [1-2*y*y-2*z*z, 2*x*y-2*z*w, 2*x*z+2*y*w],
                [2*x*y+2*z*w, 1-2*x*x-2*z*z, 2*y*z-2*x*w],
                [2*x*z-2*y*w, 2*y*z+2*x*w, 1-2*x*x-2*y*y]]) @ np.diag(node.get('scale', [1, 1, 1]))
            local[:3, 3] = node.get('translation', [0, 0, 0])
        world = parent @ local
        result[node.get('name', str(index))] = world
        for child in node.get('children', []):
            visit(child, world)

    for index in document.get('scenes', [{}])[document.get('scene', 0)].get('nodes', []):
        visit(index, np.eye(4))
    return result


def verify(root):
    expected = json.loads((root / 'expected.json').read_text())
    for target in ('fs24', 'fs20'):
        baseline = Gltf(str(root / target / 'Baseline.gltf'))
        base_world = worlds(baseline.j)
        base_anim = canonical(baseline)['animations']
        log = (root.parent / f'lod-{target}.log').read_text(encoding='utf-8', errors='replace')
        for level in range(7):
            path = root / target / f'Synthetic_LOD{level:02}.gltf'
            gltf = Gltf(str(path))
            names = set(gltf.node_names)
            present = set(expected['present'][level])
            present -= {'PanelBody', 'PanelScrew', '@MERGE_Panel'}
            present.add('Panel')
            if '@NOMERGE_Button' in present:
                present.remove('@NOMERGE_Button')
                present.add('Button')
            assert names == present, (target, level, names ^ present)
            for name, matrix in worlds(gltf.j).items():
                if name in base_world:
                    assert np.allclose(matrix, base_world[name], atol=1e-5), (target, level, name)
            animations = canonical(gltf)['animations']
            if level < 4:
                assert animations and not diff(base_anim, animations), (target, level, 'animation changed')
            else:
                assert not animations, (target, level, 'culled animation survived')
            node = next(n for n in gltf.j['nodes'] if n['name'] == 'Panel')
            primitives = gltf.j['meshes'][node['mesh']]['primitives']
            vertices = sum(gltf.j['accessors'][p['attributes']['POSITION']]['count'] for p in primitives)
            triangles = sum(gltf.j['accessors'][p['indices']]['count'] // 3 for p in primitives)
            assert (vertices, triangles) == ((48, 24) if level == 0 else (24, 12))
            accessors = {p['attributes']['POSITION'] for mesh in gltf.j.get('meshes', []) for p in mesh['primitives']}
            exact = sum(gltf.j['accessors'][i]['count'] for i in accessors)
            matches = re.findall(rf'_LOD{level:02}: .*?; ([\d,]+) vertices', log)
            assert matches and all(int(m.replace(',', '')) == exact for m in matches)
            print(f'{target} LOD{level:02}: PASS {len(names)} nodes, {exact} vertices, Panel {triangles} triangles')


if __name__ == '__main__':
    verify(Path(sys.argv[1]))
