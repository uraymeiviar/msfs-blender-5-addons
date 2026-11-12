"""Session 20: how Cycles' bake treats the parts of a triangle that lie outside the image (clipped or wrapped).

Run: blender -b --factory-startup --python s20_clip_check.py

A plane of three triangles is baked (AO, margin 0, image pre-filled with -1) into a 64 x 64 image:
- T_IN: inside the image (u 0.05..0.30);
- T_CROSS: crosses the right edge (u 0.60..1.60) and the top edge (v 0.40..1.40);
- T_OUT: entirely outside (u 1.20..1.45, v 0.05..0.30) and (u -0.80..-0.55) for a second plane.
Wrapped parts would land at u - 1 (0.20..0.45 for T_OUT) or v - 1; clipped parts write nothing there.
Prints the written pixels per region.
"""
import bpy
import numpy as np

N = 64
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
scene = bpy.context.scene
scene.render.engine = 'CYCLES'
scene.cycles.samples = 4
scene.cycles.device = 'CPU'
scene.render.threads_mode = 'FIXED'
scene.render.threads = 4

verts = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (2, 0, 0), (3, 0, 0), (2, 1, 0), (4, 0, 0), (5, 0, 0), (4, 1, 0),
         (6, 0, 0), (7, 0, 0), (6, 1, 0)]
faces = [(0, 1, 2), (3, 4, 5), (6, 7, 8), (9, 10, 11)]
uvs = [[(0.05, 0.05), (0.30, 0.05), (0.05, 0.30)],      # T_IN
       [(0.60, 0.40), (1.60, 0.40), (0.60, 1.40)],      # T_CROSS
       [(1.20, 0.05), (1.45, 0.05), (1.20, 0.30)],      # T_OUT right
       [(-0.80, 0.55), (-0.55, 0.55), (-0.80, 0.80)]]   # T_OUT left
me = bpy.data.meshes.new('clip')
me.from_pydata(verts, [], faces)
uv = me.uv_layers.new(name='UV')
for poly, tri in zip(me.polygons, uvs):
    for li, c in zip(poly.loop_indices, tri):
        uv.data[li].uv = c
obj = bpy.data.objects.new('clip', me)
scene.collection.objects.link(obj)
img = bpy.data.images.new('clip', N, N, alpha=False, float_buffer=True, is_data=True)
px = np.full(N * N * 4, -1.0, np.float32)
px[3::4] = 1
img.pixels.foreach_set(px)
mat = bpy.data.materials.new('clip')
mat.use_nodes = True
tex = mat.node_tree.nodes.new('ShaderNodeTexImage')
tex.image = img
mat.node_tree.nodes.active = tex
me.materials.append(mat)
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
bpy.ops.object.bake(type='AO', margin=0, use_clear=False, target='IMAGE_TEXTURES')
img.pixels.foreach_get(px)
R = px.reshape(N, N, 4)[:, :, 0]
written = R >= 0
ys, xs = np.nonzero(written)
c = (np.arange(N) + 0.5) / N
U, V = np.meshgrid(c, c)


def inside(tri, u, v):
    (ax, ay), (bx, by), (cx, cy) = tri
    d = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
    l1 = ((by - cy) * (u - cx) + (cx - bx) * (v - cy)) / d
    l2 = ((cy - ay) * (u - cx) + (ax - cx) * (v - cy)) / d
    return (l1 >= 0) & (l2 >= 0) & (1 - l1 - l2 >= 0)


exp_in = inside(uvs[0], U, V)
exp_cross = inside(uvs[1], U, V)
wrap = np.zeros_like(written)
for tri in uvs[1:]:
    for du in (-1, 0, 1):
        for dv in (-1, 0, 1):
            if du == dv == 0:
                continue
            wrap |= inside([(a + du, b + dv) for a, b in tri], U, V)
expected = exp_in | exp_cross
print(f'CLIPCHECK written {int(written.sum())} px; T_IN expected {int(exp_in.sum())}, written there '
      f'{int((written & exp_in).sum())}; T_CROSS clipped part expected {int(exp_cross.sum())}, written there '
      f'{int((written & exp_cross).sum())}; written outside the clipped parts {int((written & ~expected).sum())} '
      f'(of which at wrapped positions {int((written & ~expected & wrap).sum())}); wrapped positions available '
      f'{int((wrap & ~expected).sum())}')
