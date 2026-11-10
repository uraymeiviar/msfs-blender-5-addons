"""Unit and integration tests for FSS Visibility Scoring with probe lights (UV journal decisions 124 to 130).

To run:
G:\\e-jets-e2\\tools\\blender\\blender.exe -b --factory-startup --python tests/uv_prototype/test_visibility.py
"""

import math
import sys
import time
from pathlib import Path
from types import SimpleNamespace
import bpy
import bmesh
from mathutils import Matrix, Vector
import numpy as np

# If an addons_core copy was loaded during Blender startup, unregister and purge it
if 'fss_blender_tools' in sys.modules:
    try:
        sys.modules['fss_blender_tools'].unregister()
    except Exception:
        pass
    for mod in list(sys.modules.keys()):
        if mod == 'fss_blender_tools' or mod.startswith('fss_blender_tools.'):
            del sys.modules[mod]

REPO_ROOT = Path(__file__).resolve().parents[2]
repo_root_str = str(REPO_ROOT)
while repo_root_str in sys.path:
    sys.path.remove(repo_root_str)
sys.path.insert(0, repo_root_str)

import fss_blender_tools  # noqa: E402
from fss_blender_tools import visibility_core, visibility, uv_heatmap  # noqa: E402

fss_blender_tools.register()

SCRATCH_DIR = REPO_ROOT / 'tests' / '_work' / 'visibility_scratch'
SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
POWER = 100.0  # the synthetic scene's probe light: reach 10 m at the default Light Threshold


def srgb_decode(value):
    """Inverse of visibility_core.srgb_encode: the linear light behind a displayed value."""
    v = np.asarray(value, dtype=np.float64)
    return np.where(v <= 12.92 * 0.0031308, v / 12.92, np.power((v + 0.055) / 1.055, 2.4))


def expected_linear(power, light_pos, centre, normal, reach=None, factor=None):
    """What EEVEE gives a white diffuse face centre from a point light, without shadows."""
    to_face = Vector(centre) - Vector(light_pos)
    d = to_face.length
    cos = max(-Vector(normal).normalized().dot(to_face.normalized()), 0.0)
    if reach is None:
        reach = math.sqrt(power / (100.0 * bpy.context.scene.eevee.light_threshold))
    window = max(0.0, 1.0 - (d * d / (reach * reach)) ** 2) ** 2
    return (factor or visibility_core.POINT_FACTOR) * power / (d * d) * cos * window


def add_light(name, kind='POINT', power=POWER, location=(0, 0, 0), radius=0.0, rotation=(0, 0, 0)):
    data = bpy.data.lights.new(name, kind)
    data.energy = power
    if kind != 'SUN':
        data.shadow_soft_size = radius
    obj = bpy.data.objects.new(name, data)
    obj.location = location
    obj.rotation_euler = rotation
    bpy.context.scene.collection.objects.link(obj)
    return obj


def include_lights(scene, names):
    visibility.sync_light_list(scene)
    for item in scene.fss_visibility.lights:
        item.include = item.light.name in names


def build_synthetic_scene(blend_path):
    """The synthetic cases, lit by one point light PROBE at the origin (radius 0: hard shadows)."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    add_light("PROBE")
    sun = add_light("SUN_LIGHT", kind='SUN', power=3.0, location=(0, 0, 5))
    sun.hide_render = False

    def create_quad_facing(name, size, loc, normal_dir='+Y', mat_name=None):
        me = bpy.data.meshes.new(name + "_Mesh")
        bm = bmesh.new()
        hw, hh = size[0] / 2.0, size[1] / 2.0
        if normal_dir == '+Y':
            v = [bm.verts.new(c) for c in ((-hw, 0, -hh), (hw, 0, -hh), (hw, 0, hh), (-hw, 0, hh))]
            bm.faces.new((v[3], v[2], v[1], v[0]))
        elif normal_dir == '-Y':
            v = [bm.verts.new(c) for c in ((-hw, 0, -hh), (hw, 0, -hh), (hw, 0, hh), (-hw, 0, hh))]
            bm.faces.new((v[0], v[1], v[2], v[3]))
        elif normal_dir == '-X':
            v = [bm.verts.new(c) for c in ((0, -hw, -hh), (0, hw, -hh), (0, hw, hh), (0, -hw, hh))]
            bm.faces.new((v[3], v[2], v[1], v[0]))
        bm.to_mesh(me)
        bm.free()
        obj = bpy.data.objects.new(name, me)
        obj.location = Vector(loc)
        bpy.context.scene.collection.objects.link(obj)
        if mat_name:
            obj.data.materials.append(bpy.data.materials.new(mat_name))
        return obj

    # 1. Distance: 0.5 m and 2 m
    create_quad_facing("CASE1_PANEL_NEAR", (0.025, 0.025), (0.0, -0.5, -0.10), '+Y')
    create_quad_facing("CASE1_PANEL_FAR", (0.10, 0.10), (0.0, -2.0, 0.40), '+Y')
    # 2. Half-covered panel
    create_quad_facing("CASE2_HALF_PANEL", (0.2, 0.2), (0.4, -2.0, 0.0), '+Y')
    create_quad_facing("CASE2_COVER_PLATE", (0.1, 0.2), (0.35, -1.999, 0.0), '+Y')
    # 3. Straight ahead and 90 deg to the side, both facing the light at 2 m: a point light lights both alike
    create_quad_facing("CASE3_PANEL_AHEAD", (0.2, 0.2), (0.0, -2.0, 0.0), '+Y')
    create_quad_facing("CASE3_PANEL_SIDE", (0.2, 0.2), (2.0, 0.0, 0.0), '-X')
    # 4. Back face: never lit
    create_quad_facing("CASE4_BACK_FACE", (0.2, 0.2), (0.0, -2.0, -0.8), '-Y')
    # 5. Invisible box hides nothing
    create_quad_facing("CASE5_TARGET_PANEL", (0.2, 0.2), (-0.8, -2.0, 0.0), '+Y')
    me_invis = bpy.data.meshes.new("CASE5_INVIS_BOX_Mesh")
    bm_invis = bmesh.new()
    bmesh.ops.create_cube(bm_invis, size=0.3)
    bm_invis.to_mesh(me_invis)
    bm_invis.free()
    invis_obj = bpy.data.objects.new("CASE5_COLLISION_BOX", me_invis)
    invis_obj.location = Vector((-0.8, -1.5, 0.0))
    invis_obj.data.materials.append(bpy.data.materials.new("COLLIDER_MATERIAL"))
    bpy.context.scene.collection.objects.link(invis_obj)
    # 6. Decal does not shadow its panel
    create_quad_facing("CASE6_OPAQUE_PANEL", (0.2, 0.2), (-0.4, -2.0, 1.0), '+Y', mat_name="PANEL_OPAQUE_MAT")
    create_quad_facing("CASE6_DECAL_QUAD", (0.15, 0.15), (-0.4, -1.98, 1.0), '+Y', mat_name="LABEL_DECAL")
    # 7. Animated lever on frames 100 to 200, hiding the sensor panel at its top
    lever = create_quad_facing("CASE7_ANIM_LEVER", (0.2, 0.2), (0.8, -2.0, 0.0), '+Y')
    lever.animation_data_create()
    lever.location.z = 0.0
    lever.keyframe_insert(data_path="location", index=2, frame=100)
    lever.location.z = 0.8
    lever.keyframe_insert(data_path="location", index=2, frame=200)
    act7 = lever.animation_data.action
    lever.animation_data.action = None
    track = lever.animation_data.nla_tracks.new()
    track.strips.new(act7.name, 100, act7)
    create_quad_facing("CASE7_SENSOR_PANEL", (0.15, 0.15), (0.8, -2.05, 0.8), '+Y')
    # 9. Mirror object with one copy hidden behind a wall
    mirr_obj = create_quad_facing("CASE9_MIRROR_OBJ", (0.2, 0.2), (0.0, 0.0, 0.0), '+Y')
    for v in mirr_obj.data.vertices:
        v.co += Vector((0.5, -2.0, 0.4))
    mirr_obj.data.update()
    mirr_obj.modifiers.new("MirrX", "MIRROR").use_axis[0] = True
    create_quad_facing("CASE9_WALL_BLOCK", (0.4, 0.4), (-0.5, -1.5, 0.4), '+Y')
    # 10. Triangulate modifier, half covered
    tri_obj = create_quad_facing("CASE10_TRI_PANEL", (0.2, 0.2), (-0.4, -2.0, 0.0), '+Y')
    tri_obj.modifiers.new("Tri", "TRIANGULATE")
    create_quad_facing("CASE10_COVER_PLATE", (0.1, 0.2), (-0.45, -1.999, 0.0), '+Y')
    # 11. Two linked duplicates, one hidden
    shared_me = bpy.data.meshes.new("CASE11_SHARED_Mesh")
    bm_sh = bmesh.new()
    v = [bm_sh.verts.new(c) for c in ((-0.1, 0, -0.1), (0.1, 0, -0.1), (0.1, 0, 0.1), (-0.1, 0, 0.1))]
    bm_sh.faces.new((v[3], v[2], v[1], v[0]))
    bm_sh.to_mesh(shared_me)
    bm_sh.free()
    for name, x in (("CASE11_OBJ_VISIBLE", -0.6), ("CASE11_OBJ_HIDDEN", 0.6)):
        obj = bpy.data.objects.new(name, shared_me)
        obj.location = Vector((x, -2.0, -0.8))
        bpy.context.scene.collection.objects.link(obj)
    create_quad_facing("CASE11_BLOCKER", (0.4, 0.4), (0.6, -1.5, -0.8), '+Y')
    # 12. One UV island of two quads, one lit and one in shadow
    me12 = bpy.data.meshes.new("CASE12_PARTLY_HIDDEN_Mesh")
    bm12 = bmesh.new()
    v0, v1, v2, v3 = (bm12.verts.new(c) for c in ((1.1, -2.0, 0.0), (1.3, -2.0, 0.0), (1.3, -2.0, 0.2), (1.1, -2.0, 0.2)))
    f0 = bm12.faces.new((v3, v2, v1, v0))
    v4, v5 = bm12.verts.new((1.3, -2.0, -0.2)), bm12.verts.new((1.1, -2.0, -0.2))
    f1 = bm12.faces.new((v0, v1, v4, v5))
    uv = bm12.loops.layers.uv.new("UVMap")
    for loop, xy in zip(f0.loops, ((0.0, 1.0), (1.0, 1.0), (1.0, 0.5), (0.0, 0.5))):
        loop[uv].uv = xy
    for loop, xy in zip(f1.loops, ((0.0, 0.5), (1.0, 0.5), (1.0, 0.0), (0.0, 0.0))):
        loop[uv].uv = xy
    bm12.to_mesh(me12)
    bm12.free()
    bpy.context.scene.collection.objects.link(bpy.data.objects.new("CASE12_PARTLY_HIDDEN_OBJ", me12))
    me_b = bpy.data.meshes.new("CASE12_BLOCKER_Mesh")
    bm_b = bmesh.new()
    vb = [bm_b.verts.new(c) for c in ((0.70, -1.5, -0.20), (1.10, -1.5, -0.20), (1.10, -1.5, 0.00), (0.70, -1.5, 0.00))]
    bm_b.faces.new((vb[3], vb[2], vb[1], vb[0]))
    bm_b.to_mesh(me_b)
    bm_b.free()
    bpy.context.scene.collection.objects.link(bpy.data.objects.new("CASE12_BLOCKER", me_b))
    # 13. A 2 mm part at 1 m with a parent panel; 14. the same part with no parent
    p13 = create_quad_facing("CASE13_PARENT_PANEL", (0.2, 0.2), (0.0, -1.0, 0.6), '+Y')
    c13 = create_quad_facing("CASE13_CHILD_PART", (0.002, 0.002), (0.0, -1.0, 0.5), '+Y')
    c13.parent = p13
    create_quad_facing("CASE14_STANDALONE_PART", (0.002, 0.002), (0.3, -1.0, 0.5), '+Y')

    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    return blend_path


def _quad(me_verts, me_faces, centre, angle_deg, half=0.3, eye=(0, 0, 0)):
    """A square at centre whose normal is the direction to eye turned by angle_deg about Z."""
    c = Vector(centre)
    to_eye = (Vector(eye) - c).normalized()
    normal = Matrix.Rotation(math.radians(angle_deg), 3, 'Z') @ to_eye
    v = Vector((0, 0, 1))
    u = v.cross(normal)
    start = len(me_verts)
    me_verts += [tuple(c + half * (a * u + b * v)) for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    me_faces.append(tuple(range(start, start + 4)))


def _facing_object(name, quads, material=None, eye=(0, 0, 0)):
    verts, faces = [], []
    for centre, angle, half in quads:
        _quad(verts, faces, centre, angle, half, eye)
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    layer = me.uv_layers.new(name='UVMap')
    layer.data.foreach_set('uv', [c for i, _f in enumerate(faces) for xy in ((i, 0), (i + .1, 0), (i + .1, .1), (i, .1))
                                  for c in xy])
    if material is not None:
        me.materials.append(material)
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _raw(results, mesh_name, face=0):
    return float(results['mesh_arrays'][mesh_name]['face_raw'][face])


def _share(results, mesh_name, power, light_pos, centre, normal, face=0):
    """The share of the face the light reaches: the measured light over the light without shadows."""
    return float(srgb_decode(_raw(results, mesh_name, face))) / expected_linear(power, light_pos, centre, normal)


# ---------------------------------------------------------------------------
# The score's light against an EEVEE render
# ---------------------------------------------------------------------------

def test_light_term_matches_eevee():
    """batch_light_term gives the light a white diffuse plane shows in an EEVEE render, within 3 %: point and spot
    lights, distance, the Light Threshold's fade, Custom Distance, a spot's edge, an area light."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_EEVEE'
    scene.render.resolution_x = scene.render.resolution_y = 32
    scene.view_settings.view_transform = 'Standard'
    world = bpy.data.worlds.new('BLACK')
    world.color = (0, 0, 0)
    scene.world = world
    world.use_nodes = True
    world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0.0
    bpy.ops.mesh.primitive_plane_add(size=4.0)
    plane = bpy.context.object
    mat = bpy.data.materials.new('WHITE')
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    diffuse = nt.nodes.new('ShaderNodeBsdfDiffuse')
    diffuse.inputs['Color'].default_value = (1, 1, 1, 1)
    nt.links.new(diffuse.outputs[0], nt.nodes.new('ShaderNodeOutputMaterial').inputs[0])
    plane.data.materials.append(mat)
    cam = bpy.data.objects.new('CAM', bpy.data.cameras.new('CAM'))
    cam.data.type = 'ORTHO'
    cam.data.ortho_scale = 0.1
    cam.location = (0, 0, 5)
    scene.collection.objects.link(cam)
    scene.camera = cam
    out = SCRATCH_DIR / 'term.exr'
    tri = [np.array([[-0.001, -0.001, 0.0]]), np.array([[0.001, -0.001, 0.0]]), np.array([[0.0, 0.001, 0.0]])]

    def rendered():
        scene.render.image_settings.file_format = 'OPEN_EXR'
        scene.render.filepath = str(out)
        bpy.ops.render.render(write_still=True)
        img = bpy.data.images.load(str(out))
        img.colorspace_settings.name = 'Non-Color'
        value = float(np.array(img.pixels[:]).reshape(32, 32, 4)[14:18, 14:18, 0].mean())
        bpy.data.images.remove(img)
        return value

    cases = [('POINT', 10, (0, 0, 1), {}), ('POINT', 10, (0, 0, 2), {}), ('POINT', 5, (0.5, 0, 1.3), {}),
             ('POINT', 10, (0, 0, 2), {'custom': 2.5}), ('SPOT', 10, (math.sin(math.radians(57)), 0, math.cos(math.radians(57))), {}),
             ('SPOT', 10, (0, 0, 1), {}), ('AREA', 10, (0, 0, 1), {}), ('AREA', 10, (0, 0, 2), {})]
    lines = []
    for kind, power, location, extra in cases:
        for o in [o for o in bpy.data.objects if o.type == 'LIGHT']:
            bpy.data.objects.remove(o)
        light = add_light('L', kind, power, location)
        if kind == 'SPOT':
            light.data.spot_size = math.radians(120)
            light.data.spot_blend = 0.15
            light.rotation_euler = (0, 0, 0)  # pointing straight down: the plane centre sits 57 deg off its axis
        if kind == 'AREA':
            light.data.size = 0.05
        if 'custom' in extra:
            light.data.use_custom_distance = True
            light.data.cutoff_distance = extra['custom']
        bpy.context.view_layer.update()
        record = visibility_core.light_record(light, scene)
        weighted, area = visibility_core.batch_light_term(record, *tri, np.array([0]), 1)
        mine = float(weighted[0] / area[0])
        theirs = rendered()
        lines.append(f"{kind} {power} W at {tuple(round(c, 2) for c in location)}{' ' + str(extra) if extra else ''}: "
                     f"score {mine:.4f}, EEVEE {theirs:.4f}")
        assert abs(mine - theirs) <= 0.03 * max(theirs, 1e-3) + 2e-4, lines[-1]
    print("PASS: test_light_term_matches_eevee (" + "; ".join(lines) + ")")


# ---------------------------------------------------------------------------
# Synthetic cases through visibility_core
# ---------------------------------------------------------------------------

def test_synthetic_cases():
    blend_path = SCRATCH_DIR / "synthetic_test.blend"
    build_synthetic_scene(blend_path)
    results = visibility_core.analyze_visibility(blend_path=blend_path, ambient=0.0, lights=['PROBE'], anim_states=(0.0, 1.0),
                                                 shadow_samples=4)
    arrays = results['mesh_arrays']
    origin = (0, 0, 0)

    # A light with radius 0 has one sample per state
    assert results['lights'] == [{'name': 'PROBE', 'samples': 1}] and len(results['views']) == 2, results['lights']

    # 1. Distance: the light falls off with 1/d2, as EEVEE shows it
    near = srgb_decode(_raw(results, "CASE1_PANEL_NEAR_Mesh"))
    far = srgb_decode(_raw(results, "CASE1_PANEL_FAR_Mesh"))
    want_near = expected_linear(POWER, origin, (0, -0.5, -0.1), (0, 1, 0))
    want_far = expected_linear(POWER, origin, (0, -2.0, 0.4), (0, 1, 0))
    assert abs(near / want_near - 1) < 0.03 and abs(far / want_far - 1) < 0.03, (near, want_near, far, want_far)

    # 3. Ahead and to the side at the same distance, both facing the light: the same
    ahead, side = _raw(results, "CASE3_PANEL_AHEAD_Mesh"), _raw(results, "CASE3_PANEL_SIDE_Mesh")
    assert abs(ahead - side) < 0.01 * ahead, (ahead, side)

    # 2. and 10. Half covered: half the light, through a Triangulate modifier too
    half = _share(results, "CASE2_HALF_PANEL_Mesh", POWER, origin, (0.4, -2.0, 0.0), (0, 1, 0))
    assert abs(half - 0.5) < 0.05, half
    tri_shares = [float(srgb_decode(arrays["CASE10_TRI_PANEL_Mesh"]['face_raw'][0]))
                  / expected_linear(POWER, origin, (-0.4, -2.0, 0.0), (0, 1, 0))]
    assert abs(tri_shares[0] - 0.5) < 0.05, tri_shares

    # 4. Back face: no light, never seen
    assert _raw(results, "CASE4_BACK_FACE_Mesh") == 0.0 and arrays["CASE4_BACK_FACE_Mesh"]['face_never_seen'][0]

    # 5. and 6. An invisible box and a decal cast no shadow
    for name, centre in (("CASE5_TARGET_PANEL_Mesh", (-0.8, -2.0, 0.0)), ("CASE6_OPAQUE_PANEL_Mesh", (-0.4, -2.0, 1.0))):
        share = _share(results, name, POWER, origin, centre, (0, 1, 0))
        assert abs(share - 1.0) < 0.03, (name, share)

    # 7. The sensor panel hidden by the lever at its top step is lit at the other: the brightest step counts
    sensor = _share(results, "CASE7_SENSOR_PANEL_Mesh", POWER, origin, (0.8, -2.05, 0.8), (0, 1, 0))
    assert sensor > 0.97, sensor

    # 9. and 11. A mirror copy or a linked duplicate in shadow does not darken the lit one
    assert _raw(results, "CASE9_MIRROR_OBJ_Mesh") > 0.0
    shared = _share(results, "CASE11_SHARED_Mesh", POWER, origin, (-0.6, -2.0, -0.8), (0, 1, 0))
    assert abs(shared - 1.0) < 0.03, shared

    # 12. One island, one quad lit and one in shadow: the island follows its lit part (90 %)
    m12 = arrays["CASE12_PARTLY_HIDDEN_Mesh"]
    assert m12['face_raw'][1] == 0.0 and m12['face_raw'][0] > 0.0, m12['face_raw']
    scale = results['scale']
    assert abs(m12['island_scores'][0] - m12['face_raw'][0] / scale) < 1e-6, (m12['island_scores'], scale)

    # 13. and 14. Too small to measure: the child takes its parent's lit share, the lone part counts as fully lit
    child, alone = arrays["CASE13_CHILD_PART_Mesh"], arrays["CASE14_STANDALONE_PART_Mesh"]
    assert child['face_undetermined'][0] and alone['face_undetermined'][0]
    rc = results['resolved_counts']
    assert rc['PARENT_SUBTREE']['faces'] >= 1 and rc['FALLBACK_1.0']['faces'] >= 1, rc
    for name in ("CASE13_CHILD_PART", "CASE14_STANDALONE_PART"):
        centre = bpy.data.objects[name].matrix_world.translation  # parenting moved the child: its world place counts
        share = _share(results, name + "_Mesh", POWER, origin, centre, (0, 1, 0))
        assert abs(share - 1.0) < 0.05, (name, share)

    # The most visible island is 1.0, and every value is the raw one over the same scale
    best = max(isl['score'] for isl in results['island_summaries'].values())
    assert abs(best - 1.0) < 1e-6, best
    assert results['scale'] > 0 and all(0.0 <= isl['score'] <= 1.0 for isl in results['island_summaries'].values())
    assert results['step_limit_result']['pairs_left'] == 0
    print(f"PASS: test_synthetic_cases (1/d2 near {near:.4f} far {far:.4f}; half covered {half:.3f}; sensor {sensor:.3f}; "
          f"scale {scale:.4f})")


def test_percentile_and_step_limit():
    """The island percentile, the step limit (raise only, decision 134) and Ambient (decision 133), on their own and in
    a run."""
    v, left = visibility_core.limit_steps([1.0, 4.0], [(0, 1)], 1.5)
    assert list(v) == [4.0 / 1.5, 4.0] and left == 0, v  # the darker rises; the brighter stays
    # A chain: each rises to its brighter neighbour / 1.5, whatever order the pairs come in
    v, left = visibility_core.limit_steps([16.0, 1.0, 4.0], [(1, 2), (0, 2)], 1.5)
    assert np.allclose(v, [16.0, 16.0 / 1.5 ** 2, 16.0 / 1.5]) and left == 0, v
    # A large dim island beside a small lit one: the lit one keeps its value (the glareshield case of Session 110)
    v, _ = visibility_core.limit_steps([0.51, 0.15], [(0, 1)], 1.5)
    assert v[0] == 0.51 and abs(v[1] - 0.34) < 1e-9, v
    v, _ = visibility_core.limit_steps([0.0, 5.0], [(0, 1)], 1.5)
    assert np.allclose(v, [5.0 / 1.5, 5.0]), v  # a never-lit island rises too
    v, _ = visibility_core.limit_steps([1.0, 4.0, 2.0], [(0, 1)], 1.0)
    assert list(v) == [4.0, 4.0, 2.0], v  # 1 makes touching islands equal; an island without neighbours stays
    assert visibility_core.island_pairs([[1], [0, 2], [1]], np.array([0, 0, 1])) == [(0, 1)]

    # A mesh of two islands meeting at an edge: one faces the light, the other nearly edge-on
    bpy.ops.wm.read_factory_settings(use_empty=True)
    add_light('PROBE')
    me = bpy.data.meshes.new('HINGE')
    # The second island turns away along the first one's edge: lit, unshadowed, almost edge-on and farther
    me.from_pydata([(-0.2, -2, -0.2), (0.2, -2, -0.2), (0.2, -2, 0.2), (-0.2, -2, 0.2), (0.6, -3.6, 0.2), (0.6, -3.6, -0.2)],
                   [], [(3, 2, 1, 0), (2, 4, 5, 1)])
    layer = me.uv_layers.new(name='UVMap')
    layer.data.foreach_set('uv', [0, 0, .4, 0, .4, .4, 0, .4, .5, .5, .9, .5, .9, .9, .5, .9])
    bpy.context.scene.collection.objects.link(bpy.data.objects.new('HINGE', me))
    blend_path = SCRATCH_DIR / 'step_limit.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))

    def run(ratio, percentile=0.9, ambient=0.0):
        res = visibility_core.analyze_visibility(blend_path=blend_path, ambient=ambient, lights=['PROBE'], anim_states=(0.0,),
                                                 step_limit=ratio, island_percentile=percentile)
        return res, res['mesh_arrays']['HINGE']['island_scores']

    free, free_scores = run(4.0)
    assert free_scores.max() / max(free_scores.min(), 1e-9) > 1.5, free_scores
    limited, scores = run(1.5)
    assert abs(scores.max() / scores.min() - 1.5) < 1e-4 and abs(scores.max() - 1.0) < 1e-6, scores
    result = limited['step_limit_result']
    assert result['lowered'] == 0 and result['raised'] == 1 and result['pairs_left'] == 0, result
    # Raise only: the brighter island keeps its value, the scale stays
    assert abs(limited['scale'] - free['scale']) < 1e-9 and abs(scores.max() - free_scores.max()) < 1e-9, (scores, free_scores)

    # Ambient: every value lifted by the same share of the way to 1; never-lit faces stay flagged
    unlimited, unlimited_scores = run(1000.0)
    lifted, lifted_scores = run(1000.0, ambient=0.25)
    assert np.allclose(lifted_scores, 0.25 + 0.75 * unlimited_scores), (lifted_scores, unlimited_scores)
    faces_free = unlimited['mesh_arrays']['HINGE']['face_scores']
    assert np.allclose(lifted['mesh_arrays']['HINGE']['face_scores'], 0.25 + 0.75 * faces_free)
    assert lifted['ambient'] == 0.25
    print(f"PASS: test_percentile_and_step_limit (free {free_scores.round(3)}, limited {scores.round(3)})")


def test_spot_and_area_lights():
    """A spot lights inside its cone only and renders only the cube sides it can reach; an area light its front."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    spot = add_light('SPOT', 'SPOT', rotation=(math.radians(-90), 0, 0))  # pointing along -Y
    spot.data.spot_size = math.radians(60)
    spot.data.spot_blend = 0.0
    _facing_object('AHEAD', [((0, -2, 0), 0, 0.1)])
    _facing_object('SIDE', [((2, 0, 0), 0, 0.1)])
    _facing_object('BEHIND', [((0, 2, 0), 0, 0.1)])
    bpy.context.view_layer.update()
    record = visibility_core.light_record(spot, bpy.context.scene)
    # 30 deg each side reaches only the front cube side (the others start 45 deg off the axis); 60 deg all but the back
    assert visibility_core.cube_faces_in_cone(record) == {'FORWARD'}, visibility_core.cube_faces_in_cone(record)
    wide = dict(record, cos_half=math.cos(math.radians(60)))
    assert visibility_core.cube_faces_in_cone(wide) == {'FORWARD', 'LEFT', 'RIGHT', 'UP', 'DOWN'}
    blend_path = SCRATCH_DIR / 'spot.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    res = visibility_core.analyze_visibility(blend_path=blend_path, ambient=0.0, lights=['SPOT'], anim_states=(0.0,))
    a = res['mesh_arrays']
    ahead = _share(res, 'AHEAD', POWER, (0, 0, 0), (0, -2, 0), (0, 1, 0))
    assert abs(ahead - 1.0) < 0.03 and a['SIDE']['face_raw'][0] == 0.0 and a['BEHIND']['face_raw'][0] == 0.0, ahead

    bpy.ops.wm.read_factory_settings(use_empty=True)
    area = add_light('AREA', 'AREA', rotation=(math.radians(-90), 0, 0))
    area.data.size = 0.0  # a point at its centre, front side only
    _facing_object('AHEAD', [((0, -2, 0), 0, 0.1)])
    _facing_object('BEHIND', [((0, 2, 0), 0, 0.1)])
    blend_path = SCRATCH_DIR / 'area.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    res = visibility_core.analyze_visibility(blend_path=blend_path, ambient=0.0, lights=['AREA'], anim_states=(0.0,))
    got = float(srgb_decode(res['mesh_arrays']['AHEAD']['face_raw'][0]))
    want = expected_linear(POWER, (0, 0, 0), (0, -2, 0), (0, 1, 0), factor=visibility_core.AREA_FACTOR)
    assert abs(got / want - 1.0) < 0.03 and res['mesh_arrays']['BEHIND']['face_raw'][0] == 0.0, (got, want)
    print(f"PASS: test_spot_and_area_lights (spot: ahead {ahead:.3f}, side and behind 0; area front {got / want:.3f})")


def test_soft_shadows():
    """A face in a small blocker's shadow: dark with radius 0, partly lit from samples spread over a larger radius."""
    def run(radius, samples=4):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        add_light('PROBE', radius=radius)
        _facing_object('TARGET', [((0, -2, 0), 0, 0.02)])
        # Half 0.19 m: of the 4 samples 0.3 m around the centre, two pass behind it at about 0.155 m, two beside it at
        # about 0.21 m
        _facing_object('BLOCKER', [((0, -0.5, 0), 0, 0.19)])
        blend_path = SCRATCH_DIR / 'soft.blend'
        bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
        return visibility_core.analyze_visibility(blend_path=blend_path, ambient=0.0, lights=['PROBE'], anim_states=(0.0,),
                                                  shadow_samples=samples)

    hard = run(0.0)
    assert hard['lights'][0]['samples'] == 1 and hard['mesh_arrays']['TARGET']['face_raw'][0] == 0.0
    soft = run(0.3)
    assert soft['lights'][0]['samples'] == 4 and len(soft['views']) == 4, soft['lights']
    share = _share(soft, 'TARGET', POWER, (0, 0, 0), (0, -2, 0), (0, 1, 0))
    assert 0.2 < share < 0.95, share
    print(f"PASS: test_soft_shadows (radius 0: in shadow; radius 0.3 m, 4 samples: {share:.2f} lit)")


def test_animated_light():
    """A keyed spot sweeping from one panel to another lights both over the animation steps, one at a single step."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    spot = add_light('SWEEP', 'SPOT', rotation=(math.radians(-90), 0, math.radians(45)))
    spot.data.spot_size = math.radians(30)
    spot.keyframe_insert(data_path='rotation_euler', index=2, frame=0)
    spot.rotation_euler.z = math.radians(-45)
    spot.keyframe_insert(data_path='rotation_euler', index=2, frame=100)
    r = 2.0 / math.sqrt(2.0)
    _facing_object('LEFT_PANEL', [((r, -r, 0), 0, 0.1)])
    _facing_object('RIGHT_PANEL', [((-r, -r, 0), 0, 0.1)])
    blend_path = SCRATCH_DIR / 'sweep.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    both = visibility_core.analyze_visibility(blend_path=blend_path, ambient=0.0, lights=['SWEEP'], anim_states=(0.0, 1.0))
    first = visibility_core.analyze_visibility(blend_path=blend_path, ambient=0.0, lights=['SWEEP'], anim_states=(0.0,))
    assert both['mesh_arrays']['LEFT_PANEL']['face_raw'][0] > 0 and both['mesh_arrays']['RIGHT_PANEL']['face_raw'][0] > 0
    assert first['mesh_arrays']['LEFT_PANEL']['face_raw'][0] > 0 and first['mesh_arrays']['RIGHT_PANEL']['face_raw'][0] == 0
    assert len(both['light_states']) == 2 and both['light_states'][0]['SWEEP']['pos'] == [0.0, 0.0, 0.0]
    print("PASS: test_animated_light (the sweep lights both panels; one step lights one)")


# ---------------------------------------------------------------------------
# Operator, panel and file
# ---------------------------------------------------------------------------

def test_operator_on_saved_scene():
    blend_path = SCRATCH_DIR / "operator_test.blend"
    build_synthetic_scene(blend_path)
    scene = bpy.context.scene
    include_lights(scene, {'PROBE'})
    settings = scene.fss_visibility
    settings.states = 3
    settings.island_percentile = 80.0
    settings.step_limit = 2.0
    settings.ambient = 0.2
    assert bpy.ops.fss.update_visibility.poll(), "Poll must be True on a saved scene with an included light"
    assert bpy.ops.fss.update_visibility() == {'FINISHED'}

    vis_file = blend_path.with_suffix('.visibility')
    meta, data, _ = visibility_core.load_visibility_file(vis_file, scene_meshes=bpy.data.meshes, use_cache=False)
    assert meta['schema_version'] == visibility_core.VISIBILITY_SCHEMA == 8
    assert meta['settings']['lights'] == ['PROBE'] and meta['settings']['states'] == 3, meta['settings']
    assert abs(meta['island_percentile'] - 0.8) < 1e-6 and meta['step_limit'] == 2.0, meta
    assert abs(meta['ambient'] - 0.2) < 1e-6 and abs(meta['settings']['ambient'] - 0.2) < 1e-6, meta['settings']
    assert [entry['name'] for entry in meta['lights']] == ['PROBE'] and len(meta['views']) == 3
    assert not any(key.endswith('__vis_omega') for key in data.files), "per-view sums are not kept"
    assert any(key.endswith('__face_island_values') for key in data.files)

    text = bpy.data.texts[visibility.REPORT_TEXT_NAME].as_string()
    for line in ("FSS VISIBILITY REPORT", "PROBE LIGHTS:", "PROBE", "Point 100 W", "Island value: the 80 %", "Step limit 2.00"):
        assert line in text, (line, text[:1200])
    assert bpy.ops.fss.visibility_select_never_seen() == {'FINISHED'}
    assert bpy.ops.fss.visibility_select_stale() == {'FINISHED'}

    # An older file, scored by cameras: not used
    meta_old = dict(meta, schema_version=6)
    assert visibility_core.is_old_visibility_file(meta_old)
    print("PASS: test_operator_on_saved_scene")


def test_scene_unchanged_after_run_and_esc():
    blend_path = SCRATCH_DIR / "restore_test.blend"
    build_synthetic_scene(blend_path)
    bpy.context.scene.frame_set(42)
    include_lights(bpy.context.scene, {'PROBE'})
    bpy.ops.fss.update_visibility()
    assert bpy.context.scene.frame_current == 42
    for me in bpy.data.meshes:
        assert visibility_core.ORIG_FACE_ATTR_NAME not in me.attributes, me.name

    analyzer = visibility_core.VisibilityAnalyzer(scene=bpy.context.scene, view_layer=bpy.context.view_layer,
                                                  lights=['PROBE'], blend_path=blend_path)
    analyzer.prepare()
    analyzer.execute_next_step()
    analyzer.cleanup()
    assert bpy.context.scene.frame_current == 42
    for me in bpy.data.meshes:
        assert visibility_core.ORIG_FACE_ATTR_NAME not in me.attributes, me.name
    print("PASS: test_scene_unchanged_after_run_and_esc")


def test_disabled_states():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    assert not bpy.ops.fss.update_visibility.poll(), "unsaved"
    blend_path = SCRATCH_DIR / "disabled_state_test.blend"
    build_synthetic_scene(blend_path)
    scene = bpy.context.scene
    include_lights(scene, set())
    assert not bpy.ops.fss.update_visibility.poll(), "no light included"
    include_lights(scene, {'SUN_LIGHT'})
    assert not bpy.ops.fss.update_visibility.poll(), "a sun only: it has no position"
    assert visibility.included_lights(scene) == []
    include_lights(scene, {'PROBE'})
    assert bpy.ops.fss.update_visibility.poll()
    print("PASS: test_disabled_states (unsaved, none, a sun only, a point light)")


def test_light_list_sync():
    """The list follows the scene's lights; Include survives a rename; a deleted light leaves; drawing only schedules."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    a = add_light('L_ALPHA')
    b = add_light('L_BETA', 'SPOT')
    visibility.sync_light_list(scene)
    settings = scene.fss_visibility
    assert [it.light for it in settings.lights] == [a, b]
    settings.lights[0].include = True
    a.name = 'L_ALPHA_RENAMED'
    visibility.sync_light_list(scene)
    item = next(it for it in settings.lights if it.light == a)
    assert item.include and item.light_name == 'L_ALPHA_RENAMED'
    bpy.data.objects.remove(b, do_unlink=True)
    visibility.sync_light_list(scene)
    assert [it.light for it in settings.lights] == [a]

    c = add_light('L_GAMMA')
    assert not visibility.light_list_in_sync(scene)
    registered = []
    original = bpy.app.timers.register
    bpy.app.timers.register = lambda fn, first_interval=0.0, persistent=False: registered.append(fn)
    try:
        visibility.schedule_light_sync(scene)
        visibility.schedule_light_sync(scene)
    finally:
        bpy.app.timers.register = original
    assert len(registered) == 1 and len(settings.lights) == 1, "scheduling must not write the list"
    registered[0]()
    assert visibility.light_list_in_sync(scene) and [it.light for it in settings.lights] == [a, c]
    assert settings.lights[0].include is True and visibility._light_sync_pending is False

    # Selecting a row's light
    assert bpy.ops.fss.visibility_select_light(light_name='L_GAMMA') == {'FINISHED'}
    assert bpy.context.view_layer.objects.active == c and c.select_get()
    assert visibility.light_summary(c) == 'Point 100 W'
    print("PASS: test_light_list_sync")


class Recorder:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return self
        return call


def test_panel_draw():
    """The panel lists the lights and the island settings, warns about an included sun, and writes nothing."""
    blend_path = SCRATCH_DIR / "panel_test.blend"
    build_synthetic_scene(blend_path)
    scene = bpy.context.scene
    include_lights(scene, {'PROBE', 'SUN_LIGHT'})
    before = [(it.light.name, it.include) for it in scene.fss_visibility.lights]
    recorder = Recorder()
    visibility.FSS_PT_Visibility.draw(SimpleNamespace(layout=recorder), bpy.context)
    props = [args[1] for name, args, _kw in recorder.calls if name == 'prop' and len(args) > 1]
    labels = [kw.get('text', args[0] if args else '') for name, args, kw in recorder.calls if name == 'label']
    lists = [args[0] for name, args, _kw in recorder.calls if name == 'template_list']
    assert lists == ['FSS_UL_VisibilityLightList'], lists
    assert {'states', 'island_percentile', 'step_limit'} <= set(props), props
    assert any('Sun lights have no position' in text for text in labels), labels
    assert [(it.light.name, it.include) for it in scene.fss_visibility.lights] == before
    print("PASS: test_panel_draw")


def test_visibility_heatmap_mode():
    blend_path = SCRATCH_DIR / "heatmap_vis_test.blend"
    build_synthetic_scene(blend_path)
    include_lights(bpy.context.scene, {'PROBE'})
    bpy.ops.fss.update_visibility()
    scene = bpy.context.scene
    scene.fss_uv_heatmap_show = True
    scene.fss_uv_heatmap_mode = 'VISIBILITY'
    bpy.ops.object.select_all(action='DESELECT')
    for name in ("CASE1_PANEL_NEAR", "CASE4_BACK_FACE", "CASE13_CHILD_PART"):
        bpy.data.objects[name].select_set(True)
    uv_heatmap.update_heatmap_cache(bpy.context, refresh=True)
    stats = uv_heatmap._global_stats
    assert stats['total_tris'] > 0 and 'chart_visibility' in stats
    col_near = uv_heatmap._cache["CASE1_PANEL_NEAR"].colors_visibility[0]
    assert col_near[:3].min() > 0.9, f"the brightest panel is not white: {col_near}"
    # both views show the saved scores on the one scale: never seen and undetermined faces have no colour of their own
    for name in ("CASE1_PANEL_NEAR", "CASE4_BACK_FACE", "CASE13_CHILD_PART"):
        cache = uv_heatmap._cache[name]
        assert cache.vis_data['has_data'], name
        for scores, colors in ((cache.vis_data['scores'], cache.colors_visibility),
                               (cache.vis_data['island_scores'], cache.colors_visibility_island)):
            # black to white: red, green and blue are each the score
            np.testing.assert_allclose(colors[::3, :3], np.column_stack((scores, scores, scores)), atol=1e-4)
    back = uv_heatmap._cache["CASE4_BACK_FACE"]
    assert back.vis_data['never_seen'].all(), "the back face is expected to be flagged never seen"
    assert back.vis_data['scores'].min() > 0.0 and np.ptp(back.colors_visibility[0][:3]) < 1e-6, "never seen is not its grey"
    assert 'chart_visibility_island' in stats
    assert len(stats['chart_visibility_island']) == len(stats['chart_visibility']) == len(stats['chart_area'])
    for scope in ('ISLAND', 'FACE'):
        cdata = uv_heatmap.chart_data('VISIBILITY', stats, scope=scope)
        assert cdata is not None and cdata['title'] == 'Visibility' and len(cdata['ticks']) == 5, scope

    # the island view shows exactly the value saved for the packer
    data = visibility_core.load_visibility_file(blend_path.with_suffix('.visibility'), use_cache=False)[1]
    near = uv_heatmap._cache["CASE1_PANEL_NEAR"].vis_data['island_scores']
    saved = data['CASE1_PANEL_NEAR_Mesh__face_island_values']
    assert set(np.round(near, 6)) <= set(np.round(saved, 6)), (near, saved)

    # a selected object that Visibility leaves out must not make every frame recompute the statistics
    near_obj = bpy.data.objects["CASE1_PANEL_NEAR"]
    near_obj.hide_render = True
    uv_heatmap.update_heatmap_cache(bpy.context, refresh=True)
    names = tuple(sorted(o.name for o in bpy.context.selected_objects if o.type == 'MESH'))
    assert "CASE1_PANEL_NEAR" in names and "CASE1_PANEL_NEAR" not in uv_heatmap._cache
    assert uv_heatmap._global_stats['selection'] == names, "statistics keep the filtered selection"
    near_obj.hide_render = False

    # changing the mode brings statistics that fit it, without Refresh
    uv_heatmap.update_heatmap_cache(bpy.context, refresh=True)
    scene.fss_uv_heatmap_mode = 'SHAPE'
    assert len(uv_heatmap._global_stats['chart_area']) == len(uv_heatmap._global_stats['chart_distortion'])  # no UVs here
    scene.fss_uv_heatmap_mode = 'VISIBILITY'
    assert uv_heatmap.chart_data('VISIBILITY', uv_heatmap._global_stats) is not None
    print("PASS: test_visibility_heatmap_mode")


def test_heatmap_modifier_face_mapping():
    blend_path = SCRATCH_DIR / "heatmap_modifier_test.blend"
    build_synthetic_scene(blend_path)
    include_lights(bpy.context.scene, {'PROBE'})
    bpy.ops.fss.update_visibility()
    data = visibility_core.load_visibility_file(blend_path.with_suffix('.visibility'), use_cache=False)[1]
    scene = bpy.context.scene
    scene.fss_uv_heatmap_show = True
    scene.fss_uv_heatmap_mode = 'VISIBILITY'
    for obj_name, mesh_name in (("CASE9_MIRROR_OBJ", "CASE9_MIRROR_OBJ_Mesh"), ("CASE10_TRI_PANEL", "CASE10_TRI_PANEL_Mesh")):
        bpy.ops.object.select_all(action='DESELECT')
        bpy.data.objects[obj_name].select_set(True)
        uv_heatmap.update_heatmap_cache(bpy.context, refresh=True)
        cache = uv_heatmap._cache[obj_name]
        assert cache.vis_data['has_data'], obj_name
        expected = visibility_core.compute_heatmap_colors(np.array([data[f'{mesh_name}__face_scores'][0]]))[0]
        assert len(cache.colors_visibility) > 0
        for tri_col in cache.colors_visibility:
            np.testing.assert_allclose(tri_col, expected, atol=1e-4)

    bpy.ops.object.select_all(action='DESELECT')
    obj_near = bpy.data.objects["CASE1_PANEL_NEAR"]
    obj_near.select_set(True)
    uv_heatmap.update_heatmap_cache(bpy.context, refresh=True)
    assert uv_heatmap._cache["CASE1_PANEL_NEAR"].vis_data['has_data']
    mod_sub = obj_near.modifiers.new("ChangeEvalCount", "SUBSURF")
    mod_sub.levels = 1
    uv_heatmap.update_heatmap_cache(bpy.context, refresh=True)
    assert not uv_heatmap._cache["CASE1_PANEL_NEAR"].vis_data['has_data']
    assert uv_heatmap._global_stats['no_data_count'] == 1
    obj_near.modifiers.remove(mod_sub)
    uv_heatmap.update_heatmap_cache(bpy.context, refresh=True)
    assert uv_heatmap._cache["CASE1_PANEL_NEAR"].vis_data['has_data'] and uv_heatmap._global_stats['no_data_count'] == 0
    print("PASS: test_heatmap_modifier_face_mapping")


def test_gltf_leak_check():
    blend_path = SCRATCH_DIR / "gltf_leak_test.blend"
    build_synthetic_scene(blend_path)
    include_lights(bpy.context.scene, {'PROBE'})
    bpy.ops.fss.update_visibility()
    out_gltf = SCRATCH_DIR / "test_leak.gltf"
    bpy.ops.export_scene.gltf(filepath=str(out_gltf), export_format='GLTF_SEPARATE', export_animations=False,
                              export_skins=False, export_morph=False)
    gltf_str = out_gltf.read_text(encoding='utf-8')
    assert visibility_core.ORIG_FACE_ATTR_NAME not in gltf_str and "fss_orig" not in gltf_str.lower()
    print("PASS: test_gltf_leak_check")


def test_packer_interface_and_cache():
    blend_path = SCRATCH_DIR / "packer_test.blend"
    build_synthetic_scene(blend_path)
    include_lights(bpy.context.scene, {'PROBE'})
    bpy.ops.fss.update_visibility()
    obj12 = bpy.data.objects["CASE12_PARTLY_HIDDEN_OBJ"]
    res12 = visibility_core.get_object_visibility(obj12)
    assert not res12['stale'] and res12['object_name'] == "CASE12_PARTLY_HIDDEN_OBJ"
    isl_val = res12['island_values'][0]
    lit_face = float(res12['face_scores'][0])
    # the hidden face scores the Ambient (0.1 by default, decision 133) and stays flagged as never lit
    assert abs(res12['face_scores'][1] - 0.1) < 1e-6 and res12['face_never_seen'][1] and not res12['face_never_seen'][0]
    assert abs(isl_val - lit_face) < 1e-6 and abs(res12['ambient'] - 0.1) < 1e-6, (isl_val, res12['ambient'])
    areas12 = res12['orig_areas']
    share = visibility_core.seen_share_face_set(res12, np.arange(len(areas12)))
    assert abs(share - areas12[0] / areas12.sum()) < 1e-6, share
    assert np.all(res12['face_facing'] == 1.0)

    visibility_core.clear_file_cache()
    c_start = visibility_core.get_file_load_count()
    cached = [visibility_core.get_object_visibility(obj12) for _ in range(200)]
    assert visibility_core.get_file_load_count() - c_start == 1
    uncached = visibility_core.get_object_visibility(obj12, use_cache=False)
    assert cached[0]['island_values'] == uncached['island_values']
    np.testing.assert_array_equal(cached[0]['face_scores'], uncached['face_scores'])

    faces = np.arange(len(obj12.data.polygons))
    assert abs(visibility_core.score_face_set(obj12, faces, vis_data=cached[0]) - isl_val) < 1e-6
    assert abs(visibility_core.score_face_set(obj12, faces) - isl_val) < 1e-6
    assert visibility_core.score_face_set(obj12, []) == 0.0
    assert visibility_core.score_face_set(None, [0]) == 1.0
    print(f"PASS: test_packer_interface_and_cache (partly shadowed island {isl_val:.3f} = its lit face)")


def test_animation_steps():
    """A step is a share of the widest range that moves, whichever object comes last; one keyframe does not decide it."""
    def animated(name, frames):
        obj = bpy.data.objects.new(name, None)
        bpy.context.scene.collection.objects.link(obj)
        for frame in frames:
            obj.location.z = frame
            obj.keyframe_insert(data_path='location', index=2, frame=frame)
        return obj

    def frames_at(steps):
        ctrl = visibility_core.AnimationStateController(bpy.context.scene)
        out = []
        for step in steps:
            ctrl.apply_percentage_state(step)
            out.append(bpy.context.scene.frame_current)
        ctrl.restore()
        return out

    for names in (('A_MOVES', 'B_HOLDS'), ('B_MOVES', 'A_HOLDS')):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        animated(names[0], (0, 100))
        animated(names[1], (500,))
        assert frames_at((0.0, 0.5, 1.0)) == [0, 50, 100], names
    bpy.ops.wm.read_factory_settings(use_empty=True)
    animated('SHORT', (10, 50))
    animated('LONG', (0, 200))
    animated('LATE', (100, 120))
    assert frames_at((0.0, 0.25, 1.0)) == [0, 50, 200]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    animated('HOLDS', (30,))
    bpy.context.scene.frame_set(7)
    assert frames_at((0.0, 1.0)) == [7, 7] and bpy.context.scene.frame_current == 7
    print("PASS: test_animation_steps")


def test_run_in_pieces():
    """Update Visibility a small piece at a time: the same numbers as all at once, a bar that moves, Esc restores."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    add_light('PROBE')
    _facing_object('FRONT', [((0, -3, 0), 0, 0.3)])
    scene.frame_current = 7
    blend_path = SCRATCH_DIR / 'pieces.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    scene = bpy.context.scene
    include_lights(scene, {'PROBE'})
    scene.fss_visibility.states = 2
    bpy.ops.wm.save_mainfile()
    scene = bpy.context.scene
    whole = visibility_core.analyze_visibility(blend_path=blend_path, lights=['PROBE'], anim_states=(0.0, 1.0))

    def new_op():
        analyzer = visibility_core.VisibilityAnalyzer(scene=scene, view_layer=bpy.context.view_layer, lights=['PROBE'],
                                                      anim_states=(0.0, 1.0), blend_path=blend_path)
        messages = []
        return SimpleNamespace(_analyzer=analyzer, _pieces=analyzer.run_pieces(), _timer=None,
                               _get_settings_dict=lambda context: {}, report=lambda kind, text: messages.append(text),
                               messages=messages)

    timer, esc = SimpleNamespace(type='TIMER'), SimpleNamespace(type='ESC')
    modal = visibility.FSS_OT_UpdateVisibility.modal
    vis_file = blend_path.with_suffix('.visibility')
    if vis_file.exists():
        vis_file.unlink()

    op = new_op()
    for _piece in range(6):
        assert modal(op, bpy.context, timer) == {'RUNNING_MODAL'}
    assert op._analyzer.prepared and visibility._progress is not None and not bpy.ops.fss.update_visibility.poll()
    assert modal(op, bpy.context, esc) == {'CANCELLED'} and visibility._progress is None and op._analyzer is None
    assert not vis_file.exists() and scene.frame_current == 7
    assert all(visibility_core.ORIG_FACE_ATTR_NAME not in me.attributes for me in bpy.data.meshes)
    assert bpy.ops.fss.update_visibility.poll() and 'cancelled' in op.messages[-1]

    op = new_op()
    assert modal(op, bpy.context, SimpleNamespace(type='MOUSEMOVE')) == {'PASS_THROUGH'}
    assert modal(op, bpy.context, SimpleNamespace(type='LEFTMOUSE')) == {'RUNNING_MODAL'}
    assert not op._analyzer.prepared

    fractions, texts, ret, pieces = [], [], {'RUNNING_MODAL'}, 0
    while ret == {'RUNNING_MODAL'}:
        ret = modal(op, bpy.context, timer)
        pieces += 1
        assert pieces < 100, 'the run does not end'
        if visibility._progress is not None:
            fractions.append(visibility._progress['fraction'])
            texts.append(visibility._progress['text'])
            recorder = Recorder()
            visibility.FSS_PT_Visibility.draw(SimpleNamespace(layout=recorder), bpy.context)
            names = [name for name, _a, _kw in recorder.calls]
            assert 'progress' in names and not any(name == 'operator' and args[0] == 'fss.update_visibility'
                                                   for name, args, _kw in recorder.calls), names
    assert ret == {'FINISHED'} and visibility._progress is None and op._analyzer is None, ret
    assert fractions == sorted(fractions) and fractions[0] < 0.1 and 0.5 < fractions[-1] <= 1.0, fractions
    assert pieces >= 2 * 7, pieces
    assert 'View 1 of 2: PROBE, animation 0 %' in texts and 'View 2 of 2: PROBE, animation 100 %' in texts, texts
    assert texts[-1] == 'Scoring the faces', texts
    assert vis_file.exists() and 'Visibility updated' in op.messages[-1]
    data = visibility_core.load_visibility_file(vis_file, use_cache=False)[1]
    for name, arrays in whole['mesh_arrays'].items():
        np.testing.assert_array_equal(data[f'{name}__face_scores'], arrays['face_scores'])

    op = new_op()
    for _piece in range(6):
        modal(op, bpy.context, timer)

    def broken():
        raise ZeroDivisionError('broken')
        yield

    op._pieces = broken()
    assert modal(op, bpy.context, timer) == {'CANCELLED'} and visibility._progress is None and 'stopped' in op.messages[-1]
    assert scene.frame_current == 7
    print(f"PASS: test_run_in_pieces ({pieces} pieces for 2 views)")


def main():
    print("\n" + "=" * 70)
    print("      FSS VISIBILITY TEST SUITE")
    print("=" * 70)
    t0 = time.perf_counter()
    test_light_term_matches_eevee()
    test_synthetic_cases()
    test_percentile_and_step_limit()
    test_spot_and_area_lights()
    test_soft_shadows()
    test_animated_light()
    test_operator_on_saved_scene()
    test_scene_unchanged_after_run_and_esc()
    test_disabled_states()
    test_light_list_sync()
    test_panel_draw()
    test_visibility_heatmap_mode()
    test_heatmap_modifier_face_mapping()
    test_gltf_leak_check()
    test_packer_interface_and_cache()
    test_animation_steps()
    test_run_in_pieces()
    print("\n" + "=" * 70)
    print(f"      ALL TESTS PASSED ({time.perf_counter() - t0:.0f} s)")
    print("=" * 70)


if __name__ == '__main__':
    main()
