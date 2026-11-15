"""A Blender mesh to the arrays polygoneReduce takes, and the reduced arrays back to a Blender mesh.

In: every face corner becomes a split vertex of the library, and corners of one Blender vertex with the same normal,
UVs and colours are one split vertex; triangles are Blender's loop triangles, their group the material index. Feature
edges come from the mesh's sharp edges, marked seams and creases and from an angle, as the panel asks; locks and
importance from vertex groups.

Out: output vertices at one position are one Blender vertex (the library's points are positions too), each triangle a
face with its corners' UVs, colours and custom normals, its material index from the triangle's group. Vertex group
weights come from the input vertex each output vertex names as its source.
"""

import math

import bpy
import numpy as np

from . import native


def _rows(array):
    """A contiguous 2D array as one void value per row, for np.unique over rows by their bytes."""
    array = np.ascontiguousarray(array)
    return array.view(np.dtype((np.void, array.dtype.itemsize * array.shape[1]))).reshape(-1)


def _edge_flags(me, name, kind):
    """A boolean or float edge attribute as a numpy array, or None when the mesh has none."""
    attr = me.attributes.get(name)
    if attr is None or attr.domain != 'EDGE':
        return None
    values = np.empty(len(me.edges), dtype=np.float32 if kind == 'FLOAT' else bool)
    attr.data.foreach_get('value', values)
    return values


def vertex_group_weights(me):
    """Every (vertex, group, weight) of the mesh, as three arrays."""
    verts, groups, weights = [], [], []
    for v in me.vertices:
        for g in v.groups:
            verts.append(v.index)
            groups.append(g.group)
            weights.append(g.weight)
    return np.array(verts, dtype=np.int64), np.array(groups, dtype=np.int64), np.array(weights, dtype=np.float32)


def read(me, group_names, s):
    """The library's input for one mesh, and what is needed to build the output. s: the panel's settings."""
    me.calc_loop_triangles()
    nv, nl, nt = len(me.vertices), len(me.loops), len(me.loop_triangles)
    co = np.empty(nv * 3, dtype=np.float32)
    me.vertices.foreach_get('co', co)
    co = co.reshape(-1, 3)
    loop_vert = np.empty(nl, dtype=np.int32)
    me.loops.foreach_get('vertex_index', loop_vert)
    tri_loops = np.empty(nt * 3, dtype=np.int32)
    me.loop_triangles.foreach_get('loops', tri_loops)
    tri_mat = np.empty(nt, dtype=np.int32)
    me.loop_triangles.foreach_get('material_index', tri_mat)

    # Attribute streams per corner: (kind, name, data (nl, c), weight, flags)
    streams = []
    normals = np.empty(nl * 3, dtype=np.float32)
    me.corner_normals.foreach_get('vector', normals)
    streams.append(('NORMAL', '', normals.reshape(-1, 3), s.normal_weight, native.ATTRIBUTE_UNIT_VECTOR))
    for layer in me.uv_layers:
        uv = np.empty(nl * 2, dtype=np.float32)
        layer.uv.foreach_get('vector', uv)
        streams.append(('UV', layer.name, uv.reshape(-1, 2), s.uv_weight, 0))
    for attr in me.color_attributes:
        if attr.domain == 'CORNER':
            c = np.empty(nl * 4, dtype=np.float32)
            attr.data.foreach_get('color', c)
            c = c.reshape(-1, 4)
        elif attr.domain == 'POINT':
            c = np.empty(nv * 4, dtype=np.float32)
            attr.data.foreach_get('color', c)
            c = c.reshape(-1, 4)[loop_vert]
        else:
            continue
        streams.append(('COLOR', attr.name, c, s.color_weight, native.ATTRIBUTE_CLAMP01))

    # Split vertices: corners at one position with equal values are one, as in glTF. Keyed by position, not by
    # Blender vertex: an imported glTF often keeps one Blender vertex per glTF vertex or per corner, and corners equal
    # in everything but their Blender vertex would otherwise be seams the library cannot collapse. UVs and colours
    # must be equal bit for bit; normals within the merge angle, because Blender stores custom normals with an
    # encoding error (on SciFiHelmet up to about 1 degree between corners that had one normal in the glTF).
    # Triangle groups: material * 2 + 1 for a flat face of a mesh without custom normals, whose normals Blender
    # derives from the face. Such corners take one normal per position (the area-weighted mean of the face normals
    # there) instead of the face normal, so flat shading does not make every edge a normal seam; the group bit gives
    # the face Flat shading again in the output, and the border between flat and smooth faces (a visible one) is held
    # like a material border. With custom normals the corner normals are data and stay as they are.
    npoly = len(me.polygons)
    poly_mat = np.empty(npoly, dtype=np.int32)
    me.polygons.foreach_get('material_index', poly_mat)
    totals = np.empty(npoly, dtype=np.int32)
    me.polygons.foreach_get('loop_total', totals)
    smooth = np.empty(npoly, dtype=bool)
    me.polygons.foreach_get('use_smooth', smooth)
    flat_face = ~smooth if not me.has_custom_normals else np.zeros(npoly, dtype=bool)
    derived = np.repeat(flat_face, totals)  # face loops are contiguous and in face order
    if np.any(derived):
        face_n = np.empty(npoly * 3, dtype=np.float32)
        me.polygons.foreach_get('normal', face_n)
        area = np.empty(npoly, dtype=np.float32)
        me.polygons.foreach_get('area', area)
        _u, position = np.unique(_rows(co[loop_vert]), return_inverse=True)
        position = position.reshape(-1)
        weighted = np.repeat(face_n.reshape(-1, 3) * area[:, None], totals, axis=0)
        mean = np.zeros((position.max() + 1, 3), dtype=np.float64)
        np.add.at(mean, position, weighted)
        length = np.linalg.norm(mean, axis=1)
        mean = np.where(length[:, None] > 0, mean / np.maximum(length, 1e-30)[:, None], [0.0, 0.0, 1.0])
        normals = streams[0][2]
        normals[derived] = mean[position[derived]].astype(np.float32)
    poly_group = np.maximum(poly_mat, 0) * 2 + flat_face
    loop_mat = np.repeat(poly_group, totals).astype(np.int32)
    tri_poly = np.empty(nt, dtype=np.int32)
    me.loop_triangles.foreach_get('polygon_index', tri_poly)
    tri_mat = poly_group[tri_poly]
    # The group is part of the split-vertex key: the library takes a vertex in one triangle group only, as glTF
    # primitives have their own vertices.
    corner_key = np.concatenate([co[loop_vert], loop_mat.view(np.float32)[:, None]], axis=1)
    first_loop, inverse = _split_corners(corner_key, streams, s.normal_merge_angle)
    split_vertex = loop_vert[first_loop]  # a Blender vertex of each split vertex (for vertex group weights)
    indices = inverse[tri_loops]

    # Locks and importance from vertex groups, per Blender vertex, then per split vertex: the largest over the
    # corners it joins, so a lock on any of several Blender vertices at one position holds.
    locks = importance = None
    vg = vertex_group_weights(me) if group_names else (np.empty(0, np.int64),) * 2 + (np.empty(0, np.float32),)
    index_of = {name: i for i, name in enumerate(group_names)}
    if s.lock_group and s.lock_group in index_of:
        sel = vg[1] == index_of[s.lock_group]
        per_vertex = np.zeros(nv, dtype=np.uint8)
        per_vertex[vg[0][sel]] = vg[2][sel] >= 0.5
        locks = np.zeros(len(first_loop), dtype=np.uint8)
        np.maximum.at(locks, inverse, per_vertex[loop_vert])
    if s.importance_group and s.importance_group in index_of:
        sel = vg[1] == index_of[s.importance_group]
        per_vertex = np.ones(nv, dtype=np.float32)
        per_vertex[vg[0][sel]] = 1.0 + vg[2][sel] * (s.importance_strength - 1.0)
        importance = np.zeros(len(first_loop), dtype=np.float32)
        np.maximum.at(importance, inverse, np.maximum(per_vertex, 0.0)[loop_vert])

    features = _features(me, co, loop_vert, split_vertex, s)

    mesh = dict(positions=co[split_vertex], indices=indices,
                attributes=[(d[first_loop], w, f) for _k, _n, d, w, f in streams],
                groups=np.maximum(tri_mat, 0).astype(np.uint32), locks=locks, importance=importance,
                features=features)
    info = dict(streams=[(k, n, d.shape[1]) for k, n, d, _w, _f in streams], split_vertex=split_vertex,
                vertex_groups=vg, triangles=nt, vertices=nv, split_vertices=len(first_loop),
                feature_edges=0 if features is None else len(features[0]),
                active_uv=me.uv_layers.active_index, render_uv=next(
                    (i for i, l in enumerate(me.uv_layers) if l.active_render), -1),
                diagonal=float(np.linalg.norm(co.max(axis=0) - co.min(axis=0))) if nv else 0.0)
    return mesh, info


def _split_corners(corner_positions, streams, merge_angle):
    """(first corner of each split vertex, split vertex of each corner). Corners share a split vertex when position,
    UVs and colours are equal bit for bit and their normals differ by less than merge_angle degrees (0 = equal)."""
    normals = next(d for k, _n, d, _w, _f in streams if k == 'NORMAL')
    others = [d for k, _n, d, _w, _f in streams if k != 'NORMAL']
    if merge_angle <= 0:
        key = np.concatenate([corner_positions, normals] + others, axis=1)
        _u, first, inverse = np.unique(_rows(key), return_index=True, return_inverse=True)
        return first, inverse.reshape(-1).astype(np.uint32)
    cos_tol = math.cos(math.radians(merge_angle))
    _u, first, group = np.unique(_rows(np.concatenate([corner_positions] + others, axis=1)), return_index=True,
                                 return_inverse=True)
    group = group.reshape(-1)
    label = np.zeros(len(group), dtype=np.int64)
    # Most groups: every normal close to the group's first corner's. The rest: greedy, in corner order.
    close = np.einsum('ij,ij->i', normals, normals[first[group]]) >= cos_tol
    bad = np.unique(group[~close])
    if len(bad):
        order = np.argsort(group, kind='stable')
        starts = np.searchsorted(group[order], bad, side='left')
        ends = np.searchsorted(group[order], bad, side='right')
        for start, end in zip(starts, ends):
            reps = []
            for corner in order[start:end]:
                for rep_label, rep_normal in reps:
                    if float(np.dot(rep_normal, normals[corner])) >= cos_tol:
                        label[corner] = rep_label
                        break
                else:
                    label[corner] = len(reps)
                    reps.append((len(reps), normals[corner]))
    key = np.stack([group.astype(np.int64), label], axis=1)
    _u, first, inverse = np.unique(_rows(key), return_index=True, return_inverse=True)
    return first, inverse.reshape(-1).astype(np.uint32)


def _features(me, co, loop_vert, split_vertex, s):
    """Feature edges (split vertex pairs and weights) from sharp edges, seams, creases and the feature angle."""
    ne = len(me.edges)
    if ne == 0:
        return None
    weight = np.zeros(ne, dtype=np.float32)
    if s.use_sharp:
        sharp = _edge_flags(me, 'sharp_edge', 'BOOLEAN')
        if sharp is not None:
            weight = np.where(sharp, np.maximum(weight, s.sharp_weight), weight)
    if s.use_seams:
        seam = np.zeros(ne, dtype=bool)
        try:
            me.edges.foreach_get('use_seam', seam)
        except (AttributeError, TypeError):
            seam = _edge_flags(me, '.uv_seam', 'BOOLEAN')
        if seam is not None:
            weight = np.where(seam, np.maximum(weight, s.seam_weight), weight)
    if s.use_creases:
        crease = _edge_flags(me, 'crease_edge', 'FLOAT')
        if crease is not None:
            weight = np.maximum(weight, crease * s.crease_weight)

    # Faces per edge, and the feature angle between the two faces of a manifold edge.
    loop_edge = np.empty(len(me.loops), dtype=np.int32)
    me.loops.foreach_get('edge_index', loop_edge)
    totals = np.empty(len(me.polygons), dtype=np.int32)
    me.polygons.foreach_get('loop_total', totals)
    loop_poly = np.repeat(np.arange(len(me.polygons), dtype=np.int32), totals)
    faces_per_edge = np.bincount(loop_edge, minlength=ne)
    if s.feature_angle > 0.0:
        normals = np.empty(len(me.polygons) * 3, dtype=np.float32)
        me.polygons.foreach_get('normal', normals)
        normals = normals.reshape(-1, 3)
        order = np.argsort(loop_edge, kind='stable')
        edges_sorted = loop_edge[order]
        starts = np.searchsorted(edges_sorted, np.arange(ne))
        two = np.nonzero(faces_per_edge == 2)[0]
        a = loop_poly[order[starts[two]]]
        b = loop_poly[order[starts[two] + 1]]
        cos = np.einsum('ij,ij->i', normals[a], normals[b])
        bent = two[cos < math.cos(math.radians(s.feature_angle))]
        weight[bent] = np.maximum(weight[bent], s.angle_weight)

    ev = np.empty(ne * 2, dtype=np.int32)
    me.edges.foreach_get('vertices', ev)
    ev = ev.reshape(-1, 2)
    # A split vertex of each Blender vertex (any copy names the point).
    any_split = np.full(len(me.vertices), -1, dtype=np.int64)
    any_split[split_vertex[::-1]] = np.arange(len(split_vertex) - 1, -1, -1)
    chosen = np.nonzero((weight > 0) & (faces_per_edge > 0))[0]
    a, b = any_split[ev[chosen, 0]], any_split[ev[chosen, 1]]
    apart = np.any(co[ev[chosen, 0]] != co[ev[chosen, 1]], axis=1)
    keep = (a >= 0) & (b >= 0) & apart
    if not np.any(keep):
        return None
    pairs = np.stack([a[keep], b[keep]], axis=1).astype(np.uint32)
    return pairs, weight[chosen][keep]


def build(name, result, info, source_mesh):
    """A new Blender mesh from a reduction result. Returns (mesh, faces dropped, output vertex -> source Blender
    vertex)."""
    pos = result['positions']
    tris = result['indices'].reshape(-1, 3).astype(np.int64)
    _u, first, weld = np.unique(_rows(pos), return_index=True, return_inverse=True)
    weld = weld.reshape(-1)
    corners = weld[tris]
    # Blender cannot hold a face with one vertex twice; the library's triangles have area, so this stays rare.
    good = (corners[:, 0] != corners[:, 1]) & (corners[:, 1] != corners[:, 2]) & (corners[:, 0] != corners[:, 2])
    dropped = int(np.count_nonzero(~good))
    tris, corners = tris[good], corners[good]
    groups = result['groups'][good]
    nt = len(tris)
    # Faces on one set of positions (double-sided geometry the input had) are duplicates to Blender, which only holds
    # them on separate vertices: every such face after the first gets its own copies of its three vertices.
    vertex_split = result['sources'][first]  # the input split vertex each Blender vertex takes its weights from
    _u, first_face, face_set = np.unique(_rows(np.sort(corners, axis=1)), return_index=True, return_inverse=True)
    repeated = np.flatnonzero(first_face[face_set.reshape(-1)] != np.arange(nt))
    vertex_pos = pos[first]
    if len(repeated):
        copies = corners[repeated].ravel()
        corners[repeated] = (len(first) + np.arange(len(copies))).reshape(-1, 3)
        vertex_pos = np.concatenate([vertex_pos, vertex_pos[copies]])
        vertex_split = np.concatenate([vertex_split, vertex_split[copies]])

    me = bpy.data.meshes.new(name)
    me.vertices.add(len(vertex_pos))
    me.vertices.foreach_set('co', vertex_pos.astype(np.float32).ravel())
    me.loops.add(nt * 3)
    me.loops.foreach_set('vertex_index', corners.astype(np.int32).ravel())
    me.polygons.add(nt)
    me.polygons.foreach_set('loop_start', np.arange(0, nt * 3, 3, dtype=np.int32))
    try:
        me.polygons.foreach_set('loop_total', np.full(nt, 3, dtype=np.int32))
    except (AttributeError, TypeError, RuntimeError):
        pass  # read-only since Blender 4.0: derived from loop_start
    me.update(calc_edges=True)
    for mat in source_mesh.materials:
        me.materials.append(mat)
    materials, flat = groups >> 1, (groups & 1).astype(bool)  # the groups read() made
    if len(source_mesh.materials):
        me.polygons.foreach_set('material_index', np.minimum(materials, len(source_mesh.materials) - 1).astype(np.int32))
    me.polygons.foreach_set('use_smooth', ~flat)

    loop_split = tris.ravel()  # the output split vertex of each corner
    normals = None
    for (kind, stream_name, _c), data in zip(info['streams'], result['attributes']):
        per_loop = data[loop_split]
        if kind == 'NORMAL':
            normals = per_loop
        elif kind == 'UV':
            layer = me.uv_layers.new(name=stream_name, do_init=False)
            layer.uv.foreach_set('vector', per_loop.astype(np.float32).ravel())
        elif kind == 'COLOR':
            attr = me.color_attributes.new(stream_name, 'FLOAT_COLOR', 'CORNER')
            attr.data.foreach_set('color', per_loop.astype(np.float32).ravel())
    if 0 <= info['active_uv'] < len(me.uv_layers):
        me.uv_layers.active_index = info['active_uv']
    if 0 <= info['render_uv'] < len(me.uv_layers):
        me.uv_layers[info['render_uv']].active_render = True
    if normals is not None:
        normals = normals.reshape(-1, 3).copy()
        normals[np.repeat(flat, 3)] = 0.0  # zero: Blender's own normal, the face normal of a flat face
        me.normals_split_custom_set(normals.tolist())
    me.update()

    vertex_source = info['split_vertex'][vertex_split]
    return me, dropped, vertex_source


def copy_vertex_groups(obj, info, vertex_source, group_names):
    """Vertex group weights of the output vertices, each from the input vertex it came from."""
    verts, groups, weights = info['vertex_groups']
    if not len(verts) or not group_names:
        return
    targets = []
    for name in group_names:
        vg = obj.vertex_groups.get(name) or obj.vertex_groups.new(name=name)
        targets.append(vg)
    # For each input vertex, its (group, weight) entries; then per output vertex.
    order = np.argsort(verts, kind='stable')
    verts, groups, weights = verts[order], groups[order], weights[order]
    start = np.searchsorted(verts, vertex_source, side='left')
    end = np.searchsorted(verts, vertex_source, side='right')
    by_group = {}
    for out_index in range(len(vertex_source)):
        for k in range(start[out_index], end[out_index]):
            by_group.setdefault((int(groups[k]), float(weights[k])), []).append(out_index)
    for (group, weight), members in by_group.items():
        if 0 <= group < len(targets):
            targets[group].add(members, weight, 'REPLACE')
