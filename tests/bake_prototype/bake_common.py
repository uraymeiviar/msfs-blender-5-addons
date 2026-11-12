"""Shared helpers of the bake prototype (docs/journal/20261112.auto-bake-ao-curvature.md, Session 2).

Paths, 16-bit PNG writing, Cycles AO bake setup, bake images. Runs inside background Blender.
"""
import os
import struct
import time
import zlib

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
WORK = os.path.join(REPO, 'tests', '_work', 'ao_bake')
AO_DISTANCE = 0.1
THREADS = 12


def log(msg, path=None):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    if path:
        with open(path, 'a', encoding='utf-8') as f:
            f.write(line + '\n')


# ---------------------------------------------------------------------------------------------------------------
# PNG (16-bit grey and 8-bit grey/RGB), rows given bottom-up as in Blender images
# ---------------------------------------------------------------------------------------------------------------

def _png_chunk(tag, data):
    return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff)


def write_png(path, arr, bits=16):
    """arr: (H, W) or (H, W, 3) floats in 0..1, row 0 = bottom (Blender convention)."""
    a = np.clip(np.asarray(arr, dtype=np.float64), 0.0, 1.0)[::-1]
    h, w = a.shape[:2]
    ch = 1 if a.ndim == 2 else a.shape[2]
    color_type = {1: 0, 3: 2}[ch]
    if bits == 16:
        q = np.round(a * 65535.0).astype('>u2')
    else:
        q = np.round(a * 255.0).astype(np.uint8)
    q = q.reshape(h, w * ch)
    raw = b''.join(b'\x00' + q[i].tobytes() for i in range(h))
    ihdr = struct.pack('>IIBBBBB', w, h, bits, color_type, 0, 0, 0)
    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n')
        f.write(_png_chunk(b'IHDR', ihdr))
        f.write(_png_chunk(b'IDAT', zlib.compress(raw, 6)))
        f.write(_png_chunk(b'IEND', b''))


def read_png16(path):
    """Reads a PNG written by write_png(bits=16, grey). Returns (H, W) float, row 0 = bottom."""
    with open(path, 'rb') as f:
        data = f.read()
    pos = 8
    idat = b''
    w = h = 0
    while pos < len(data):
        n = struct.unpack('>I', data[pos:pos + 4])[0]
        tag = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + n]
        if tag == b'IHDR':
            w, h = struct.unpack('>II', body[:8])
        elif tag == b'IDAT':
            idat += body
        pos += 12 + n
    raw = np.frombuffer(zlib.decompress(idat), dtype=np.uint8).reshape(h, 1 + 2 * w)
    if np.any(raw[:, 0] != 0):
        raise ValueError('only filter type 0 supported')
    q = raw[:, 1:].copy().view('>u2').reshape(h, w).astype(np.float64) / 65535.0
    return q[::-1].copy()


# ---------------------------------------------------------------------------------------------------------------
# Scene loading and mesh access
# ---------------------------------------------------------------------------------------------------------------

def load_scene(tag):
    """Empty the factory scene and link the collection BAKE_<tag> from scene_<tag>.blend. Returns (target, info)."""
    import json
    import bpy
    scene = bpy.context.scene
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    path = os.path.join(WORK, f'scene_{tag}.blend')
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        dst.collections = [f'BAKE_{tag}']
    coll = dst.collections[0]
    scene.collection.children.link(coll)
    with open(os.path.join(WORK, f'scene_{tag}.json')) as f:
        info = json.load(f)
    target = next(o for o in coll.objects if o.name.startswith('TARGET'))
    return target, info


def mesh_arrays(me):
    """Positions (V,3) float64, triangles (T,3) vertex ids, corner normals (T,3,3), UVs {name: (T,3,2)}.

    The prototype's target meshes are triangles only (extract_scene.py), so corner 3*t+k is corner k of face t.
    """
    nv = len(me.vertices)
    co = np.empty(nv * 3)
    me.vertices.foreach_get('co', co)
    nt = len(me.polygons)
    vi = np.empty(nt * 3, dtype=np.int64)
    me.loops.foreach_get('vertex_index', vi)
    cn = np.empty(nt * 9)
    me.corner_normals.foreach_get('vector', cn)
    uvs = {}
    for uv in me.uv_layers:
        a = np.empty(nt * 6)
        uv.uv.foreach_get('vector', a)
        uvs[uv.name] = a.reshape(nt, 3, 2)
    return co.reshape(-1, 3), vi.reshape(nt, 3), cn.reshape(nt, 3, 3), uvs


def set_uv(me, name, uv_tc2):
    layer = me.uv_layers.get(name) or me.uv_layers.new(name=name)
    layer.uv.foreach_set('vector', np.asarray(uv_tc2, dtype=np.float32).ravel())
    return layer


def build_mesh(name, positions, tris, corner_normals, uv_tc2, uv_name='BAKE_UV'):
    """A triangle mesh with one UV map and custom split normals (corner order = triangle order)."""
    import bpy
    me = bpy.data.meshes.new(name)
    me.from_pydata(np.asarray(positions, dtype=np.float64).tolist(), [], np.asarray(tris).tolist())
    me.update(calc_edges=True)
    if len(me.polygons) != len(tris):
        raise RuntimeError(f'{name}: from_pydata kept {len(me.polygons)} of {len(tris)} faces')
    set_uv(me, uv_name, uv_tc2)
    me.shade_smooth()
    n = np.asarray(corner_normals, dtype=np.float64).reshape(-1, 3)
    me.normals_split_custom_set(n.tolist())
    me.update()
    return me


# ---------------------------------------------------------------------------------------------------------------
# Cycles setup and baking
# ---------------------------------------------------------------------------------------------------------------

def setup_cycles(scene, samples, seed=0):
    import bpy
    scene.render.engine = 'CYCLES'
    cy = scene.cycles
    cy.device = 'CPU'
    cy.samples = samples
    cy.seed = seed
    cy.use_denoising = False
    cy.use_adaptive_sampling = False
    cy.use_animated_seed = False
    scene.render.threads_mode = 'FIXED'
    scene.render.threads = THREADS
    if scene.world is None:
        scene.world = bpy.data.worlds.new('BAKE_WORLD')
    scene.world.light_settings.distance = AO_DISTANCE
    try:
        prefs = bpy.context.preferences.addons['cycles'].preferences
        prefs.compute_device_type = 'NONE'
    except Exception:
        pass


def new_float_image(name, w, h, fill=-1.0):
    import bpy
    img = bpy.data.images.new(name, int(w), int(h), alpha=False, float_buffer=True, is_data=True)
    try:
        img.colorspace_settings.name = 'Non-Color'
    except Exception:
        pass
    px = np.full(int(w) * int(h) * 4, fill, dtype=np.float32)
    px[3::4] = 1.0
    img.pixels.foreach_set(px)
    return img


def image_to_array(img):
    w, h = img.size
    px = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(px)
    return px.reshape(h, w, 4)[:, :, 0].astype(np.float64)


def bake_material(img, name='BAKE_MAT'):
    """A material whose only (active) node is an image texture node holding img."""
    import bpy
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    for n in list(nt.nodes):
        if n.type == 'TEX_IMAGE':
            nt.nodes.remove(n)
    if not any(n.type == 'BSDF_DIFFUSE' for n in nt.nodes):
        for n in list(nt.nodes):
            nt.nodes.remove(n)
        out = nt.nodes.new('ShaderNodeOutputMaterial')
        bsdf = nt.nodes.new('ShaderNodeBsdfDiffuse')
        nt.links.new(bsdf.outputs[0], out.inputs[0])
    tex = nt.nodes.new('ShaderNodeTexImage')
    tex.image = img
    for n in nt.nodes:
        n.select = False
    tex.select = True
    nt.nodes.active = tex
    return mat


def assign_only_material(obj, mat):
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    for p in obj.data.polygons:
        p.material_index = 0


def set_ray_invisible(obj, invisible=True, keep_camera=False):
    """All ray visibility off (Cycles then drops the object from its scene), or all but camera."""
    v = not invisible
    obj.visible_camera = v or keep_camera
    obj.visible_diffuse = v
    obj.visible_glossy = v
    obj.visible_transmission = v
    obj.visible_volume_scatter = v
    obj.visible_shadow = v


def bake(obj, img, uv_name, samples, seed, margin=0, margin_type='ADJACENT_FACES', bake_type='AO',
         from_objects=None, extrusion=1e-4, ray_distance=2e-4):
    """Bake into img (float, pre-filled with -1 so unbaked pixels stay negative). Returns seconds.

    from_objects: bake Selected to Active, reading the surface of these objects at the points of obj (obj itself
    can then be hidden from all rays: Cycles shades the hit on the selected object, with its own self-intersection
    exclusion).
    """
    import bpy
    scene = bpy.context.scene
    setup_cycles(scene, samples, seed)
    mat = bake_material(img)
    assign_only_material(obj, mat)
    uv = obj.data.uv_layers[uv_name]
    obj.data.uv_layers.active = uv
    uv.active_render = True
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    s2a = bool(from_objects)
    for o in (from_objects or []):
        o.select_set(True)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    rb = scene.render.bake
    rb.margin = margin
    rb.margin_type = margin_type
    rb.use_clear = False
    rb.use_selected_to_active = s2a
    rb.target = 'IMAGE_TEXTURES'
    kw = {}
    if s2a:
        kw = dict(cage_extrusion=extrusion, max_ray_distance=ray_distance, use_cage=False)
    t = time.time()
    bpy.ops.object.bake(type=bake_type, margin=margin, margin_type=margin_type, use_clear=False,
                        use_selected_to_active=s2a, target='IMAGE_TEXTURES', **kw)
    return time.time() - t
