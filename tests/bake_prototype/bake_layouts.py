"""The test layouts of the bake prototype (step 5), on copies of the object's UV map; the map itself is not changed.

  a unchanged; b every island rotated 37 degrees about its centre, then packed without scaling; c, d, e islands scaled
  0.5x, 1.9x, 2.5x about their centres, then packed; f Smart UV Project on a copy, scaled to layout (a)'s median
  density, then packed; g layout (a) at a quarter of the texture size.
Packing: shelf, islands 2 x pad apart, no rotation, no scaling.
"""
import math

import numpy as np

import bake_common as bc
import bake_geom as bg


def pack(uvpx, isl, S, pad, width=None):
    """Shelf-pack islands (no rotation, no scaling); returns new uvpx."""
    sep = 2 * pad
    out = uvpx.copy()
    ids = np.unique(isl)
    boxes = []
    for i in ids:
        P = uvpx[isl == i].reshape(-1, 2)
        lo, hi = P.min(axis=0), P.max(axis=0)
        boxes.append((i, lo, hi - lo))
    width = width or S
    width = max(width, int(math.ceil(max(b[2][0] for b in boxes))) + sep)
    boxes.sort(key=lambda b: (-b[2][1], -b[2][0], b[0]))
    x = y = shelf = 0
    for i, lo, ext in boxes:
        w_, h_ = int(math.ceil(ext[0])) + sep, int(math.ceil(ext[1])) + sep
        if x + w_ > width:
            x, y, shelf = 0, y + shelf, 0
        out[isl == i] = uvpx[isl == i] - lo + np.array([x + pad, y + pad])
        x += w_
        shelf = max(shelf, h_)
    return out


def transform_islands(uvpx, isl, scale=1.0, angle=0.0):
    out = uvpx.copy()
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    R = np.array([[c, -s], [s, c]]) * scale
    for i in np.unique(isl):
        P = uvpx[isl == i]
        flat = P.reshape(-1, 2)
        ctr = (flat.min(axis=0) + flat.max(axis=0)) / 2
        out[isl == i] = (P - ctr) @ R.T + ctr
    return out


def smart_uv(target):
    import bpy
    dup = target.copy()
    dup.data = target.data.copy()
    bpy.context.scene.collection.objects.link(dup)
    layer = dup.data.uv_layers.new(name='SMART')
    dup.data.uv_layers.active = layer
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    dup.select_set(True)
    bpy.context.view_layer.objects.active = dup
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=math.radians(66.0), island_margin=0.0, scale_to_bounds=False)
    bpy.ops.object.mode_set(mode='OBJECT')
    _, _, _, u2 = bc.mesh_arrays(dup.data)
    bpy.data.objects.remove(dup)
    return u2['SMART']


def make_layouts(target, pos, tris, wt, uv0, S, pad, keys):
    """{key: (uv px (T,3,2), texture size, island per face)} and layout (a)'s median density."""
    a3 = bg.tri_areas_3d(pos, tris)
    isl_a = bg.uv_islands(wt, uv0)
    layouts = {}
    base = uv0 * S
    med_a = bg.weighted_median(bg.densities(pos, tris, base)[a3 > 0], a3[a3 > 0])
    if 'a' in keys:
        layouts['a'] = (base, S, isl_a)
    if 'b' in keys:
        layouts['b'] = (pack(transform_islands(base, isl_a, angle=37.0), isl_a, S, pad), S, isl_a)
    for key, sc in (('c', 0.5), ('d', 1.9), ('e', 2.5)):
        if key in keys:
            layouts[key] = (pack(transform_islands(base, isl_a, scale=sc), isl_a, S, pad, width=int(S * max(sc, 1))),
                            S, isl_a)
    if 'f' in keys:
        su = smart_uv(target)
        isl_f = bg.uv_islands(wt, su)
        d_f = bg.weighted_median(bg.densities(pos, tris, su * S)[a3 > 0], a3[a3 > 0])
        layouts['f'] = (pack(su * S * (med_a / d_f), isl_f, S, pad), S, isl_f)
    if 'g' in keys:
        layouts['g'] = (uv0 * (S // 4), S // 4, isl_a)
    return layouts, med_a
