"""AO Bake panel (auto-bake journal, decision 29 and P46): bake masters in a second Blender, apply them to textures.

FSS MSFS Tools > AO Bake:
- Bake: AO distance (scene, decision 16), Auto Distance (decision 51), Distance Falloff (decision 53), Curvature Map
  (decision 54), the baker (Auto, FSS OptiX or Cycles: OptiX baker journal decision 22) with FSS OptiX's samples
  (decision 24) and Cycles' samples and device; poses of moving parts and the occluders (scene defaults, decisions 34
  and 35), the run mode (Hidden or Visible, decision 36); the active object's overrides (poses, occluders; Custom:
  Scene as occluder and a list whose items are added or ignored, filled by an eyedropper field or Add Selected, with
  Remove and Clear, decision 60; an item With its children covers a parent's branch, decision 63; the occluders the
  scene rule detected at the last Refresh as a tree with their parents, joined for several selected objects, with
  [+] and [-] per row (on a parent: its branch) and a button selecting the object, decisions 62, 63 and 66, with a
  Refresh button); the masters' counts (up to date,
  surroundings changed, mesh changed, missing, excluded); Bake Missing and Stale, Bake Selected, Select Stale, Select
  Missing; while a bake runs, object n of m with the share done (tiles and views), its name, tile, copy and pose, time
  spent and left, and Cancel (no preview of the master being baked: the FSS OptiX window shows it, OptiX baker
  decision 30); the bake reads a snapshot of the current state (unsaved changes included); the report of the last
  bake.
- Apply: padding; a row per texture set with its state (masters complete, or the number missing or stale; faces under
  4 x); for the active row: target (ORM slot texture or separate file) and the separate file's output folder,
  name, resolution, layout, green and blue, sampling; the warnings; Apply, Apply All, Apply Selected.
The panel draws without writing: the hashes are computed by Refresh (and before a bake), index.json is read when a
file opens and after a bake.
"""

import fnmatch
import os
import time

import bpy
from bpy.app.handlers import persistent

from . import ao_bake_apply as apply_mod
from . import ao_bake_native as native
from . import ao_bake_store as store

DEVICES = [('CPU', 'CPU', 'Bake on the CPU'), ('GPU', 'GPU', 'Bake on the first GPU type found (OptiX, CUDA, HIP, oneAPI)')]
BAKERS = [  # OptiX baker journal decision 22
    ('AUTO', 'Auto', "FSS OptiX when it can run here (an NVIDIA GPU), else Cycles"),
    ('OPTIX', 'FSS OptiX', "The add-on's own AO baker on the NVIDIA GPU (OptiX), with its own denoiser; where it "
     "cannot run, or fails, Cycles bakes and the report says why"),
    ('CYCLES', 'Cycles', "Blender's Cycles bakes every master (CPU or GPU, Device)")]
_res_items = {}  # Blender keeps no reference to a dynamic enum's strings: kept here, per material


def resolution_items(self, context):
    """A new file's size: the ORM texture's (only when the material has one), or a size of its own. The numbers
    are the static list's (ORM 0, then the sizes), so stored values keep their meaning."""
    mat = self.id_data
    size = apply_mod.orm_size(mat)
    items = []
    if size is not None:
        items.append(('ORM', f'ORM Texture Size ({size[0]} x {size[1]})',
                      "The size of the texture in the material's ORM slot", 0))
    items += [(r, f'{r} x {r}', f'{r} x {r} pixels', i + 1) for i, r in enumerate(apply_mod.RESOLUTIONS)]
    _res_items[mat.name] = items
    return items


def _res_get(self, key):
    """The stored choice; ORM Texture Size without an ORM texture: the texture set's size (UV Auto Packing)."""
    v = self.get(key, 0)
    if v == 0 and apply_mod.orm_size(self.id_data) is None:
        size = str(store.texture_size(self.id_data))
        rs = apply_mod.RESOLUTIONS
        return rs.index(size) + 1 if size in rs else rs.index('2048') + 1
    return v


def _get_resolution(self):
    return _res_get(self, 'resolution')


def _set_resolution(self, value):
    self['resolution'] = value


def _get_curv_resolution(self):
    return _res_get(self, 'curv_resolution')


def _set_curv_resolution(self, value):
    self['curv_resolution'] = value


def _redraw(sidebar_only=False):
    """The 3D views redrawn; sidebar_only: only their sidebar (the panel's progress while a bake or an Apply runs: a
    whole 3D view of a large scene takes long to draw, and Apply drew it after every 0.1 s of work)."""
    wm = bpy.context.window_manager
    for window in getattr(wm, 'windows', ()):
        for area in window.screen.areas:
            if area.type != 'VIEW_3D':
                continue
            if not sidebar_only:
                area.tag_redraw()
                continue
            for region in area.regions:
                if region.type == 'UI':
                    region.tag_redraw()


def _get_curv_folder(self):
    """The curvature's Output Folder: its own, else the AO's (shown in the box; stored empty, it follows the AO's)."""
    return self.get('curv_output_folder', '') or self.output_folder


def _set_curv_folder(self, value):
    self['curv_output_folder'] = '' if value == self.output_folder else value


class FSS_AOBakeSettings(bpy.types.PropertyGroup):
    distance: bpy.props.FloatProperty(name="AO Distance", default=0.25, min=0.001, soft_max=1.0, unit='LENGTH',
                                      precision=3, description="How far other geometry darkens a surface, one value "
                                      "for the whole file. With Auto Distance (shown as Max Distance): the most any "
                                      "object gets; objects larger than it bake at this distance. Good values are "
                                      "about the gaps where large parts should still shade each other; a cockpit: a "
                                      "few cm to 10 cm. Changing it makes the masters it affects stale")
    auto_distance: bpy.props.BoolProperty(
        name="Auto Distance", default=False,
        description="Small objects bake with a shorter AO distance: the factor times the longest axis of the object's "
        "own box, at most AO Distance. A small part is then shaded by its own shape and what is close to it, not by "
        "everything within AO Distance. A shared mesh's copies all use the first copy's distance")
    auto_distance_factor: bpy.props.FloatProperty(
        name="Factor", default=1.0, min=0.05, soft_max=4.0, precision=2,
        description="AO distance of an object = this factor times the longest axis of its box (at most AO Distance)")
    falloff: bpy.props.BoolProperty(
        name="Distance Falloff", default=False,
        description="An occluder darkens less the farther it is: full at the surface, nothing at the AO distance "
        "(linear). Each view is baked once per step and averaged, so the bake takes about as many times longer")
    falloff_steps: bpy.props.IntProperty(
        name="Steps", default=3, min=2, max=16,
        description="Distances of the falloff: the AO distance times 1/n, 2/n ... 1. More steps make the falloff "
        "smoother and the bake longer")
    bake_ao: bpy.props.BoolProperty(
        name="AO Bake Selected", default=True,
        description="Run bakes the AO masters of the selected objects (Baker); with CM also ticked, each object's "
        "curvature is written with its AO")
    curvature: bpy.props.BoolProperty(
        name="CM Bake Selected", default=False,
        description="Run writes the curvature masters (CM) of the selected objects: each object's curvature from its geometry in "
        "its AO master's layout, no rays, seconds per object. Without AO, only objects whose AO master is up to date "
        "in mesh (its layout is used). 50 % grey flat, lighter convex, darker concave")
    curv_width: bpy.props.FloatProperty(
        name="Curvature Width", default=0.0005, min=0.00001, soft_max=0.005, unit='LENGTH', precision=2,
        description="How far from a sharp edge its curvature band reaches, and the width over which a smooth bend is "
        "measured, in the model's units: the same on every island. Changing it makes the curvature masters stale "
        "(bake CM; the AO is not touched)")
    # decision 56: the master denoised after its bake, guided by its geometry and its curvature master
    denoise: bpy.props.BoolProperty(
        name="Denoise", default=False,
        description="Each AO master is denoised after its bake (Method). The raw bake is kept beside it, so changing "
        "these options re-runs only the denoise (Bake Selected with AO ticked), not the rays")
    dn_method: bpy.props.EnumProperty(name="Method", default='OIDN', items=[
        ('OIDN', 'OIDN', "Intel Open Image Denoise run on each group of islands apart (islands do not bleed into "
         "one another). With FSS OptiX its own OIDN on the GPU, which also keeps each area's mean AO and moves no "
         "pixel further than its noise; with Cycles the one Blender ships, on the GPU when the bake runs on the GPU. "
         "Fast, only Strength"),
        ('FILTER', 'Surface Filter', "An edge-aware filter of our own: smooths along the surface, keeps sharp edges, "
         "curvature changes and real AO changes (contact shadows); its options below")])
    dn_strength: bpy.props.FloatProperty(
        name="Strength", default=1.0, min=0.0, max=1.0, subtype='FACTOR',
        description="How much of the filtered value replaces the baked one: 1 the filtered, 0.5 halfway, 0 the bake")
    dn_radius: bpy.props.FloatProperty(
        name="Radius", default=0.001, min=0.00001, soft_max=0.01, unit='LENGTH', precision=2,
        description="How far on the surface a pixel is averaged with others (the spread of a Gaussian in 3D). "
        "Larger: smoother, but more AO detail can be lost; it reaches at most what Max Levels allow")
    dn_levels: bpy.props.IntProperty(
        name="Max Levels", default=5, min=1, max=7,
        description="The filter's passes, each reaching twice as far (5: about 18 master pixels of spread, 7: 74). "
        "Fewer than the Radius needs are used when they reach it; more levels take longer and read more rows")
    dn_detail: bpy.props.FloatProperty(
        name="Smoothing", default=3.0, min=0.25, soft_max=8.0, precision=2,
        description="How different two pixels' AO may be, counted in their noise, and still be averaged: higher "
        "smooths more (and can soften contact shadows), lower keeps more AO detail (and more noise)")
    dn_normal: bpy.props.FloatProperty(
        name="Sharp Angle Threshold", default=0.5235988, min=0.0174533, max=3.14159, subtype='ANGLE',
        description="Pixels whose shading normals differ by more are never averaged: the faces of a sharp edge stay "
        "apart")
    dn_curv_mode: bpy.props.EnumProperty(
        name="Curvature Guide", default='SIMILAR', items=[
            ('SIMILAR', 'Similar', "A pixel counts less the more its curvature differs (by Threshold): a sharp edge's "
             "band is smoothed along the edge, not across it. Needs the curvature master (written with the AO)"),
            ('SHRINK', 'Shrink', "The radius shrinks with the curvature: no filtering at Threshold from flat and "
             "beyond, so edge bands and tight bends stay as baked (and keep their noise)"),
            ('OFF', 'Off', "The curvature is not used: the sharp angle and the AO difference only")])
    dn_curv_threshold: bpy.props.FloatProperty(
        name="Threshold", default=0.1, min=0.005, max=1.0, precision=3,
        description="The curvature difference (0 to 1, flat grey 0.5) that counts as different: Similar's spread, "
        "Shrink's curvature where the filter stops")
    dn_noise: bpy.props.EnumProperty(
        name="Noise", default='MEASURED', items=[
            ('MEASURED', 'Measured', "The noise is measured on the master itself (each pixel against its neighbours "
             "on the same face)"),
            ('SAMPLES', 'From Samples', "The noise expected from the sample count (v (1 - v) / samples); usually more "
             "than the bake has, so it smooths more")])
    apply_ao: bpy.props.BoolProperty(
        name="Apply AO to Texture", default=True,
        description="Run writes the selected objects' AO masters into their texture sets' AO target (Texture "
        "Target), after the bake when one is ticked")
    apply_cm: bpy.props.BoolProperty(
        name="Apply CM to Texture", default=False,
        description="Run writes the selected objects' curvature masters into their texture sets' curvature file "
        "(16-bit grey; flat grey where no curvature master is), after the bake when one is ticked")
    samples: bpy.props.IntProperty(name="Samples", default=256, min=1, soft_max=1024,
                                   description="Cycles samples per master pixel")
    baker: bpy.props.EnumProperty(name="Baker", items=BAKERS, default='AUTO',
                                  description="What bakes the AO masters. A master baked by the other baker is not "
                                  "stale; Bake Selected bakes it again")
    optix_samples: bpy.props.IntProperty(name="Samples", default=4096, min=1, soft_max=16384,
                                         description="FSS OptiX samples per master pixel")
    sample_quality: bpy.props.EnumProperty(name="Quality", default='SPLIT', items=[
        ('SPLIT', 'Split Samples', "Views that are averaged (a moving object's poses, a shared mesh's copies) share "
         "the samples, so the average is about as clean as one bake and costs about as much (each view at least 4)"),
        ('FULL', 'Full Quality', "Every pose and copy is baked with all the samples: less noise, as many times slower "
         "as there are views")],
        description="How the samples are spent when a master averages several views")
    device: bpy.props.EnumProperty(name="Device", items=DEVICES, default='CPU')
    threads: bpy.props.IntProperty(name="Threads", default=0, min=0, max=1024, soft_max=64,
                                   description="CPU threads of the bake and of Apply. 0: Auto, half of this PC's "
                                               "logical processors, at least 2; a number above this PC's logical "
                                               "processors uses them all")
    padding: bpy.props.IntProperty(name="Padding", default=8, min=0, max=64, subtype='PIXEL',
                                   description="Pixels written around each island by Apply, in the AO")
    curv_padding: bpy.props.IntProperty(name="Padding", default=8, min=0, max=64, subtype='PIXEL',
                                        description="Pixels written around each island by Apply, in the curvature "
                                        "map")
    soften_edges: bpy.props.BoolProperty(
        name="Soften Sharp Edges", default=False,
        description="Apply treats convex sharp edges (a lip, a rim; faces more than 30 degrees apart) as slightly "
        "rounded: the darker side brightens toward the brighter side's value at the edge, the brighter side keeps its "
        "AO. Inside corners keep their contact shadow. The masters are not changed")
    soften_width: bpy.props.FloatProperty(
        name="Width", default=0.0003, min=0.0, soft_max=0.005, unit='LENGTH', precision=2,
        description="How far from the edge the darker side brightens; at least one texel of the texture, so a narrow "
        "width still hides the one-texel step")
    output_folder: bpy.props.StringProperty(name="Output Folder", default='', subtype='DIR_PATH',
                                            description="Where Apply writes separate AO files. Empty: a folder "
                                            "<blend name>_ao beside the .blend")
    curv_output_folder: bpy.props.StringProperty(
        name="Output Folder", subtype='DIR_PATH', get=_get_curv_folder, set=_set_curv_folder,
        description="Where Apply writes the curvature files; cleared, it goes back to the AO's Output Folder")
    poses: bpy.props.IntProperty(name="Default Poses", default=5, min=1, max=64,
                                 description="An object with something moving against it (it moves, or a part "
                                 "near it does) is baked in this many poses spread evenly over that animation and "
                                 "averaged, so a shadow that only one pose has does not stay. 1: the current frame "
                                 "only. An object can override it")
    occluders: bpy.props.EnumProperty(name="Default Occluders", default='SCENE', items=[
        ('SCENE', 'Scene Rule', 'Every visible mesh near the object darkens it (not Non-AO-Occluder or Invisible '
         'objects). Parts that move with it darken it as placed; parts that move against it darken it in each pose'),
        ('SELF', 'Self Only', 'Each object darkens only itself')],
        description="What darkens an object; an object can override it")
    shared_combine: bpy.props.EnumProperty(name="Shared Meshes", default='AVERAGE', items=[
        ('AVERAGE', 'Average', "Each copy is baked in its own surroundings and the copies are averaged: a shadow all "
         "copies have (the panel under a knob) shows fully, one copy's neighbour only faintly"),
        ('LIGHTEST', 'Most Lit', "Each pixel takes its lightest copy: only shadows every copy has"),
        ('DARKEST', 'Darkest', "Each pixel takes its darkest copy: every copy's shadows, also one copy's neighbour"),
        ('ONE', 'One Instance', "Only one copy is baked, in its own surroundings, and all copies use it: the copy "
         "selected when it is baked (with several selected, the one the drop-down names), kept until a bake of "
         "another selected copy; never baked, its first copy by name")],
        description="How the copies of a mesh shared by several objects are combined into its one AO; a mesh can "
        "override it")
    run_mode: bpy.props.EnumProperty(name="Run In", default='HIDDEN', items=[
        ('HIDDEN', 'Background', 'The second Blender bakes in the background, without a window'),
        ('VISIBLE', 'Foreground', "With FSS OptiX, FSS OptiX's window shows the bake and a preview of the master, "
         'and the second Blender runs in the background; with Cycles, the second Blender opens a window')],
        description="How the bake runs; this panel shows the progress in both")


OBJECT_OCCLUDERS = [
    ('DEFAULT', 'Default', "The scene's Default Occluders"),
    ('SCENE', 'Scene Rule', 'Every visible static mesh near the object darkens it'),
    ('SELF', 'Self Only', 'Only the object itself'),
    ('CUSTOM', 'Custom', 'The scene rule (Scene as occluder) or nothing, minus the ignored objects of the list below, '
     'plus its added ones; posed with this object when it moves')]
SCENE_OCCLUDER_NAMES = {'SCENE': 'Scene Rule', 'SELF': 'Self Only'}
_occluder_items = []  # Blender keeps no reference to a dynamic enum's strings: kept here


def object_occluder_items(self, context):
    """The object's occluder choices; Default names the scene's Default Occluders (values as the static list had)."""
    scene = getattr(context, 'scene', None) if context is not None else None
    default = SCENE_OCCLUDER_NAMES.get(scene.fss_ao_bake.occluders, 'Scene Rule') if scene is not None else 'Scene Rule'
    items = [(k, f'Default ({default})' if k == 'DEFAULT' else name, desc, i)
             for i, (k, name, desc) in enumerate(OBJECT_OCCLUDERS)]
    _occluder_items[:] = items
    return items


_pose_items = []  # Blender keeps no reference to a dynamic enum's strings: kept here


def pose_mode_items(self, context):
    """A moving object's pose choices; Default names the scene's Default Poses."""
    scene = getattr(context, 'scene', None) if context is not None else None
    n = int(scene.fss_ao_bake.poses) if scene is not None else 5
    items = [('DEFAULT', f'Default ({n})', "The scene's Default Poses", 0),
             ('MANUAL', 'Manual', "This object's own number of poses", 1)]
    _pose_items[:] = items
    return items


def _get_pose_mode(self):
    return 1 if self.poses > 0 else 0


def _set_pose_mode(self, value):
    if not value:
        self.poses = 0
    elif self.poses <= 0:
        self.poses = int(bpy.context.scene.fss_ao_bake.poses)


SHARED_COMBINE_NAMES = {'AVERAGE': 'Average', 'LIGHTEST': 'Most Lit', 'DARKEST': 'Darkest',
                        'ONE': 'One Instance'}
_combine_items = []  # Blender keeps no reference to a dynamic enum's strings: kept here


def mesh_combine_items(self, context):
    """Decision 47: the shared mesh's choices; Default names the scene's."""
    scene = getattr(context, 'scene', None) if context is not None else None
    default = SHARED_COMBINE_NAMES.get(scene.fss_ao_bake.shared_combine, 'Average') if scene is not None else 'Average'
    items = [('DEFAULT', f'Default ({default})', "The scene's Shared Meshes setting", 0)]
    items += [(k, n, '', i + 1) for i, (k, n) in enumerate(SHARED_COMBINE_NAMES.items())]
    _combine_items[:] = items
    return items


def _is_copy(self, obj):
    return obj.type == 'MESH' and obj.data is self.id_data


def selected_copies(context, mesh):
    """Decision 77: the names of the selected copies of this mesh that a bake bakes (sorted)."""
    scene, view_layer = context.scene, context.view_layer
    return sorted(o.name for o in getattr(context, 'selected_objects', None) or ()
                  if o.data is mesh and store.bakeable_copy(o, view_layer, scene))


def bake_copy_choice(context, mesh, names=None):
    """Decision 77: the copy a bake of the selection bakes for this One Instance mesh (its name), or None."""
    names = selected_copies(context, mesh) if names is None else names
    active = getattr(context, 'active_object', None)
    return store.instance_choice(names, active.name if active is not None else None,
                                 mesh.fss_ao_shared.bake_copy_name)


def bake_instances(context):
    """Decision 77: {mesh name: object name}, the copy a bake of the selection bakes for each One Instance mesh with
    a selected copy."""
    scene = context.scene
    out = {}
    meshes = {o.data for o in getattr(context, 'selected_objects', None) or () if o.type == 'MESH'}
    for me in meshes:
        if store.shared_combine(me, scene) == 'ONE':  # refresh uses it only for a mesh with several copies
            choice = bake_copy_choice(context, me)
            if choice:
                out[me.name] = choice
    return out


_copy_items = []  # Blender keeps no reference to a dynamic enum's strings: kept here


def bake_copy_items(self, context):
    """Decision 77: the drop-down's choices, the mesh's selected copies by name."""
    context = context if context is not None else bpy.context
    items = [(n, n, f'Bake Selected bakes {n} for every copy of the mesh', i)
             for i, n in enumerate(selected_copies(context, self.id_data))]
    _copy_items[:] = items
    return items


def _get_bake_copy(self):
    names = selected_copies(bpy.context, self.id_data)
    choice = bake_copy_choice(bpy.context, self.id_data, names)
    return names.index(choice) if choice in names else 0


def _set_bake_copy(self, value):
    names = selected_copies(bpy.context, self.id_data)
    if 0 <= value < len(names):
        self.bake_copy_name = names[value]


class FSS_AOMeshSettings(bpy.types.PropertyGroup):
    """Decision 47: a shared mesh's override, on the mesh (one master for all its copies, so one choice)."""
    combine: bpy.props.EnumProperty(name="Copies", items=mesh_combine_items, default=0,
                                    description="How this shared mesh's copies are combined into its one AO")
    instance: bpy.props.PointerProperty(type=bpy.types.Object, name="Copy", poll=_is_copy,
                                        description="Decision 48's picked copy, no longer shown (decision 77): read "
                                        "only for a One Instance master baked before decision 77, whose index entry "
                                        "does not name its copy")
    bake_copy_name: bpy.props.StringProperty(name="Copy to Bake", options={'HIDDEN'},
                                             description="Decision 77: the drop-down's copy, by name")
    bake_copy: bpy.props.EnumProperty(name="Copy to Bake", items=bake_copy_items, get=_get_bake_copy,
                                      set=_set_bake_copy,
                                      description="One Instance with several copies selected: the copy Bake Selected "
                                      "bakes, in its own surroundings, for every copy of the mesh")


class FSS_AOOccluderRef(bpy.types.PropertyGroup):
    object: bpy.props.PointerProperty(type=bpy.types.Object, name="Object")
    ignore: bpy.props.BoolProperty(name="Ignore", default=False,
                                   description="Decision 60: on, this object never darkens the object; off, it is "
                                   "added to what darkens it")
    children: bpy.props.BoolProperty(name="With its children", default=False,
                                     description="Decision 63: the item also covers this object's children at every "
                                     "depth, as the hierarchy is now (an item on a child wins)")


def _listable(obj):
    """Decision 63: a mesh, or a parent (its item then covers its children)."""
    return obj.type == 'MESH' or bool(obj.children)


def _is_pickable(self, obj):
    return _listable(obj) and obj is not self.id_data


def _add_ref(settings, obj):
    ref = settings.custom.add()
    ref.object = obj
    ref.children = obj.type != 'MESH'  # an empty or other parent stands for its children
    return ref


def _pick_update(self, context):
    """Decision 60: the eyedropper field adds the picked object to the list (as Add) and empties itself."""
    obj = self.pick
    if obj is None:
        return
    if obj is not self.id_data and all(r.object is not obj for r in self.custom):
        _add_ref(self, obj)
        self.custom_index = len(self.custom) - 1
    self.pick = None


class FSS_AOObjectSettings(bpy.types.PropertyGroup):
    """Per-object overrides of the bake (decisions 34 and 35); `fss_` on the object, so the glTF extras drop them."""
    poses: bpy.props.IntProperty(name="Poses", default=0, min=0, max=64,
                                 description="This object's pose count when something moves against it. 0: the "
                                 "scene's Default Poses")
    pose_mode: bpy.props.EnumProperty(name="Poses", get=_get_pose_mode, set=_set_pose_mode, items=pose_mode_items,
        description="How many poses this object is baked in (something moves against it)")
    occluders: bpy.props.EnumProperty(name="Occluders", items=object_occluder_items, default=0,
                                      description="What darkens this object")
    custom: bpy.props.CollectionProperty(type=FSS_AOOccluderRef)
    custom_index: bpy.props.IntProperty()
    custom_scene: bpy.props.BoolProperty(
        name="Scene as occluder", default=False,
        description="Decision 60: on, the scene rule darkens the object (every visible mesh near it), minus the "
        "list's ignored objects, plus its added ones; off, only the list's added objects")
    pick: bpy.props.PointerProperty(type=bpy.types.Object, name="Add", poll=_is_pickable, update=_pick_update,
                                    description="Pick an object (eyedropper or name) to add it to the list without "
                                    "changing the selection")


def _get_curv_file_name(self):
    """The set's curvature file name, else <material>_curvature.png (stored empty, it follows a rename)."""
    return self.get('curv_file_name', '') or apply_mod.default_curvature_name(self.id_data)


def _set_curv_file_name(self, value):
    value = value.strip()
    self['curv_file_name'] = '' if value == apply_mod.default_curvature_name(self.id_data) else value


def _get_file_name(self):
    """The set's own name, else <material>_ao.png (shown in the box; stored empty, it follows a rename)."""
    return self.get('file_name', '') or apply_mod.default_file_name(self.id_data)


def _set_file_name(self, value):
    value = value.strip()
    self['file_name'] = '' if value == apply_mod.default_file_name(self.id_data) else value


class FSS_AOApplySettings(bpy.types.PropertyGroup):
    use: bpy.props.BoolProperty(name="Apply", default=True,
                                description="Apply Selected writes this texture set (unticked: it is left as it is)")
    target: bpy.props.EnumProperty(name="Target", default='FILE', items=[
        ('FILE', 'Separate File', 'A file of its own in the output folder'),
        ('ORM', 'ORM Texture', "The red channel of the texture in the material's ORM slot; green and blue stay")])
    file_name: bpy.props.StringProperty(name="File", get=_get_file_name, set=_set_file_name,
                                        description="The file's name in the output folder; cleared, it goes back to "
                                        "<material>_ao.png")
    resolution: bpy.props.EnumProperty(name="Resolution", items=resolution_items, get=_get_resolution,
                                       set=_set_resolution, description="A new AO file's size (an existing file "
                                       "keeps its own)")
    curv_file_name: bpy.props.StringProperty(name="File", get=_get_curv_file_name, set=_set_curv_file_name,
                                             description="The curvature file's name in its output folder; cleared, "
                                             "it goes back to <material>_curvature.png")
    curv_resolution: bpy.props.EnumProperty(name="Resolution", items=resolution_items, get=_get_curv_resolution,
                                            set=_set_curv_resolution, description="A new curvature file's size (an "
                                            "existing file keeps its own)")
    layout: bpy.props.EnumProperty(name="Channels", default='GREY', items=[
        ('GREY', 'Greyscale', 'The AO in red, green and blue'),
        ('ORM', 'Red (ORM)', 'The AO in red, as in an ORM texture; green and blue as chosen')])
    green_blue: bpy.props.EnumProperty(name="Green and Blue", default='WHITE', items=[
        ('WHITE', 'White', 'Empty: MSFS then uses the material\'s roughness and metallic factors'),
        ('COPY', 'From ORM Texture', "Roughness and metallic taken from the texture in the material's ORM slot")])
    sampling: bpy.props.EnumProperty(name="Sampling", default='AUTOMATIC', items=[
        ('AUTOMATIC', 'Automatic', 'The mean of the covered pixels when smaller, bilinear when larger'),
        ('NEAREST', 'Nearest', 'No in-between values: hard metallic edges stay hard'),
        ('BICUBIC', 'Bicubic', 'A sharper enlargement; may overshoot slightly at hard edges (clamped)')])


class FSS_AOSetRow(bpy.types.PropertyGroup):
    material: bpy.props.StringProperty()
    state: bpy.props.StringProperty()
    warn: bpy.props.BoolProperty()
    n_missing: bpy.props.IntProperty()
    n_stale: bpy.props.IntProperty()  # mesh or surroundings changed
    n_total: bpy.props.IntProperty()


class FSS_AOBakeState(bpy.types.PropertyGroup):
    """What the panel shows (written by Refresh, the bake's status and Apply; never while drawing)."""
    refreshed: bpy.props.BoolProperty()
    up_to_date: bpy.props.IntProperty()
    surroundings: bpy.props.IntProperty()
    mesh: bpy.props.IntProperty()
    missing: bpy.props.IntProperty()
    excluded: bpy.props.IntProperty()
    index_masters: bpy.props.IntProperty()
    cm_up_to_date: bpy.props.IntProperty()  # decision 55: the curvature masters' state
    cm_width: bpy.props.IntProperty()
    cm_missing: bpy.props.IntProperty()
    cm_needs_ao: bpy.props.IntProperty()
    dn_up_to_date: bpy.props.IntProperty()  # decision 56: the denoise state
    dn_stale: bpy.props.IntProperty()
    dn_needs_ao: bpy.props.IntProperty()
    phase: bpy.props.StringProperty()  # the runner's step after the rays (Denoising)
    running: bpy.props.BoolProperty()
    n_done: bpy.props.IntProperty()
    progress: bpy.props.FloatProperty()  # the bake's share done: objects, and the current one's tiles and views
    n_total: bpy.props.IntProperty()
    tile: bpy.props.IntProperty()
    n_tiles: bpy.props.IntProperty()
    pose: bpy.props.IntProperty()
    n_poses: bpy.props.IntProperty()
    copy: bpy.props.IntProperty()  # decision 47: the copy and its pose being baked
    n_copies: bpy.props.IntProperty()
    copy_name: bpy.props.StringProperty()
    copy_pose: bpy.props.IntProperty()
    copy_poses: bpy.props.IntProperty()
    current: bpy.props.StringProperty()
    elapsed: bpy.props.FloatProperty()
    left: bpy.props.FloatProperty(default=-1.0)
    report: bpy.props.StringProperty()
    apply_report: bpy.props.StringProperty()
    applying: bpy.props.BoolProperty()  # decision 45: Apply in steps, with progress
    apply_set: bpy.props.IntProperty()
    apply_sets: bpy.props.IntProperty()
    apply_material: bpy.props.StringProperty()
    apply_what: bpy.props.StringProperty()
    apply_factor: bpy.props.FloatProperty()
    apply_elapsed: bpy.props.FloatProperty()
    sets: bpy.props.CollectionProperty(type=FSS_AOSetRow)
    active_set: bpy.props.IntProperty()
    detected_index: bpy.props.IntProperty(default=-1)  # decision 62: the highlighted row of the Detected list
    detected_view: bpy.props.EnumProperty(  # decision 70
        name='View', items=[('TREE', 'Tree', 'The detected objects with their parents', 'OUTLINER', 0),
                            ('FLAT', 'Flat', 'The detected objects alone', 'ALIGN_JUSTIFY', 1)])
    detected_sort: bpy.props.EnumProperty(  # decision 71
        name='Sort', items=[('NAME', 'By Name', 'Sort the rows by name', 'SORTALPHA', 0),
                            ('DISTANCE', 'By Distance', 'Sort the rows nearest first (a parent row: by the nearest in '
                             'its branch), then by name', 'DRIVER_DISTANCE', 1)])


def _state(context=None):
    return (context or bpy.context).window_manager.fss_ao_bake_state


def sync_state(context):
    """Copies the store's last refresh into the window manager's state for drawing."""
    st = _state(context)
    c = store.counts()
    st.refreshed = store._state['refreshed'] is not None
    st.up_to_date, st.surroundings, st.mesh, st.missing, st.excluded = (
        c['UP_TO_DATE'], c['SURROUNDINGS'], c['MESH'], c['MISSING'], c['EXCLUDED'])
    cc = store.curv_counts()
    st.cm_up_to_date, st.cm_width, st.cm_missing, st.cm_needs_ao = (
        cc['UP_TO_DATE'], cc['WIDTH'], cc['MISSING'], cc['NEEDS_AO'])
    dc = store.dn_counts()
    st.dn_up_to_date, st.dn_stale, st.dn_needs_ao = dc['UP_TO_DATE'], dc['STALE'], dc['NEEDS_AO']
    active = st.sets[st.active_set].material if 0 <= st.active_set < len(st.sets) else ''
    st.sets.clear()
    for name, row in sorted(store._state['sets'].items()):
        r = st.sets.add()
        r.material = name
        bad = row['MISSING'] + row['MESH']
        parts = []
        if bad:
            parts.append(f"{row['MISSING']} missing" if row['MISSING'] else '')
            parts.append(f"{row['MESH']} mesh changed" if row['MESH'] else '')
        if row['SURROUNDINGS']:
            parts.append(f"{row['SURROUNDINGS']} stale")
        parts = [p for p in parts if p]
        r.state = ', '.join(parts) if parts else f"{len(row['items'])} complete"
        r.warn = bool(parts)
        r.n_missing, r.n_stale, r.n_total = row['MISSING'], row['MESH'] + row['SURROUNDINGS'], len(row['items'])
    for i, r in enumerate(st.sets):
        if r.material == active:
            st.active_set = i


def read_index_on_open():
    st = _state()
    folder = store.bake_folder()
    st.index_masters = len(store.read_index(folder).get('masters', {})) if folder else 0


# ---------------------------------------------------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------------------------------------------------

def ao_unavailable():
    """Apply-native-copy decision 6: why the AO Bake cannot run here (fss_ao_copy.dll or libjxl not loaded), on one
    line, or None."""
    return store.core.native_copy().unavailable()


def _available(cls):
    """For the polls of the AO Bake operators (decision 6; not Cancel): False, the reason as the poll's message, when
    the AO Bake cannot run here (the button greyed, its tooltip saying why)."""
    why = ao_unavailable()
    if why:
        cls.poll_message_set(f'AO Bake not available: {why}')
        return False
    return True


class FSS_OT_AOBakeRefresh(bpy.types.Operator):
    bl_idname = 'fss.ao_bake_refresh'
    bl_label = 'Refresh'
    bl_description = "Compute the masters' hashes and states against the bake folder (links renamed objects again)"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        if not _available(cls):
            return False
        return context.mode == 'OBJECT'

    def execute(self, context):
        t = time.time()
        state = store.refresh(context)
        sync_state(context)
        read_index_on_open()
        msg = f"AO Bake: {len(state['items'])} masters checked in {time.time() - t:.1f} s"
        if state.get('relinked'):
            msg += f"; linked again: {', '.join(f'{a} -> {b}' for a, b in state['relinked'])}"
        self.report({'INFO'}, msg)
        return {'FINISHED'}


def _poll_timer():
    st = _state()
    status = store.read_status()
    if status:
        st.n_done = status.get('n_done', 0)
        st.progress = status.get('progress', 0.0) or 0.0
        st.n_total = status.get('n_total', 0)
        st.current = status.get('current', '')
        st.elapsed = status.get('elapsed_s', 0.0)
        st.left = status.get('left_s') if status.get('left_s') is not None else -1.0
        st.tile = status.get('tile', 0) or 0
        st.n_tiles = status.get('n_tiles', 0) or 0
        st.phase = status.get('phase', '') or ''
        st.pose = status.get('pose', 0) or 0
        st.n_poses = status.get('n_poses', 0) or 0
        st.copy = status.get('copy', 0) or 0
        st.n_copies = status.get('n_copies', 0) or 0
        st.copy_name = status.get('copy_name', '') or ''
        st.copy_pose = status.get('copy_pose', 0) or 0
        st.copy_poses = status.get('copy_poses', 0) or 0
    if store.running():
        _redraw(sidebar_only=True)
        return 0.5
    finish_bake()
    return None


def excluded_lines(limit=8):
    """The objects the last Refresh excluded, per reason (decision 30: also those without a face of a texture set)."""
    by = {}
    for name, why in sorted(store._state.get('excluded', {}).items()):
        by.setdefault(why, []).append(name)
    lines = []
    for why, names in sorted(by.items()):
        more = f' and {len(names) - limit} more' if len(names) > limit else ''
        lines.append(f"excluded ({why}): {len(names)}: {', '.join(names[:limit])}{more}")
        for name in names:
            print(f'AO Bake: excluded {name} ({why})')
    return lines


def finish_bake():
    st = _state()
    status = store.finish_run() or {}
    st.running = False
    results = status.get('results', [])
    by = {}
    for r in results:
        by.setdefault(r['status'], []).append(r)
    lines = [f"{status.get('state', 'ended')}: {status.get('n_done', 0)} of {status.get('n_total', 0)} in "
             f"{status.get('elapsed_s', 0)} s; baked {len(by.get('baked', []))}"
             + (f", updated without rays {len(by['updated'])}" if by.get('updated') else '')]
    if status.get('baker'):  # OptiX baker decision 22: the baker, and why Cycles when FSS OptiX was asked for
        n_by = {}
        for r in by.get('baked', []):
            n_by[r.get('baker') or 'Cycles'] = n_by.get(r.get('baker') or 'Cycles', 0) + 1
        lines.append('baked by ' + (', '.join(f'{k} {v}' for k, v in n_by.items()) or status['baker'])
                     + (f"; Cycles because {status['baker_why']}" if status.get('baker_why') else ''))
    for kind in ('skipped', 'failed', 'cancelled'):
        for r in by.get(kind, []):
            lines.append(f"{kind}: {r['name']} ({r.get('reason', '')})")
    for r in by.get('baked', []):  # decision 34: a mover not baked in its poses, and why
        if r.get('note'):
            lines.append(f"{r['name']}: {r['note']}")
    lines += excluded_lines()
    for line in lines:  # decision 74: the whole report in the console; the panel one line, and what failed
        print('AO Bake:', line)
    shown = [f"{status.get('state', 'ended')} {status.get('n_done', 0)} of {status.get('n_total', 0)}, in "
             f"{float(status.get('elapsed_s', 0) or 0):.1f} s, {time.strftime('%Y-%m-%d %H:%M')}"]
    shown += [f"failed: {r['name']} ({r.get('reason', '')})" for r in by.get('failed', [])]
    st.report = '\n'.join(shown)
    sync_state(bpy.context)
    read_index_on_open()
    _redraw()
    if _run_next['objects'] is not None:  # decision 75: Run's apply after its bake (not after a cancelled one)
        if status.get('state') == 'cancelled':
            _run_next['objects'] = None
        elif bpy.app.background:
            _start_queued_apply()
        else:
            bpy.app.timers.register(_start_queued_apply, first_interval=0.1)


_run_next = dict(objects=None)  # decision 75: the objects Run applies once its bake has finished (names)


def _start_queued_apply():
    """Decision 75: Run's apply, on the objects selected when Run was pressed."""
    names = _run_next['objects']
    _run_next['objects'] = None
    if names is None:
        return None
    objs = [o for o in (bpy.data.objects.get(n) for n in names) if o is not None]
    wm = bpy.context.window_manager
    window = wm.windows[0] if getattr(wm, 'windows', None) else None
    with bpy.context.temp_override(window=window, selected_objects=objs):
        bpy.ops.fss.ao_apply('INVOKE_DEFAULT' if window is not None else 'EXEC_DEFAULT', scope='SELECTED')
    return None


def run_problems(context):
    """Decision 75: why Run cannot start, as short lines (empty: it can)."""
    s = context.scene.fss_ao_bake
    lines = []
    if not (s.bake_ao or s.curvature or s.apply_ao or s.apply_cm):
        lines.append('Tick what to run')
    if not context.selected_objects:
        lines.append('Select the objects to run')
    if (s.apply_ao or s.apply_cm) and context.selected_objects and store._state['refreshed'] is not None:
        ticked, blocked = apply_check(context)
        if not ticked:
            lines.append("None of the selection's texture sets is ticked")
        lines += [f'{name}: {problem}' for name, problem in blocked]
    return lines


class FSS_OT_AORun(bpy.types.Operator):
    bl_idname = 'fss.ao_run'
    bl_label = 'Run'
    bl_description = ("Run what is ticked for the selected objects: the bake (AO, CM) in a second Blender, then, "
                      "when it has finished, the apply into their texture sets")
    bl_options = {'REGISTER'}

    hidden: bpy.props.BoolProperty(default=False, options={'HIDDEN', 'SKIP_SAVE'})  # tests: hidden, whatever the run mode
    wait: bpy.props.BoolProperty(default=False, options={'HIDDEN', 'SKIP_SAVE'})  # tests: return when done

    @classmethod
    def poll(cls, context):
        if not _available(cls):
            return False
        return (context.mode == 'OBJECT' and bool(bpy.data.filepath) and not store.running()
                and _apply_run['gen'] is None)

    def execute(self, context):
        s = context.scene.fss_ao_bake
        bake, apply = s.bake_ao or s.curvature, s.apply_ao or s.apply_cm
        if apply and store._state['refreshed'] is None:
            store.refresh(context)
            sync_state(context)
        problems = run_problems(context)
        if problems:
            self.report({'WARNING'}, 'AO Run: ' + '; '.join(problems))
            return {'CANCELLED'}
        names = [o.name for o in context.selected_objects]
        _run_next['objects'] = names if apply else None
        if bake:
            got = bpy.ops.fss.ao_bake_start(scope='AUTO', hidden=self.hidden, wait=self.wait)
            if got == {'FINISHED'} and (store.running() or self.wait):
                return {'FINISHED'}  # the apply starts when the bake has finished
        if apply:  # no bake, or nothing to bake
            _run_next['objects'] = None
            with context.temp_override(selected_objects=[bpy.data.objects[n] for n in names]):
                bpy.ops.fss.ao_apply('INVOKE_DEFAULT' if context.window is not None and not self.wait
                                     else 'EXEC_DEFAULT', scope='SELECTED')
        return {'FINISHED'}


def _selected_meshes(context):
    return sorted((o for o in getattr(context, 'selected_objects', None) or () if o.type == 'MESH'),
                  key=lambda o: o.name)


class FSS_OT_AOObjectStep(bpy.types.Operator):
    bl_idname = 'fss.ao_object_step'
    bl_label = 'Next Object'
    bl_description = 'Make the previous or next selected object the active one; the selection stays as it is'
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    step: bpy.props.IntProperty(default=1, options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return _available(cls)

    def execute(self, context):
        objs = _selected_meshes(context)
        if not objs:
            return {'CANCELLED'}
        names = [o.name for o in objs]
        active = context.view_layer.objects.active
        i = names.index(active.name) + self.step if active is not None and active.name in names else 0
        context.view_layer.objects.active = objs[i % len(objs)]
        return {'FINISHED'}


class FSS_OT_AOBakeStart(bpy.types.Operator):
    bl_idname = 'fss.ao_bake_start'
    bl_label = 'Bake'
    bl_description = ("Bake masters in a second Blender on a snapshot of the current state (unsaved changes "
                      "included); this Blender, its scene and the .blend on disk are not touched")
    bl_options = {'REGISTER'}

    scope: bpy.props.EnumProperty(items=[
        ('AUTO', 'Selected', "The selected objects: of each, what is missing or stale (the denoise alone re-run from "
         "its raw bake, without rays); an object that is up to date is baked again in full"),
        ('STALE', 'Missing and Stale', ''), ('SELECTED', 'Selected, All', '')], default='AUTO')
    hidden: bpy.props.BoolProperty(default=False, options={'HIDDEN', 'SKIP_SAVE'})  # tests: hidden, whatever the run mode
    wait: bpy.props.BoolProperty(default=False, options={'HIDDEN', 'SKIP_SAVE'})  # tests: return when done
    test_delay: bpy.props.FloatProperty(default=0.0, options={'HIDDEN', 'SKIP_SAVE'})  # tests: pause per object
    test_tile_delay: bpy.props.FloatProperty(default=0.0, options={'HIDDEN', 'SKIP_SAVE'})  # tests: pause per tile
    tile: bpy.props.IntProperty(default=0, min=0, options={'HIDDEN', 'SKIP_SAVE'})  # tests: force the tile size

    @classmethod
    def poll(cls, context):
        if not _available(cls):
            return False
        return (context.mode == 'OBJECT' and bool(bpy.data.filepath) and not store.running()
                and _apply_run['gen'] is None)

    def execute(self, context):
        # decision 77: a bake of the selection bakes a One Instance mesh's selected copy; Missing and Stale keeps the
        # copy each master was baked from
        store.refresh(context, instances=bake_instances(context) if self.scope in ('AUTO', 'SELECTED') else None)
        sync_state(context)
        items = store._state['items']
        s = context.scene.fss_ao_bake
        if not (s.bake_ao or s.curvature):
            self.report({'WARNING'}, 'AO Bake: tick AO, CM or both')
            return {'CANCELLED'}
        dn_opts = store.denoise_opts(context.scene)
        if self.scope == 'AUTO':
            what, needs_ao = store.bake_auto(store.items_for_objects(context.selected_objects), s.bake_ao,
                                             s.curvature, dn_opts)
        else:
            sel = self.scope == 'SELECTED'
            cands = (store.items_for_objects(context.selected_objects) if sel else
                     [st for st, it in sorted(items.items(), key=lambda kv: kv[1]['name'])])
            what, needs_ao = store.bake_choice(cands, s.bake_ao, s.curvature, sel, dn_opts)
        stems = list(what)
        if needs_ao:
            self.report({'WARNING'}, f'AO Bake: {len(needs_ao)} object(s) need an AO bake before their curvature '
                        f'(no AO master, or its mesh changed): ' + ', '.join(needs_ao[:5])
                        + (' ...' if len(needs_ao) > 5 else ''))
        if not stems:
            if not needs_ao:
                self.report({'INFO'}, 'AO Bake: nothing to bake')
            return {'CANCELLED'}
        visible = not (self.hidden or s.run_mode == 'HIDDEN')  # decision 36
        # OptiX baker decision 28: Foreground with FSS OptiX shows its window, the second Blender in the background
        baker_window = visible and s.baker != 'CYCLES' and native.available()[0]
        job = store.make_job(context, stems, self.test_delay, self.tile, self.test_tile_delay, what=what,
                             baker_window=baker_window)
        proc = store.start_bake(job, hidden=not visible or baker_window)
        st = _state(context)
        st.running, st.n_done, st.n_total, st.current, st.report = True, 0, len(stems), '', ''
        st.progress = 0.0
        st.tile = st.n_tiles = st.pose = st.n_poses = st.copy = st.n_copies = 0
        if self.wait:
            proc.wait()
            finish_bake()
        elif not bpy.app.timers.is_registered(_poll_timer):
            bpy.app.timers.register(_poll_timer, first_interval=0.5)
        self.report({'INFO'}, f'AO Bake: {len(stems)} masters in a second Blender')
        return {'FINISHED'}


class FSS_OT_AOBakeCancel(bpy.types.Operator):
    bl_idname = 'fss.ao_bake_cancel'
    bl_label = 'Cancel'
    bl_description = ('Stop the bake after the current tile; the finished masters are kept, the object being baked '
                      'keeps its old master')
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return store.running()

    def execute(self, context):
        store.cancel()
        return {'FINISHED'}


class FSS_OT_AOBakeSelect(bpy.types.Operator):
    bl_idname = 'fss.ao_bake_select'
    bl_label = 'Select'
    bl_description = 'Select the objects whose master is in this state (from the last Refresh)'
    bl_options = {'REGISTER', 'UNDO'}

    which: bpy.props.EnumProperty(items=[
        ('OUTDATED', 'Missing and Stale', "Select the objects with something to bake for the ticked AO and CM: a "
         "missing or stale master, a stale denoise or curvature (from the last Refresh)"),
        ('STALE', 'Stale', "Select the objects whose AO master is stale: their mesh or surroundings changed"),
        ('MISSING', 'Missing', "Select the objects without an AO master")], default='OUTDATED')
    material: bpy.props.StringProperty(options={'SKIP_SAVE'})  # only this texture set's objects (the list's buttons)
    @classmethod
    def description(cls, context, props):
        return cls.bl_rna.properties['which'].enum_items[props.which].description or cls.bl_description

    @classmethod
    def poll(cls, context):
        if not _available(cls):
            return False
        return context.mode == 'OBJECT' and store._state['refreshed'] is not None

    def execute(self, context):
        items = store._state['items']
        if self.which == 'OUTDATED':
            s = context.scene.fss_ao_bake
            what, _needs = store.bake_choice(list(items), s.bake_ao, s.curvature, False,
                                             store.denoise_opts(context.scene))
            stems = set(what)
        else:
            grades = {'STALE': ('MESH', 'SURROUNDINGS'), 'MISSING': ('MISSING',)}[self.which]
            stems = {st for st, it in items.items() if it['grade'] in grades}
        if self.material:
            stems &= set(store._state['sets'].get(self.material, {}).get('items', ()))
        names = {n for st in stems for n in items[st]['users']}
        n_sel, hidden = 0, 0
        for obj in context.view_layer.objects:
            want = obj.name in names
            obj.select_set(want)
            if want:
                if obj.select_get():
                    n_sel += 1
                else:
                    hidden += 1
        self.report({'WARNING'} if hidden else {'INFO'},
                    f'{n_sel} objects selected' + (f'; {hidden} hidden, not selected' if hidden else ''))
        return {'FINISHED'}


def _active_mesh(context):
    obj = context.active_object
    return obj if obj is not None and obj.type == 'MESH' else None


def tree_targets(context):
    """Decision 63: the objects the Detected tree is for: the selected meshes when there are several, else the
    active mesh."""
    sel = sorted((o for o in getattr(context, 'selected_objects', None) or () if o.type == 'MESH'),
                 key=lambda o: o.name)
    if len(sel) > 1:
        return sel
    obj = _active_mesh(context)
    return [obj] if obj is not None else []


_tree_cache = dict(key=None, tree=None)
_tree_open = set()  # the unfolded rows (names); panel state only, not saved


def detected_tree(context):
    """Decision 63: the occluders the scene rule detected (last Refresh) for the tree's objects, joined, with their
    parents: dict(targets (names with a Refresh result), missing (names without), rules {target: set}, members {row:
    detected names in its branch}, children {row: sorted child rows}, parent {row: its parent row}, roots, depth {row:
    n}, count {row: number of targets that detect something in its branch}, gap {row: the smallest gap in its branch,
    metres}, own_gap {detected: its gap}, detected (the detected names)). An empty parent is a row only when its
    branch holds two objects or more that are not empties (decision 70); its children move up to the next row above.
    Cached until the targets or the Refresh change."""
    targets = tree_targets(context)
    rules_all = store._state.get('scene_rule', {})
    key = (tuple(o.name for o in targets), store._state.get('rule_gen', 0))
    if _tree_cache['key'] == key:
        return _tree_cache['tree']
    rules = {o.name: set(rules_all[o.name]) for o in targets if o.name in rules_all}
    objects = context.scene.objects
    members, kids, parent, chains = {}, {}, {}, {}
    by_name = {o.name: o for o in objects}  # one pass: objects.get scans every object per call
    for d in sorted(set().union(*rules.values()) if rules else ()):
        o = by_name.get(d)
        if o is None:
            continue
        chain = []
        whole = []  # Session 53: the whole parent chain by name, for the rows' state
        p = o
        while p is not None:
            whole.append(p.name)
            p = p.parent
        chains[d] = whole
        while o is not None:
            chain.append(o.name)
            o = o.parent if o.parent is not None and o.parent.name in by_name else None
        for i, n in enumerate(chain):
            members.setdefault(n, []).append(d)
            if i + 1 < len(chain):
                parent[n] = chain[i + 1]
                kids.setdefault(chain[i + 1], set()).add(n)
    solid = {}  # objects that are not empties in each row's branch, the row not counted

    def count_solid(n):
        if n not in solid:
            solid[n] = sum(count_solid(c) + (by_name[c].type != 'EMPTY') for c in kids.get(n, ()))
        return solid[n]
    shown = {n for n in members if by_name[n].type != 'EMPTY' or count_solid(n) >= 2}
    up = {}  # decision 70: a row's parent among the shown rows
    for n in shown:
        p = parent.get(n)
        while p is not None and p not in shown:
            p = parent.get(p)
        if p is not None:
            up[n] = p
    kids = {}
    for n, p in up.items():
        kids.setdefault(p, set()).add(n)
    members = {n: m for n, m in members.items() if n in shown}
    depth = {}
    for n in members:
        k, p = 0, up.get(n)
        while p is not None:
            k, p = k + 1, up.get(p)
        depth[n] = k
    count = {n: sum(1 for t in rules.values() if not t.isdisjoint(m)) for n, m in members.items()}
    gaps_all = store._state.get('scene_gap') or {}
    own_gap = {}
    for t, rule in rules.items():
        g = gaps_all.get(t) or {}
        for d in rule:
            if d in g:
                own_gap[d] = min(own_gap.get(d, g[d]), g[d])
    gap = {n: min((own_gap[d] for d in m if d in own_gap), default=None) for n, m in members.items()}
    tree = dict(targets=list(rules), missing=[o.name for o in targets if o.name not in rules], rules=rules,
                members=members, children={n: sorted(c) for n, c in kids.items()}, parent=up,
                roots=sorted(n for n in members if n not in up), depth=depth, count=count, gap=gap, own_gap=own_gap,
                chains=chains,
                detected=sorted(set().union(*rules.values()) & set(members)) if rules else [])
    _tree_cache.update(key=key, tree=tree)
    return tree


def tree_rows(tree, filter_name='', flat=False, by_distance=False):
    """Decision 63: the rows shown, in order: depth first by name, a branch only when its row is unfolded; with a
    name filter, the matching rows and their parents, folded or not. Flat (decision 70): the detected objects alone.
    By distance (decision 71): nearest first (a parent row by the nearest in its branch), then by name."""
    inf = float('inf')
    gaps = tree['own_gap'] if flat else tree['gap']

    def order(names):
        if not by_distance:
            return sorted(names)
        return sorted(names, key=lambda n: (inf if gaps.get(n) is None else gaps[n], n))
    if flat:
        pattern = f'*{filter_name.lower()}*'
        return order(n for n in tree['detected'] if not filter_name or fnmatch.fnmatchcase(n.lower(), pattern))
    rows, keep = [], set()
    if filter_name:
        pattern = f'*{filter_name.lower()}*'
        for n in tree['members']:
            if fnmatch.fnmatchcase(n.lower(), pattern):
                p = n
                while p is not None and p not in keep:
                    keep.add(p)
                    p = tree['parent'].get(p)

    def walk(n):
        if filter_name and n not in keep:
            return
        rows.append(n)
        if filter_name or n in _tree_open:
            for c in order(tree['children'].get(n, ())):
                walk(c)
    for r in order(tree['roots']):
        walk(r)
    return rows


def _darkens(target, refs, mode, name, rule, chains):
    """Decision 63: does object `name` (in `rule`, the scene rule's occluders of `target`) darken the target, with
    its occluders setting (`mode`) and Custom list (`refs`); `chains`: the tree's parent chains by name (Session
    53)."""
    if mode == 'SCENE':
        return name in rule
    if mode == 'SELF':
        return False
    chain = chains.get(name)
    state = store.custom_state_chain(refs, chain) if chain else None
    if target.fss_ao_bake.custom_scene:
        return state != 'IGNORE' and (name in rule or state == 'ADD')
    return state == 'ADD'


def row_state(context, tree, name):
    """Decision 63: 'ON' (every detected object of the row's branch darkens each tree object that detects it), 'OFF'
    (none does) or 'MIXED'."""
    on = off = False
    targets = {o.name: o for o in tree_targets(context)}  # Session 53: no lookup by name while drawing
    for t, rule in tree['rules'].items():
        target = targets.get(t)
        if target is None:
            continue
        refs = store.custom_refs(target)
        mode = store.occluder_mode(target, context.scene)
        for d in tree['members'].get(name, ()):
            if d not in rule:
                continue
            hit = _darkens(target, refs, mode, d, rule, tree['chains'])
            on, off = on or hit, off or not hit
            if on and off:
                return 'MIXED'
    return 'ON' if on else 'OFF'


def set_row(context, tree, name, on):
    """Decision 63: make the row's branch darken (on) or not darken each tree object that detects something in it.
    Self Only becomes Custom (on), Scene Rule becomes Custom with Scene as occluder (off); the items inside the branch
    are removed and one item on the row (With its children for a parent row) is added when the parents' items do not
    already give the wanted state. Returns the names of the objects changed."""
    objects = context.scene.objects
    row_obj = objects.get(name)
    if row_obj is None:
        return []
    branch = {name} | {c.name for c in row_obj.children_recursive}
    changed = []
    for t, rule in tree['rules'].items():
        target = objects.get(t)
        if target is None or rule.isdisjoint(tree['members'].get(name, ())):
            continue
        s = target.fss_ao_bake
        mode = store.occluder_mode(target, context.scene)
        if (mode == 'SCENE' and on) or (mode == 'SELF' and not on):
            continue  # already so, whatever its list
        scene_on = True if mode == 'SCENE' else False if mode == 'SELF' else s.custom_scene
        kept = [(r.object.name, r.ignore, r.children) for r in s.custom
                if r.object is not None and r.object.name not in branch]
        refs = {}
        for n, ignore, children in kept:
            was = refs.get(n, (False, False))
            refs[n] = (was[0] or ignore, was[1] or children)
        state = store.custom_state(refs, row_obj)
        add = (state != 'IGNORE' if scene_on else state == 'ADD') != on
        before = [(r.object.name, r.ignore, r.children) for r in s.custom if r.object is not None]
        after = kept + ([(name, not on, bool(tree['children'].get(name)))] if add else [])
        if mode == 'CUSTOM' and sorted(after) == sorted(before):
            continue  # already so: its list stays as it is
        if mode != 'CUSTOM':
            s.occluders, s.custom_scene = 'CUSTOM', scene_on
        for i in reversed(range(len(s.custom))):
            if s.custom[i].object is not None and s.custom[i].object.name in branch:
                s.custom.remove(i)
        if add:
            ref = s.custom.add()
            ref.object, ref.ignore = row_obj, not on
            ref.children = bool(tree['children'].get(name))
        s.custom_index = min(max(s.custom_index, 0), len(s.custom) - 1)
        changed.append(t)
    return changed


class FSS_OT_AOTreeSet(bpy.types.Operator):
    bl_idname = 'fss.ao_bake_tree_set'
    bl_label = 'Darkens or Not'
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    name: bpy.props.StringProperty(options={'SKIP_SAVE'})
    on: bpy.props.BoolProperty(options={'SKIP_SAVE'})

    @classmethod
    def description(cls, context, properties):
        if properties.on:
            return ('It darkens the object(s) that detect it: Self Only becomes Custom with it added; with Custom, '
                    'it is added (a parent row: with its children)')
        return ('It never darkens the object(s) that detect it: Scene Rule becomes Custom with Scene as occluder and '
                'it ignored; with Custom, it is ignored (a parent row: with its children)')

    @classmethod
    def poll(cls, context):
        if not _available(cls):
            return False
        return context.mode == 'OBJECT'

    def execute(self, context):
        changed = set_row(context, detected_tree(context), self.name, self.on)
        if not changed:
            return {'CANCELLED'}
        what = 'darkens' if self.on else 'ignored for'
        self.report({'INFO'}, f"{self.name} {what} {', '.join(changed)}")
        return {'FINISHED'}


class FSS_OT_AODetect(bpy.types.Operator):
    bl_idname = 'fss.ao_bake_detect'
    bl_label = 'Find Occluders'
    bl_description = ("Find the occluders of the selected objects (the active one) by the scene rule, for the tree; "
                      "only that: the masters' counts stay as the last Refresh left them")
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        if not _available(cls):
            return False
        return context.mode == 'OBJECT' and bool(tree_targets(context))

    def execute(self, context):
        t = time.perf_counter()
        done = store.detect_occluders(context, tree_targets(context))
        if not done:
            self.report({'WARNING'}, 'No selected object gets a master')
            return {'CANCELLED'}
        self.report({'INFO'}, f'Occluders found for {len(done)} object(s) in {time.perf_counter() - t:.2f} s')
        _redraw(sidebar_only=True)
        return {'FINISHED'}


class FSS_OT_AOTreeFold(bpy.types.Operator):
    bl_idname = 'fss.ao_bake_tree_fold'
    bl_label = 'Fold'
    bl_description = "Show or hide this row's children"
    bl_options = {'INTERNAL'}

    name: bpy.props.StringProperty(options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return _available(cls)

    def execute(self, context):
        if self.name in _tree_open:
            _tree_open.discard(self.name)
        else:
            _tree_open.add(self.name)
        _redraw(sidebar_only=True)
        return {'FINISHED'}


def branch_objects(view_layer, name):
    """Decision 69: the row's object and all its children at every depth, those visible in the view layer."""
    obj = view_layer.objects.get(name)
    if obj is None:
        return []
    return [o for o in [obj] + list(obj.children_recursive)
            if o.name in view_layer.objects and o.visible_get(view_layer=view_layer)]


class FSS_OT_AOTreeSelect(bpy.types.Operator):
    bl_idname = 'fss.ao_bake_tree_select'
    bl_label = 'Select'
    bl_description = ('Select this object and all its children (only them) and make it the active one (the panel '
                      'then shows it)')
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    name: bpy.props.StringProperty(options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        if not _available(cls):
            return False
        return context.mode == 'OBJECT'

    def execute(self, context):
        view_layer = context.view_layer
        objs = branch_objects(view_layer, self.name)
        if not objs:
            self.report({'WARNING'}, f'{self.name} is not visible in the view layer')
            return {'CANCELLED'}
        for o in view_layer.objects:
            if o.select_get():
                o.select_set(False)
        for o in objs:
            o.select_set(True)
        view_layer.objects.active = view_layer.objects[self.name]
        return {'FINISHED'}


_highlight = dict(names=frozenset(), key=None, batch=None, objs=None)  # decisions 69, 72: the highlighted rows
_highlight_handle = None
HIGHLIGHT_COLOR = (1.0, 0.1, 0.9, 1.0)


def _highlight_draw():
    names = _highlight['names']
    if not names:
        return
    context = bpy.context
    view_layer = context.view_layer
    try:  # Session 53: the objects are found once per highlight, not on every viewport redraw
        if _highlight['objs'] is None:
            by_name = {o.name: o for o in view_layer.objects}
            found = {}
            for n in sorted(names):
                o = by_name.get(n)
                for c in ([o] + list(o.children_recursive)) if o is not None else ():
                    if c.type == 'MESH' and c.name in by_name and c.visible_get(view_layer=view_layer):
                        found[c.name] = c
            _highlight['objs'] = list(found.values())
        objs = _highlight['objs']
        key = (tuple(sorted(names)), context.scene.frame_current, len(objs),
               tuple(tuple(o.matrix_world.translation) for o in objs[:64]))
    except ReferenceError:  # an object removed since
        _highlight.update(objs=None, key=None, batch=None)
        return
    if _highlight['key'] != key:
        import gpu
        import numpy as np
        from gpu_extras.batch import batch_for_shader
        pts = []
        for o in objs:
            me = o.data
            n_v, n_e = len(me.vertices), len(me.edges)
            if not n_e:
                continue
            co = np.empty(n_v * 3, np.float32)
            me.vertices.foreach_get('co', co)
            ed = np.empty(n_e * 2, np.int32)
            me.edges.foreach_get('vertices', ed)
            M = np.array(o.matrix_world, np.float32)
            w = co.reshape(-1, 3) @ M[:3, :3].T + M[:3, 3]
            pts.append(w[ed])
        shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')  # as Empty Bounds: line width works everywhere
        coords = np.concatenate(pts) if pts else np.zeros((0, 3), np.float32)
        _highlight.update(key=key, batch=(shader, batch_for_shader(shader, 'LINES', {'pos': coords})))
    import gpu
    shader, batch = _highlight['batch']
    region = context.region
    gpu.state.depth_test_set('NONE')  # on top: seen through what hides it
    gpu.state.blend_set('ALPHA')
    shader.bind()
    shader.uniform_float('viewportSize', (region.width, region.height))
    shader.uniform_float('lineWidth', 2.0)
    shader.uniform_float('color', HIGHLIGHT_COLOR)
    batch.draw(shader)
    gpu.state.blend_set('NONE')


def _tag_views():
    for window in getattr(bpy.context.window_manager, 'windows', ()):
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


class FSS_OT_AOTreeHighlight(bpy.types.Operator):
    bl_idname = 'fss.ao_bake_tree_highlight'
    bl_label = 'Highlight'
    bl_description = ('Draw this object and all its children as a bright wire over the viewport, without selecting '
                      'them; again to clear')
    bl_options = {'INTERNAL'}

    name: bpy.props.StringProperty(options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return _available(cls)

    def execute(self, context):
        names = frozenset() if _highlight['names'] == {self.name} else frozenset((self.name,))
        _highlight.update(names=names, key=None, batch=None, objs=None)
        _tag_views()
        _redraw(sidebar_only=True)
        return {'FINISHED'}


class FSS_OT_AOTreeSelectAll(bpy.types.Operator):
    bl_idname = 'fss.ao_bake_tree_select_all'
    bl_label = 'Select All'
    bl_description = ('Select every detected object of the list (only them) and make the first row of the flat view '
                      'the active one')
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        if not _available(cls):
            return False
        return context.mode == 'OBJECT' and bool(detected_tree(context)['detected'])

    def execute(self, context):
        view_layer = context.view_layer
        st = context.window_manager.fss_ao_bake_state
        rows = tree_rows(detected_tree(context), '', True, st.detected_sort == 'DISTANCE')
        objs = [view_layer.objects[n] for n in rows if n in view_layer.objects
                and view_layer.objects[n].visible_get(view_layer=view_layer)]
        if not objs:
            self.report({'WARNING'}, 'No detected object is visible in the view layer')
            return {'CANCELLED'}
        for o in view_layer.objects:
            if o.select_get():
                o.select_set(False)
        for o in objs:
            o.select_set(True)
        view_layer.objects.active = objs[0]
        self.report({'INFO'}, f'{len(objs)} detected objects selected')
        return {'FINISHED'}


class FSS_OT_AOTreeHighlightAll(bpy.types.Operator):
    bl_idname = 'fss.ao_bake_tree_highlight_all'
    bl_label = 'Highlight All'
    bl_description = 'Draw every detected object of the list as a bright wire over the viewport, without selecting them'
    bl_options = {'INTERNAL'}

    clear: bpy.props.BoolProperty(options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return _available(cls)

    @classmethod
    def description(cls, context, properties):
        return 'Clear the highlight' if properties.clear else cls.bl_description

    def execute(self, context):
        names = frozenset() if self.clear else frozenset(detected_tree(context)['detected'])
        _highlight.update(names=names, key=None, batch=None, objs=None)
        _tag_views()
        _redraw(sidebar_only=True)
        return {'FINISHED'}


class FSS_OT_AOTreeToggle(bpy.types.Operator):
    bl_idname = 'fss.ao_bake_tree_toggle'
    bl_label = 'Switch'
    bl_description = 'Switch the Detected list between tree and flat view, or between sorting by name and by distance'
    bl_options = {'INTERNAL'}

    what: bpy.props.EnumProperty(items=[('VIEW', 'View', ''), ('SORT', 'Sort', '')], options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        return _available(cls)

    def execute(self, context):
        st = context.window_manager.fss_ao_bake_state
        if self.what == 'VIEW':
            st.detected_view = 'TREE' if st.detected_view == 'FLAT' else 'FLAT'
        else:
            st.detected_sort = 'NAME' if st.detected_sort == 'DISTANCE' else 'DISTANCE'
        _redraw(sidebar_only=True)
        return {'FINISHED'}


TREE_BUTTONS = ('fss.ao_bake_tree_set', 'fss.ao_bake_tree_highlight', 'fss.ao_bake_tree_select',
                'fss.ao_bake_tree_fold')


def _is_detected_button(context):
    """Decision 72: the right-clicked button is a row of the Detected list (its row, which holds the highlighted
    index, or one of its buttons)."""
    prop = getattr(context, 'button_prop', None)
    ptr = getattr(context, 'button_pointer', None)
    if prop is not None and prop.identifier == 'detected_index' and isinstance(ptr, FSS_AOBakeState):
        return True
    op = getattr(context, 'button_operator', None)
    if op is None:
        return False
    ident = op.rna_type.identifier.lower()  # FSS_OT_ao_bake_tree_select
    return any(ident == 'fss_ot_' + b.split('.', 1)[1] for b in TREE_BUTTONS)


def _detected_menu(self, context):
    """Decision 72: the Detected list's right-click menu: Find Occluders, the view, the sort, Select All and
    Highlight All."""
    if not _is_detected_button(context):
        return
    st = context.window_manager.fss_ao_bake_state
    layout = self.layout
    layout.separator()
    layout.operator('fss.ao_bake_detect', icon='FILE_REFRESH')
    flat = st.detected_view == 'FLAT'
    layout.operator('fss.ao_bake_tree_toggle', text='Tree View' if flat else 'Flat View',
                    icon='OUTLINER' if flat else 'ALIGN_JUSTIFY').what = 'VIEW'
    by_distance = st.detected_sort == 'DISTANCE'
    layout.operator('fss.ao_bake_tree_toggle', text='Sort by Name' if by_distance else 'Sort by Distance',
                    icon='SORTALPHA' if by_distance else 'DRIVER_DISTANCE').what = 'SORT'
    layout.operator('fss.ao_bake_tree_select_all', icon='RESTRICT_SELECT_OFF')
    layout.operator('fss.ao_bake_tree_highlight_all', icon='HIDE_OFF')
    if _highlight['names']:
        layout.operator('fss.ao_bake_tree_highlight_all', text='Clear Highlight', icon='HIDE_ON').clear = True


class FSS_OT_AOCustomOccluders(bpy.types.Operator):
    bl_idname = 'fss.ao_bake_custom_occluders'
    bl_label = 'Custom Occluders'
    bl_description = "Edit the active object's list of occluders"
    bl_options = {'REGISTER', 'UNDO'}

    action: bpy.props.EnumProperty(items=[
        ('ADD', 'Add Selected', 'Add the selected objects (but the active one) to the list'),
        ('REMOVE', 'Remove', 'Remove the highlighted object from the list'),
        ('CLEAR', 'Clear', 'Empty the list'),
        ('TOGGLE', 'Add or Ignore', 'Switch the item between Add and Ignore'),
        ('CHILDREN', 'With Its Children', 'Switch whether the item also covers its children')], default='ADD')
    index: bpy.props.IntProperty(default=-1, options={'SKIP_SAVE'})

    @classmethod
    def description(cls, context, properties):
        return {'ADD': "Add the selected objects (but the active one) to the active object's occluders",
                'REMOVE': 'Remove the highlighted object from the list',
                'CLEAR': "Empty the active object's list of occluders",
                'TOGGLE': 'Switch between Add (it darkens the object) and Ignore (it never darkens the object)',
                'CHILDREN': "Switch whether the item also covers the object's children at every depth (an item on a "
                            "child wins)"}[properties.action]

    @classmethod
    def poll(cls, context):
        if not _available(cls):
            return False
        return context.mode == 'OBJECT' and _active_mesh(context) is not None

    def execute(self, context):
        obj = _active_mesh(context)
        s = obj.fss_ao_bake
        if self.action == 'ADD':
            have = {r.object for r in s.custom if r.object is not None}
            added = 0
            for o in context.selected_objects:
                if o != obj and _listable(o) and o not in have:
                    _add_ref(s, o)
                    added += 1
            self.report({'INFO'}, f'{added} added to the occluders of {obj.name}')
        elif self.action == 'CHILDREN':
            if 0 <= self.index < len(s.custom):
                s.custom[self.index].children = not s.custom[self.index].children
                s.custom_index = self.index
        elif self.action == 'TOGGLE':
            if 0 <= self.index < len(s.custom):
                s.custom[self.index].ignore = not s.custom[self.index].ignore
                s.custom_index = self.index
        elif self.action == 'REMOVE':
            if 0 <= s.custom_index < len(s.custom):
                s.custom.remove(s.custom_index)
                s.custom_index = min(s.custom_index, len(s.custom) - 1)
        else:
            s.custom.clear()
        return {'FINISHED'}


_apply_run = dict(gen=None, cancel=False, t0=0.0)  # the panel's Apply in steps (decision 45)
APPLY_SLICE_S = 0.1  # work per timer tick before Blender redraws and takes input


class FSS_OT_AOApply(bpy.types.Operator):
    bl_idname = 'fss.ao_apply'
    bl_label = 'Apply'
    bl_description = "Copy the masters into the texture set's AO target (writes files only)"
    bl_options = {'REGISTER'}

    scope: bpy.props.EnumProperty(items=[('SET', 'Texture Set', ''), ('ALL', 'All', ''),
                                         ('SELECTED', 'Selected', '')], default='SET')
    material: bpy.props.StringProperty(options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        if not _available(cls):
            return False
        return (context.mode == 'OBJECT' and store._state['refreshed'] is not None and bool(bpy.data.filepath)
                and _apply_run['gen'] is None and not store.running())

    def _materials(self, context):
        """(materials, objects) to apply, or None (reported)."""
        sets = store._state['sets']
        objects = None
        if self.scope == 'SET':
            names = [self.material] if self.material in sets else []
            if names and self.material in bpy.data.materials:
                problem = target_problem(context, bpy.data.materials[self.material])
                if problem:
                    self.report({'ERROR'}, f'AO Apply: {self.material}: {problem}')
                    return None
        elif self.scope == 'ALL':
            names = sorted(sets)
        else:
            objects = list(context.selected_objects)
            stems = set(store.items_for_objects(objects))
            names = sorted(n for n, row in sets.items() if stems & set(row['items']))
        materials = [bpy.data.materials[n] for n in names if n in bpy.data.materials]
        if self.scope == 'SELECTED':  # only the ticked texture sets, each one's target writable
            ticked = [m for m in materials if m.fss_ao_apply.use]
            if materials and not ticked:
                self.report({'WARNING'}, "AO Apply: none of the selection's texture sets is ticked")
                return None
            blocked = [f'{m.name}: {target_problem(context, m)}' for m in ticked if target_problem(context, m)]
            if blocked:
                self.report({'ERROR'}, 'AO Apply: ' + '; '.join(blocked))
                return None
            materials = ticked
        if not materials:
            self.report({'WARNING'}, 'AO Apply: no texture set')
            return None
        return materials, objects

    def _done(self, context, reports, extra=''):
        lines = [line for rep in reports for line in apply_mod.report_lines(rep)]
        if extra:
            lines.append(extra)
        # decision 74: the panel shows only what failed (and Cancel); the whole report goes to the console
        shown = [line for rep in reports if rep.get('error') for line in apply_mod.report_lines(rep)]
        _state(context).apply_report = '\n'.join(shown + ([extra] if extra else []))
        self._reports = reports
        for line in lines:
            print('AO Apply:', line)
        self.report({'WARNING'} if (extra or any(r.get('error') for r in reports)) else {'INFO'},
                    f'AO Apply: {len(reports)} texture set(s)' + (f'; {extra}' if extra else ''))

    def execute(self, context):
        """In one go (scripts and tests)."""
        got = self._materials(context)
        if got is None:
            return {'CANCELLED'}
        self._done(context, apply_mod.apply(context, *got))
        return {'FINISHED'}

    def invoke(self, context, event):
        """From the panel: in steps on a timer, with progress and Cancel (decision 45)."""
        if context.window is None:
            return self.execute(context)
        got = self._materials(context)
        if got is None:
            return {'CANCELLED'}
        st = _state(context)
        st.applying, st.apply_set, st.apply_sets, st.apply_factor = True, 0, len(got[0]), 0.0
        st.apply_material, st.apply_what, st.apply_elapsed = got[0][0].name, 'Starting', 0.0
        # bpy.context, not the invoke's context, which is not valid after invoke returns
        _apply_run.update(gen=apply_mod.apply_steps(bpy.context, *got), cancel=False, t0=time.time())
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.02, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _end(self, context):
        context.window_manager.event_timer_remove(self._timer)
        gen = _apply_run['gen']
        _apply_run.update(gen=None, cancel=False)
        _state(context).applying = False
        _redraw()
        return gen

    def modal(self, context, event):
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}
        st = _state(context)
        gen = _apply_run['gen']
        if _apply_run['cancel']:
            self._end(context)
            gen.close()  # the set being applied: its .tmp removed, its file untouched
            done = st.apply_set
            self._done(context, [], f'cancelled: {done} of {st.apply_sets} texture set(s) written before, '
                                    f'{st.apply_material} not written')
            return {'CANCELLED'}
        t = time.time()
        try:
            while time.time() - t < APPLY_SLICE_S:
                i, n, name, frac, what = next(gen)
                st.apply_set, st.apply_sets, st.apply_material, st.apply_what = i, n, name, what
                st.apply_factor = (i + frac) / max(n, 1)
        except StopIteration as stop:
            self._end(context)
            self._done(context, stop.value or [])
            return {'FINISHED'}
        except Exception as exc:
            self._end(context)
            gen.close()
            self._done(context, [], f'stopped by an error: {exc}')
            return {'CANCELLED'}
        st.apply_elapsed = time.time() - _apply_run['t0']
        _redraw(sidebar_only=True)
        return {'RUNNING_MODAL'}


class FSS_OT_AOApplyCancel(bpy.types.Operator):
    bl_idname = 'fss.ao_apply_cancel'
    bl_label = 'Cancel'
    bl_description = ('Stop Apply: the texture set being applied keeps its file as it was; sets already applied '
                      'stay written')
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return _apply_run['gen'] is not None

    def execute(self, context):
        _apply_run['cancel'] = True
        return {'FINISHED'}


# ---------------------------------------------------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------------------------------------------------

def selected_sets(context):
    """The texture sets of the selected objects' masters (from the last Refresh); None when nothing is selected."""
    objs = list(getattr(context, 'selected_objects', None) or [])
    if not objs:
        return None
    items = store._state['items']
    return {m for s in store.items_for_objects(objs) if s in items for m in items[s]['sets']}


def apply_material(context, st):
    """The texture set the Apply box is for: the only one of the selection, else the highlighted row when the list
    shows it; None when there is no such row."""
    sel = selected_sets(context)
    shown = [r.material for r in st.sets if sel is None or r.material in sel]
    if sel is not None and len(shown) == 1:
        name = shown[0]
    else:
        row = st.sets[st.active_set] if 0 <= st.active_set < len(st.sets) else None
        name = row.material if row is not None and row.material in shown else None
    return bpy.data.materials.get(name) if name else None


def target_problem(context, material):
    """Why Apply cannot write this texture set's ticked targets, or '' (the ORM texture's file, or an output folder)."""
    a = material.fss_ao_apply
    s = context.scene.fss_ao_bake
    if s.apply_ao and a.target == 'ORM':
        orm = apply_mod.orm_image(material)
        if orm is None:
            return 'No texture in the ORM slot'
        path = apply_mod.image_path(orm)
        if not path or not os.path.isfile(path):
            return f'ORM texture file not found: {path or orm.name}'
    for kind, on in (('ao', s.apply_ao and a.target == 'FILE'), ('curv', s.apply_cm)):
        if on:
            folder = apply_mod.output_folder(context.scene, kind)
            if not (os.path.isdir(folder) or os.path.isdir(os.path.dirname(folder.rstrip('\\/')))):
                return f'Output folder cannot be made: {folder}'
    return ''


def _draw_size(layout, settings, prop, path):
    """Resolution: the file's own size when it exists (Apply keeps it), else the choice for a new file."""
    size = apply_mod.existing_size(path)
    if size is None:
        layout.prop(settings, prop)
        return
    row = layout.row(align=True)
    row.label(text='Resolution:')
    row.label(text=f'{size[0]} x {size[1]} (the file\'s size)')


def apply_check(context):
    """Apply Selected's texture sets: (ticked set names of the selection, [(name, why its target cannot be written)])."""
    sel = selected_sets(context) if context.selected_objects else set()
    ticked, blocked = [], []
    for name in sorted(sel or ()):
        mat = bpy.data.materials.get(name)
        if mat is None or not mat.fss_ao_apply.use:
            continue
        ticked.append(name)
        problem = target_problem(context, mat)
        if problem:
            blocked.append((name, problem))
    return ticked, blocked


class FSS_UL_AOSets(bpy.types.UIList):
    """The texture sets; with objects selected, only theirs."""

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        mat = bpy.data.materials.get(item.material)
        if mat is not None:
            row.prop(mat.fss_ao_apply, 'use', text='')
        split = row.split(factor=0.55, align=True)
        split.label(text=item.material, icon='MATERIAL')
        if not (item.n_missing or item.n_stale):
            split.label(text=f'{item.n_total} complete', icon='CHECKMARK')
            return
        cols = split.split(factor=0.5, align=True)
        for n, which, word in ((item.n_missing, 'MISSING', 'missing'), (item.n_stale, 'STALE', 'stale')):
            if n:
                cell = cols.row(align=True)
                cell.alert = True
                op = cell.operator('fss.ao_bake_select', text=f'{n} {word}', icon='RESTRICT_SELECT_OFF')
                op.which, op.material = which, item.material
            else:
                cols.label(text='')

    def filter_items(self, context, data, propname):
        sel = selected_sets(context)
        rows = getattr(data, propname)
        return [self.bitflag_filter_item if (sel is None or r.material in sel) else 0 for r in rows], []


def _inherited(refs, o):
    """Decision 63: what the parents' items with With its children on say about `o`: 'ADD', 'IGNORE' or None."""
    p = o.parent
    while p is not None:
        entry = refs.get(p.name)
        if entry is not None and entry[1]:
            return 'IGNORE' if entry[0] else 'ADD'
        p = p.parent
    return None


class FSS_UL_AOOccluders(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        """Decision 60: the icon switches Add (green plus) and Ignore (red cross, the row in red); an item without
        effect is greyed: Ignore with Scene as occluder off (unless a parent's item adds it), Add with it on for an
        object the scene rule already includes (known after a Refresh). Decision 63: the second icon switches With
        its children; such an item is never greyed."""
        row = layout.row(align=True)
        if item.object is None:
            row.label(text='(deleted)', icon='ERROR')
            return
        obj = data.id_data
        if item.children:
            effective = True
        elif item.ignore:
            effective = data.custom_scene or _inherited(store.custom_refs(obj), item.object) == 'ADD'
        else:
            effective = not (data.custom_scene and
                             item.object.name in store._state.get('scene_rule', {}).get(obj.name, ()))
        row.active = effective
        row.alert = item.ignore
        op = row.operator('fss.ao_bake_custom_occluders', text='', emboss=False,
                          icon='CANCEL' if item.ignore else 'ADD')
        op.action = 'TOGGLE'
        op.index = index
        op = row.operator('fss.ao_bake_custom_occluders', text='', icon='CON_CHILDOF', depress=item.children)
        op.action = 'CHILDREN'
        op.index = index
        row.label(text=item.object.name + ('  + children' if item.children else '') +
                  ('  (ignored)' if item.ignore else ''))


OBJECT_ICONS = {'MESH': 'OUTLINER_OB_MESH', 'EMPTY': 'OUTLINER_OB_EMPTY', 'ARMATURE': 'OUTLINER_OB_ARMATURE',
                'CURVE': 'OUTLINER_OB_CURVE', 'LIGHT': 'OUTLINER_OB_LIGHT', 'CAMERA': 'OUTLINER_OB_CAMERA'}


class FSS_UL_AODetected(bpy.types.UIList):
    """Decisions 62 and 63: the occluders the scene rule detected at the last Refresh for the active object, or
    joined for the selected meshes when several are selected, as a tree with their parents (the scene's objects
    filtered and ordered). Each row: [+] (lit: it darkens) and [-] (lit red: it never darkens; both unlit: mixed),
    the highlight and select buttons (the object with its children, decisions 66 and 69), the fold arrow of a parent
    row, the name (a click highlights the row), on a parent row the number of detected objects in its branch, the gap
    (decision 70: the smallest in the branch; flat view: the object's own), joined the number of selected objects that
    detect it."""

    def filter_items(self, context, data, propname):
        objects = getattr(data, propname)
        st = context.window_manager.fss_ao_bake_state
        rows = tree_rows(detected_tree(context), self.filter_name, st.detected_view == 'FLAT',
                         st.detected_sort == 'DISTANCE')
        pos = {n: i for i, n in enumerate(rows)}
        flags = [self.bitflag_filter_item if o.name in pos else 0 for o in objects]
        order, k = [], len(rows)
        for o in objects:
            if o.name in pos:
                order.append(pos[o.name])
            else:
                order.append(k)
                k += 1
        return flags, order

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        tree = detected_tree(context)
        name = item.name
        if name not in tree['members']:
            return
        state = row_state(context, tree, name)
        row = layout.row(align=True)
        sub = row.row(align=True)
        sub.active = state != 'OFF'
        op = sub.operator('fss.ao_bake_tree_set', text='', icon='ADD', depress=state == 'ON')
        op.name, op.on = name, True
        sub = row.row(align=True)
        sub.active = state != 'ON'
        sub.alert = state == 'OFF'
        op = sub.operator('fss.ao_bake_tree_set', text='', icon='REMOVE', depress=state == 'OFF')
        op.name, op.on = name, False
        op = row.operator('fss.ao_bake_tree_highlight', text='', icon='HIDE_OFF', depress=name in _highlight['names'])
        op.name = name
        op = row.operator('fss.ao_bake_tree_select', text='', icon='RESTRICT_SELECT_OFF')
        op.name = name
        row.separator()
        flat = context.window_manager.fss_ao_bake_state.detected_view == 'FLAT'
        for _ in range(0 if flat else tree['depth'].get(name, 0)):
            row.label(text='', icon='BLANK1')
        kids = None if flat else tree['children'].get(name)
        if flat:
            pass
        elif kids:
            op = row.operator('fss.ao_bake_tree_fold', text='', emboss=False,
                              icon='DISCLOSURE_TRI_DOWN' if name in _tree_open or self.filter_name
                              else 'DISCLOSURE_TRI_RIGHT')
            op.name = name
        else:
            row.label(text='', icon='BLANK1')
        text = f"{name}  ({len(tree['members'][name])})" if kids else name
        row.label(text=text, icon=OBJECT_ICONS.get(item.type, 'OBJECT_DATA'))  # a click highlights the row
        g = tree['own_gap'].get(name) if flat else tree['gap'].get(name)  # decision 70: the distance column
        sub = row.row(align=True)
        sub.alignment = 'RIGHT'
        sub.ui_units_x = 2.6
        sub.label(text='' if g is None else f'{g * 1000:.0f} mm')
        if len(tree['targets']) > 1:  # a narrow column on the right: the name keeps the row's width
            sub = row.row(align=True)
            sub.alignment = 'RIGHT'
            sub.ui_units_x = 2.0
            sub.label(text=f"{tree['count'].get(name, 0)}/{len(tree['targets'])}")


def _motion_info(obj):
    """Decision 59: the object's motion from the last Refresh (its copy's for a shared mesh): dict(mover, against,
    pose_range, pose_note), or None before a Refresh or for an object without a master."""
    item = store._state['items'].get(store._state['by_object'].get(obj.name))
    if item is None:
        return None
    src = next((c for c in item.get('copies') or () if c['object'] == obj.name), None) or item
    if src is item and item.get('copies'):  # One Instance: a copy not baked itself
        return None
    return dict(mover=bool(src.get('mover')), against=src.get('against') or [], pose_range=src.get('pose_range'),
                pose_note=src.get('pose_note') or '')


def _draw_object(layout, context):
    """The active object's overrides (decisions 34 and 35); several selected (decision 75): Objects (n) and a row
    that steps the active object through them."""
    obj = _active_mesh(context)
    sel = _selected_meshes(context)
    if obj is None and len(sel) < 2:
        return
    scene = context.scene
    box = layout.box()
    if len(sel) > 1:
        box.label(text=f'Objects ({len(sel)})', icon='OBJECT_DATA')
        row = box.row(align=True)
        row.operator('fss.ao_object_step', text='', icon='TRIA_LEFT').step = -1
        names = [o.name for o in sel]
        where = f'({names.index(obj.name) + 1} of {len(sel)})' if obj is not None and obj.name in names else \
            f'(not one of the {len(sel)})'
        row.label(text=f'{obj.name if obj is not None else "-"}  {where}')
        row.operator('fss.ao_object_step', text='', icon='TRIA_RIGHT').step = 1
        if obj is None:
            return
    else:
        box.label(text=f'Object: {obj.name}', icon='OBJECT_DATA')
    o = obj.fss_ao_bake
    copies = [u for u in context.view_layer.objects if u.data is obj.data]
    if len(copies) > 1:  # decision 47: one master for the copies; each copy below bakes in its own surroundings
        row = box.row(align=True)
        row.label(text=f'Shared mesh, {len(copies)} copies:', icon='LINKED')
        row.prop(obj.data.fss_ao_shared, 'combine', text='')
        if store.shared_combine(obj.data, scene) == 'ONE':  # decision 77
            names = selected_copies(context, obj.data)
            if len(names) > 1:  # several copies selected: which one Bake Selected bakes
                box.prop(obj.data.fss_ao_shared, 'bake_copy', text='Bake Copy')
            item = store._state['items'].get(store._state['by_object'].get(obj.name))
            if item is not None and item.get('combine') == 'ONE':  # from the last Refresh
                shown = item.get('baked_from')
                if shown:
                    box.label(text=f'One Instance: baked from {shown}', icon='INFO')
                else:
                    shown = min(item['users'])
                    box.label(text=f'One Instance: {shown} (first by name)', icon='INFO')
                choice = bake_copy_choice(context, obj.data, names)
                if choice and choice != shown:
                    box.label(text=f'Bake Selected bakes {choice}', icon='BLANK1')
    if scene.fss_ao_bake.auto_distance:  # decision 51: shown only when it is the object's own, under Max Distance
        first = sorted(copies, key=lambda u: u.name)[0] if len(copies) > 1 else obj
        d = store.item_distance(first, scene)
        if d < round(scene.fss_ao_bake.distance, 6):
            box.label(text=f'AO distance {d * 1000:.3g} mm (Auto Distance)', icon='DRIVER_DISTANCE')
    col = box.column(align=True)
    col.prop(o, 'occluders')
    info = _motion_info(obj)  # decision 59: from the last Refresh
    if info is None:  # before a Refresh: no line (decision 67); an object that moves (or a parent) shows its Poses
        if store.is_mover(obj, scene):
            col.prop(o, 'pose_mode', text='Poses')
            if o.pose_mode == 'MANUAL':
                col.prop(o, 'poses', text='Number of Poses')
    elif info['against']:
        rng = info['pose_range']
        n = len(info['against'])
        what = 'Moves against' if info['mover'] else 'Moving nearby:'
        span = f', frames {rng[0]:g} to {rng[1]:g}' if rng else ''
        col.label(text=f"{what} {n} object{'s' if n != 1 else ''}{span}", icon='INFO')
        col.prop(o, 'pose_mode', text='Poses')
        if o.pose_mode == 'MANUAL':
            col.prop(o, 'poses', text='Number of Poses')
        if info['pose_note']:
            col.label(text=info['pose_note'], icon='BLANK1')
    elif info['mover']:
        if info['pose_note']:
            col.label(text=f"Moves, {info['pose_note']}", icon='INFO')
        else:
            col.label(text='Moves with everything around it: one pose', icon='INFO')
    if o.occluders == 'CUSTOM':  # decision 60
        box.prop(o, 'custom_scene')
        box.template_list('FSS_UL_AOOccluders', '', o, 'custom', o, 'custom_index', rows=3)
        box.prop(o, 'pick', text='Add', icon='EYEDROPPER')
        row = box.row(align=True)
        row.operator('fss.ao_bake_custom_occluders', text='Add Selected', icon='ADD').action = 'ADD'
        row.operator('fss.ao_bake_custom_occluders', text='Remove', icon='REMOVE').action = 'REMOVE'
        row.operator('fss.ao_bake_custom_occluders', text='Clear', icon='X').action = 'CLEAR'
        _lines(box, 'Add Selected: the selected objects but the active one\n'
                    'Click an icon: Add (darkens it) or Ignore (never darkens it)', 'INFO')
    tree = detected_tree(context)  # decisions 62 and 63
    joined = len(tree_targets(context)) > 1
    if joined and o.occluders == 'CUSTOM':
        box.label(text=f'The list above is {obj.name}\'s; the tree below is for the selected', icon='INFO')
    if not tree['targets']:  # decision 68: the scene rule alone, quick
        box.operator('fss.ao_bake_detect', icon='VIEWZOOM')
    else:
        n = len(set().union(*tree['rules'].values()))
        what = f"for {len(tree['targets'])} selected" if joined else 'by the scene rule'
        row = box.row(align=True)
        row.label(text=f"Detected {what}: {n} object{'s' if n != 1 else ''}", icon='VIEWZOOM')
        # decision 72: refresh, view and sort in the list's right-click menu
        if tree['missing']:
            box.label(text=f"{len(tree['missing'])} selected not found yet", icon='ERROR')
        if n:
            box.template_list('FSS_UL_AODetected', '', context.scene, 'objects',
                              context.window_manager.fss_ao_bake_state, 'detected_index', rows=6)
        else:  # no row to right-click
            box.operator('fss.ao_bake_detect', icon='FILE_REFRESH')
    # decision 66: no help lines under the tree and no line on who baked the master (OptiX baker decision 31's line)


def _lines(layout, text, icon='NONE'):
    for i, line in enumerate(text.splitlines()):
        layout.label(text=line, icon=icon if i == 0 else 'BLANK1')


def _fmt_time(seconds):
    seconds = max(0, int(seconds))
    return f'{seconds // 60}:{seconds % 60:02d}'


class FSS_PT_AOBake(bpy.types.Panel):
    bl_idname = 'FSS_PT_ao_bake'
    bl_label = 'Bake'  # decision 76: more than AO
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'FSS MSFS Tools'
    bl_order = 8

    def draw(self, context):
        layout = self.layout
        s = context.scene.fss_ao_bake
        st = _state(context)
        why = ao_unavailable()
        if why:  # apply-native-copy decision 6: the reason on one line; the operators' polls grey the buttons
            layout.label(text=f'Not available: {why}', icon='ERROR')
        if _draw_progress(layout, st):
            return
        _draw_masters(layout, context, s, st)
        _draw_object(layout, context)  # the active object's own settings, a box beside Bake and Texture Target
        _draw_bake(layout, context, s)
        _draw_target(layout, context, s, st)


class FSS_PT_AORun(bpy.types.Panel):
    """Decision 75: what to run for the selected objects, and Run; a subpanel of AO Bake, so it always sits under
    Texture Target (a top-level panel goes wherever the file's saved panel order puts it). Hidden while a bake or Apply
    runs: AO Bake then shows the progress."""
    bl_idname = 'FSS_PT_ao_run'
    bl_label = 'Run'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'FSS MSFS Tools'
    bl_parent_id = 'FSS_PT_ao_bake'

    @classmethod
    def poll(cls, context):
        st = _state(context)
        return not (st.running or st.applying)

    def draw(self, context):
        layout = self.layout
        s = context.scene.fss_ao_bake
        st = _state(context)
        col = layout.column(align=True)
        row = col.row(align=True)
        row.label(text='Run In:')
        row.prop(s, 'run_mode', expand=True)
        n = len(context.selected_objects)
        ticked = apply_check(context)[0] if st.refreshed else []
        sets = f"{len(ticked)} set{'s' if len(ticked) != 1 else ''}"
        items = store._state['items']  # decision 73: masters whose mesh changed since the bake (last Refresh)
        changed = sum(1 for k in store.items_for_objects(context.selected_objects)
                      if (items.get(k) or {}).get('grade') == 'MESH')
        grid = layout.grid_flow(row_major=True, columns=2, even_columns=True, align=True)
        grid.prop(s, 'bake_ao', text=f'AO Bake Selected ({n})')
        cell = grid.row(align=True)
        cell.alert = bool(changed) and s.apply_ao
        cell.prop(s, 'apply_ao', text=f'Apply AO to Texture ({n} objs, {sets})')
        grid.prop(s, 'curvature', text=f'CM Bake Selected ({n})')
        cell = grid.row(align=True)
        cell.alert = bool(changed) and s.apply_cm
        cell.prop(s, 'apply_cm', text=f'Apply CM to Texture ({n} objs, {sets})')
        if changed and (s.apply_ao or s.apply_cm):
            layout.label(text=f'{changed} mesh changed since its bake: applied anyway', icon='ERROR')
        problems = run_problems(context)
        row = layout.row()
        row.scale_y = 1.4
        row.enabled = not problems
        row.operator('fss.ao_run', icon='PLAY')
        for line in problems[:4]:
            layout.label(text=line, icon='INFO')
        if len(problems) > 4:
            layout.label(text=f'and {len(problems) - 4} more', icon='BLANK1')
        if st.report:
            _lines(layout.column(align=True), st.report, 'INFO')
        if st.apply_report:
            _lines(layout.column(align=True), st.apply_report, 'INFO')


def _draw_progress(layout, st):
    """While a bake or Apply runs: only its progress and Cancel (decisions 44, 45; OptiX baker decision 30); Run's
    apply waiting for the bake (decision 75). Returns True when drawn. AO Bake draws it; Run is hidden meanwhile."""
    if st.running:
        box = layout.box()
        box.label(text='Baking', icon='RENDER_STILL')
        col = box.column(align=True)
        f = max(st.progress, st.n_done / max(st.n_total, 1))
        col.progress(factor=f, text=f'Object {min(st.n_done + 1, st.n_total)} of {st.n_total}, {f * 100:.0f} %')
        col.label(text=st.current or '...')
        if st.phase:  # decision 56
            col.label(text=f'{st.phase}: band {st.tile} of {st.n_tiles}')
        elif st.n_tiles > 1:
            col.label(text=f'Tile {st.tile} of {st.n_tiles}')
        if st.n_copies > 1:  # decision 47: a shared mesh, its copies in their own poses
            col.label(text=f'Copy {max(st.copy, 1)} of {st.n_copies}: {st.copy_name}')
            if st.copy_poses > 1:
                col.label(text=f'Pose {max(st.copy_pose, 1)} of {st.copy_poses}')
        elif st.n_poses > 1:
            col.label(text=f'Pose {max(st.pose, 1)} of {st.n_poses}')
        left = _fmt_time(st.left) if st.left >= 0 else '-'
        col.label(text=f'Spent {_fmt_time(st.elapsed)}, left {left}')
        if _run_next['objects'] is not None:
            col.label(text='Then: apply to the textures', icon='TEXTURE')
        col.operator('fss.ao_bake_cancel', icon='CANCEL')
        return True
    if st.applying:
        box = layout.box()
        box.label(text='Applying', icon='TEXTURE')
        col = box.column(align=True)
        col.progress(factor=st.apply_factor,
                     text=f'Texture set {min(st.apply_set + 1, st.apply_sets)} of {st.apply_sets}')
        col.label(text=st.apply_material)
        col.label(text=st.apply_what)
        f = st.apply_factor
        left = _fmt_time(st.apply_elapsed / f * (1 - f)) if f > 0.02 else '-'
        col.label(text=f'Spent {_fmt_time(st.apply_elapsed)}, left {left}')
        col.operator('fss.ao_apply_cancel', icon='CANCEL')
        return True
    return False


def _draw_masters(layout, context, s, st):
    box = layout.box()  # the masters' state, a box beside Object, Bake and Texture Target
    box.label(text='Masters', icon='FILE_REFRESH')
    if not bpy.data.filepath:
        box.label(text='Save the file once: the masters are kept beside it', icon='ERROR')
    box.operator('fss.ao_bake_refresh', icon='FILE_REFRESH')
    if st.refreshed:
        grid = box.column(align=True)
        for label, value in (('Up to date', st.up_to_date), ('Surroundings changed', st.surroundings),
                             ('Mesh changed', st.mesh), ('Missing', st.missing), ('Excluded', st.excluded)):
            r = grid.row()
            r.label(text=label)
            r.label(text=str(value))
        parts = [f'{st.cm_up_to_date} up to date'] + [
            f'{v} {t}' for v, t in ((st.cm_width, 'other width'), (st.cm_missing, 'missing'),
                                    (st.cm_needs_ao, 'need AO')) if v]
        grid.label(text='Curvature: ' + ', '.join(parts))  # decision 55
        if s.denoise or st.dn_stale:  # decision 56
            parts = [f'{st.dn_up_to_date} up to date'] + [
                f'{v} {t}' for v, t in ((st.dn_stale, 'to re-run'), (st.dn_needs_ao, 'need AO')) if v]
            grid.label(text='Denoise: ' + ', '.join(parts))
        row = box.row(align=True)  # select by the masters' state, then run the selection
        row.operator('fss.ao_bake_select', text='Select Missing').which = 'MISSING'
        row.operator('fss.ao_bake_select', text='Select Stale').which = 'STALE'
        row.operator('fss.ao_bake_select', text='Missing and Stale').which = 'OUTDATED'


def _draw_bake(layout, context, s):
    box = layout.box()
    box.label(text='Bake', icon='RENDER_STILL')
    col = box.column(align=True)
    if not s.auto_distance:
        col.prop(s, 'distance')
    row = col.row(align=True)
    row.prop(s, 'auto_distance')
    sub = row.row(align=True)
    sub.active = s.auto_distance
    sub.prop(s, 'auto_distance_factor')
    if s.auto_distance:  # decision 51: the same value, the most any object gets
        col.prop(s, 'distance', text='Max Distance')
    row = col.row(align=True)
    row.prop(s, 'falloff')
    sub = row.row(align=True)
    sub.active = s.falloff
    sub.prop(s, 'falloff_steps')
    col.separator()
    row = col.row(align=True)  # OptiX baker decisions 22, 24
    row.label(text='Baker')
    row.prop(s, 'baker', expand=True)
    if s.baker != 'CYCLES':
        have, why = native.available()
        col.prop(s, 'optix_samples', text='FSS OptiX Samples')
        if not have:
            _lines(col, f'{why}: Cycles bakes', 'INFO')
    if s.baker != 'OPTIX':
        col.prop(s, 'samples', text='Cycles Samples' if s.baker == 'AUTO' else 'Samples')
        row = col.row(align=True)
        row.prop(s, 'device', expand=True)
        if s.device == 'CPU':
            col.prop(s, 'threads')
    col.separator()
    col.prop(s, 'poses')
    col.prop(s, 'shared_combine')
    if s.poses > 1 or s.shared_combine != 'ONE':  # how the samples are spent over the views a master averages
        col.prop(s, 'sample_quality')
    col.separator()
    col.prop(s, 'occluders')
    col.separator()
    row = col.row(align=True)  # decision 56
    row.prop(s, 'denoise')
    sub = row.row(align=True)
    sub.active = s.denoise
    sub.prop(s, 'dn_strength')
    if s.denoise:
        row = col.row(align=True)
        row.label(text='Method')
        row.prop(s, 'dn_method', expand=True)
    if s.denoise and s.dn_method == 'FILTER':
        sub = col.column(align=True)
        sub.prop(s, 'dn_radius')
        sub.prop(s, 'dn_levels')
        sub.prop(s, 'dn_detail')
        sub.prop(s, 'dn_normal')
        row = sub.row(align=True)
        row.prop(s, 'dn_curv_mode', text='Curvature')
        cell = row.row(align=True)
        cell.active = s.dn_curv_mode != 'OFF'
        cell.prop(s, 'dn_curv_threshold')
        sub.prop(s, 'dn_noise')
    if s.curvature or (s.denoise and s.dn_method == 'FILTER' and s.dn_curv_mode != 'OFF'):  # Denoise reads it too
        col.separator()
        col.prop(s, 'curv_width')


def _draw_target(layout, context, s, st):
    """Decision 75: the texture sets and where Apply writes (Run applies)."""
    box = layout.box()
    box.label(text='Texture Target', icon='TEXTURE')
    if not st.refreshed:
        box.label(text='Refresh first', icon='INFO')
        return
    sel = selected_sets(context)
    if sel is not None:
        box.label(text=f'Texture sets of the selection: {len(sel)} (none selected: all)', icon='RESTRICT_SELECT_OFF')
    box.template_list('FSS_UL_AOSets', '', st, 'sets', st, 'active_set', rows=4)
    material = apply_material(context, st)
    if material is None:
        box.label(text='Pick a texture set in the list', icon='INFO')
        return
    a = material.fss_ao_apply
    sub = box.column(align=True)
    sub.label(text=f'Texture set: {material.name}', icon='MATERIAL')
    orm = apply_mod.orm_image(material)
    problem = target_problem(context, material)
    sub.label(text='AO')
    ind = sub.row()
    ind.separator(factor=2.0)
    col = ind.column(align=True)
    row = col.row(align=True)
    row.label(text='Target')
    row.prop(a, 'target', expand=True)
    if a.target == 'ORM':
        if orm is not None:
            col.label(text=f'ORM texture: {orm.name}', icon='IMAGE_DATA')
            if orm.depth and orm.depth < 48 and not orm.is_float:  # decision 74
                col.label(text='8-bit file: written as 16-bit', icon='ERROR')
    else:
        col.prop(s, 'output_folder')  # the scene's folder, shown where it is used: with the file's name
        col.prop(a, 'file_name')
        _draw_size(col, a, 'resolution', os.path.join(apply_mod.output_folder(context.scene),
                                                      apply_mod.file_name(material, a)))
        row = col.row(align=True)
        row.label(text='Channels')
        row.prop(a, 'layout', expand=True)
        if a.layout == 'ORM':
            col.prop(a, 'green_blue')
            if a.green_blue == 'COPY':
                if orm is None:
                    col.label(text='No ORM texture: green and blue white', icon='ERROR')
                elif a.resolution != 'ORM' and tuple(orm.size) != (int(a.resolution), int(a.resolution)):
                    col.label(text="Another size: roughness and metallic are resampled", icon='ERROR')
                    col.prop(a, 'sampling')
    col.prop(s, 'padding')  # the scene's, shown where it is used
    row = col.row(align=True)
    row.prop(s, 'soften_edges')
    cell = row.row(align=True)
    cell.enabled = s.soften_edges
    cell.prop(s, 'soften_width', text='Width')
    sub.label(text='Curvature Map')  # decision 54
    ind = sub.row()
    ind.separator(factor=2.0)
    col = ind.column(align=True)
    col.prop(s, 'curv_output_folder')
    col.prop(a, 'curv_file_name')
    _draw_size(col, a, 'curv_resolution', os.path.join(apply_mod.output_folder(context.scene, 'curv'),
                                                       apply_mod.curvature_name(material)))
    col.prop(s, 'curv_padding')
    if problem:
        sub.label(text=problem, icon='ERROR')


@persistent
def _forget_highlight_objects(*_args):
    """Decision 77: undo, redo and a file load replace the objects; the highlight finds them again."""
    _highlight.update(objs=None, key=None, batch=None)


@persistent
def _on_load_post(*_args):
    store._state.update(items={}, by_object={}, excluded={}, sets={}, refreshed=None, folder=None)
    try:
        wm = bpy.context.window_manager
        st = wm.fss_ao_bake_state
        st.refreshed = False
        st.applying = False  # a file load ends a running Apply's modal operator
        _run_next['objects'] = None  # decision 75: a queued apply belongs to the file it was run in
        if _apply_run['gen'] is not None:
            _apply_run['gen'].close()
            _apply_run.update(gen=None, cancel=False)
        st.sets.clear()
        st.report = st.apply_report = ''
        read_index_on_open()
    except AttributeError:
        pass


CLASSES = (FSS_AOBakeSettings, FSS_AOMeshSettings, FSS_AOOccluderRef, FSS_AOObjectSettings, FSS_AOApplySettings,
           FSS_AOSetRow,
           FSS_AOBakeState, FSS_OT_AOBakeRefresh, FSS_OT_AOBakeStart, FSS_OT_AOBakeCancel, FSS_OT_AOBakeSelect,
           FSS_OT_AOCustomOccluders, FSS_OT_AODetect, FSS_OT_AOTreeSet, FSS_OT_AOTreeFold, FSS_OT_AOTreeSelect, FSS_OT_AOTreeHighlight,
           FSS_OT_AOTreeSelectAll, FSS_OT_AOTreeHighlightAll, FSS_OT_AOTreeToggle, FSS_OT_AOApply, FSS_OT_AOApplyCancel, FSS_UL_AOSets, FSS_UL_AOOccluders, FSS_UL_AODetected,
           FSS_OT_AORun, FSS_OT_AOObjectStep, FSS_PT_AOBake, FSS_PT_AORun)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.fss_ao_bake = bpy.props.PointerProperty(type=FSS_AOBakeSettings)
    bpy.types.Object.fss_ao_bake = bpy.props.PointerProperty(type=FSS_AOObjectSettings)
    bpy.types.Mesh.fss_ao_shared = bpy.props.PointerProperty(type=FSS_AOMeshSettings)
    bpy.types.Material.fss_ao_apply = bpy.props.PointerProperty(type=FSS_AOApplySettings)
    bpy.types.WindowManager.fss_ao_bake_state = bpy.props.PointerProperty(type=FSS_AOBakeState)
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)
    for handlers in (bpy.app.handlers.undo_post, bpy.app.handlers.redo_post, bpy.app.handlers.load_post):
        if _forget_highlight_objects not in handlers:
            handlers.append(_forget_highlight_objects)
    global _highlight_handle
    if not bpy.app.background and _highlight_handle is None:
        _highlight_handle = bpy.types.SpaceView3D.draw_handler_add(_highlight_draw, (), 'WINDOW', 'POST_VIEW')
    bpy.types.UI_MT_button_context_menu.append(_detected_menu)


def unregister():
    global _highlight_handle
    if _highlight_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_highlight_handle, 'WINDOW')
        _highlight_handle = None
    _highlight.update(names=frozenset(), key=None, batch=None, objs=None)
    bpy.types.UI_MT_button_context_menu.remove(_detected_menu)
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    for handlers in (bpy.app.handlers.undo_post, bpy.app.handlers.redo_post, bpy.app.handlers.load_post):
        if _forget_highlight_objects in handlers:
            handlers.remove(_forget_highlight_objects)
    if bpy.app.timers.is_registered(_poll_timer):
        bpy.app.timers.unregister(_poll_timer)
    del bpy.types.WindowManager.fss_ao_bake_state
    del bpy.types.Object.fss_ao_bake
    del bpy.types.Mesh.fss_ao_shared
    del bpy.types.Material.fss_ao_apply
    del bpy.types.Scene.fss_ao_bake
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
