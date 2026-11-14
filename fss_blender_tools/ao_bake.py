"""AO Bake panel (auto-bake journal, decision 29 and P46): bake masters in a second Blender, apply them to textures.

FSS MSFS Tools > AO Bake:
- Bake: AO distance (scene, decision 16), Auto Distance (decision 51), Distance Falloff (decision 53), Curvature Map
  (decision 54), the baker (Auto, FSS OptiX or Cycles: OptiX baker journal decision 22) with FSS OptiX's samples
  (decision 24) and Cycles' samples and device; poses of moving parts and the occluders (scene defaults, decisions 34
  and 35), the run mode (Hidden or Visible, decision 36); the active object's overrides (poses, occluders, its custom
  list of occluders with Add Selected, Remove, Clear) and the baker of its master; the masters' counts (up to date,
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
    distance: bpy.props.FloatProperty(name="AO Distance", default=0.1, min=0.001, soft_max=1.0, unit='LENGTH',
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
        name="AO", default=True,
        description="The bake buttons bake the AO masters (Baker); with CM also ticked, each object's curvature is "
        "written with its AO")
    curvature: bpy.props.BoolProperty(
        name="CM", default=False,
        description="The bake buttons write the curvature masters (CM): each object's curvature from its geometry in "
        "its AO master's layout, no rays, seconds per object. Without AO, only objects whose AO master is up to date "
        "in mesh (its layout is used). 50 % grey flat, lighter convex, darker concave, as in Substance Painter")
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
        name="AO", default=True, description="Apply writes the AO masters into each texture set's AO target")
    apply_cm: bpy.props.BoolProperty(
        name="Curvature Map", default=False,
        description="Apply writes the curvature masters into each texture set's curvature file (16-bit grey; flat "
        "grey where no curvature master is)")
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
    threads: bpy.props.IntProperty(name="Threads", default=12, min=1, max=64,
                                   description="CPU threads of the bake")
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
        ('ONE', 'One Instance', "Only one copy is baked, in its own surroundings, and all copies use it: the mesh's "
         "picked copy, else its first copy by name")],
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
    ('CUSTOM', 'Custom', 'The objects in the list below, posed with this object when it moves')]
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


def _combine_update(self, context):
    """Decision 48: choosing One Instance on a selected copy makes that copy the instance."""
    obj = getattr(context, 'active_object', None)
    if self.combine == 'ONE' and obj is not None and obj.data is self.id_data:
        self.instance = obj


def _is_copy(self, obj):
    return obj.type == 'MESH' and obj.data is self.id_data


class FSS_AOMeshSettings(bpy.types.PropertyGroup):
    """Decision 47: a shared mesh's override, on the mesh (one master for all its copies, so one choice)."""
    combine: bpy.props.EnumProperty(name="Copies", items=mesh_combine_items, default=0, update=_combine_update,
                                    description="How this shared mesh's copies are combined into its one AO")
    instance: bpy.props.PointerProperty(type=bpy.types.Object, name="Copy", poll=_is_copy,
                                        description="One Instance (decision 48): the copy whose surroundings all "
                                        "copies use. Empty: the first copy by name")


class FSS_AOOccluderRef(bpy.types.PropertyGroup):
    object: bpy.props.PointerProperty(type=bpy.types.Object, name="Object")


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


def master_baker(obj):
    """OptiX baker decision 23: the baker and samples of the object's master as its index entry records them, for
    drawing ('' without an entry; a master of an add-on before 0.77 was baked by Cycles)."""
    stem = store._state.get('by_object', {}).get(obj.name)
    folder = store.bake_folder()
    if not stem or not folder:
        return ''
    e = store.read_index(folder).get('masters', {}).get(stem)
    if not e:
        return ''
    b = e.get('baker') or {}
    return f"Baked by {b.get('name', 'Cycles')}, {e.get('samples', '?')} samples, {e.get('baked_at', '')}".rstrip(', ')


def read_index_on_open():
    st = _state()
    folder = store.bake_folder()
    st.index_masters = len(store.read_index(folder).get('masters', {})) if folder else 0


# ---------------------------------------------------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------------------------------------------------

class FSS_OT_AOBakeRefresh(bpy.types.Operator):
    bl_idname = 'fss.ao_bake_refresh'
    bl_label = 'Refresh'
    bl_description = "Compute the masters' hashes and states against the bake folder (links renamed objects again)"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
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
    if status.get('master_format') == 'png':  # decision 37: said once per bake
        lines.append(f"masters written as PNG: the JPEG XL library could not be loaded ({status.get('jxl_error')})")
    for kind in ('skipped', 'failed', 'cancelled'):
        for r in by.get(kind, []):
            lines.append(f"{kind}: {r['name']} ({r.get('reason', '')})")
    for r in by.get('baked', []):  # decision 34: a mover not baked in its poses, and why
        if r.get('note'):
            lines.append(f"{r['name']}: {r['note']}")
    lines += excluded_lines()
    st.report = '\n'.join(lines)
    sync_state(bpy.context)
    read_index_on_open()
    _redraw()


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
        return (context.mode == 'OBJECT' and bool(bpy.data.filepath) and not store.running()
                and _apply_run['gen'] is None)

    def execute(self, context):
        store.refresh(context)
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


class FSS_OT_AOCustomOccluders(bpy.types.Operator):
    bl_idname = 'fss.ao_bake_custom_occluders'
    bl_label = 'Custom Occluders'
    bl_description = "Edit the active object's list of occluders"
    bl_options = {'REGISTER', 'UNDO'}

    action: bpy.props.EnumProperty(items=[
        ('ADD', 'Add Selected', 'Add the selected objects (but the active one) to the list'),
        ('REMOVE', 'Remove', 'Remove the highlighted object from the list'),
        ('CLEAR', 'Clear', 'Empty the list')], default='ADD')

    @classmethod
    def description(cls, context, properties):
        return {'ADD': "Add the selected objects (but the active one) to the active object's occluders",
                'REMOVE': 'Remove the highlighted object from the list',
                'CLEAR': "Empty the active object's list of occluders"}[properties.action]

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and _active_mesh(context) is not None

    def execute(self, context):
        obj = _active_mesh(context)
        s = obj.fss_ao_bake
        if self.action == 'ADD':
            have = {r.object for r in s.custom if r.object is not None}
            added = 0
            for o in context.selected_objects:
                if o != obj and o.type == 'MESH' and o not in have:
                    s.custom.add().object = o
                    added += 1
            self.report({'INFO'}, f'{added} added to the occluders of {obj.name}')
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
        _state(context).apply_report = '\n'.join(lines)
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


class FSS_UL_AOOccluders(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if item.object is None:
            layout.label(text='(deleted)', icon='ERROR')
        else:
            layout.label(text=item.object.name, icon='OBJECT_DATA')


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
    """The active object's overrides (decisions 34 and 35)."""
    obj = _active_mesh(context)
    if obj is None:
        return
    scene = context.scene
    box = layout.box()
    box.label(text=f'Object: {obj.name}', icon='OBJECT_DATA')
    o = obj.fss_ao_bake
    copies = [u for u in context.view_layer.objects if u.data is obj.data]
    if len(copies) > 1:  # decision 47: one master for the copies; each copy below bakes in its own surroundings
        row = box.row(align=True)
        row.label(text=f'Shared mesh, {len(copies)} copies:', icon='LINKED')
        row.prop(obj.data.fss_ao_shared, 'combine', text='')
        if store.shared_combine(obj.data, scene) == 'ONE':
            box.prop(obj.data.fss_ao_shared, 'instance', text='Copy')
            rep = store.shared_instance(obj.data, copies)
            if obj.data.fss_ao_shared.instance is None or rep is not obj.data.fss_ao_shared.instance:
                box.label(text=f'One Instance: {rep.name} (first by name)', icon='INFO')
    if scene.fss_ao_bake.auto_distance:  # decision 51: shown only when it is the object's own, under Max Distance
        first = sorted(copies, key=lambda u: u.name)[0] if len(copies) > 1 else obj
        d = store.item_distance(first, scene)
        if d < round(scene.fss_ao_bake.distance, 6):
            box.label(text=f'AO distance {d * 1000:.3g} mm (Auto Distance)', icon='DRIVER_DISTANCE')
    col = box.column(align=True)
    col.prop(o, 'occluders')
    info = _motion_info(obj)  # decision 59: from the last Refresh
    if info is None:
        if store.is_mover(obj, scene):
            col.label(text='Moves: Refresh shows its poses', icon='INFO')
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
    if o.occluders == 'CUSTOM':
        box.template_list('FSS_UL_AOOccluders', '', o, 'custom', o, 'custom_index', rows=3)
        row = box.row(align=True)
        row.operator('fss.ao_bake_custom_occluders', text='Add Selected', icon='ADD').action = 'ADD'
        row.operator('fss.ao_bake_custom_occluders', text='Remove', icon='REMOVE').action = 'REMOVE'
        row.operator('fss.ao_bake_custom_occluders', text='Clear', icon='X').action = 'CLEAR'
    # OptiX baker decision 31: no picture of the master (its layout is not the artist's UVs), only who baked it
    by = master_baker(obj)
    box.label(text=by or 'No master baked yet', icon='INFO')


def _lines(layout, text, icon='NONE'):
    for i, line in enumerate(text.splitlines()):
        layout.label(text=line, icon=icon if i == 0 else 'BLANK1')


def _fmt_time(seconds):
    seconds = max(0, int(seconds))
    return f'{seconds // 60}:{seconds % 60:02d}'


class FSS_PT_AOBake(bpy.types.Panel):
    bl_idname = 'FSS_PT_ao_bake'
    bl_label = 'AO Bake'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'FSS MSFS Tools'
    bl_order = 8

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        s = scene.fss_ao_bake
        st = _state(context)
        if st.running:  # decision 44: while a bake runs, only its progress and Cancel (OptiX baker decision 30)
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
            col.operator('fss.ao_bake_cancel', icon='CANCEL')
            return
        if st.applying:  # decision 45: while Apply runs, only its progress and Cancel
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
            return
        box = layout.box()  # the masters' state, a box beside Object, Bake and Apply
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
        else:
            box.label(text=f'{st.index_masters} masters in the bake folder; Refresh to compare', icon='INFO')
        if st.refreshed:  # select by the masters' state, then bake or apply the selection
            row = box.row(align=True)
            row.operator('fss.ao_bake_select', text='Select Missing').which = 'MISSING'
            row.operator('fss.ao_bake_select', text='Select Stale').which = 'STALE'
            row.operator('fss.ao_bake_select', text='Missing and Stale').which = 'OUTDATED'
        _draw_object(layout, context)  # the active object's own settings, a box beside Bake and Apply
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
        col = box.column(align=True)
        row = col.row(align=True)
        row.label(text='Bake')
        row.prop(s, 'bake_ao')
        row.prop(s, 'curvature')
        if s.curvature or (s.denoise and s.dn_method == 'FILTER' and s.dn_curv_mode != 'OFF'):  # Denoise reads it too
            col.prop(s, 'curv_width')
        row = col.row(align=True)
        row.label(text='Run In')
        row.prop(s, 'run_mode', expand=True)
        col = box.column(align=True)  # the selection is baked (Masters selects by state)
        row = col.row(align=True)
        row.enabled = s.bake_ao or s.curvature
        row.operator('fss.ao_bake_start', text=f'Bake Selected ({len(context.selected_objects)})',
                     icon='RENDER_STILL').scope = 'AUTO'
        if st.report:
            _lines(box.column(align=True), st.report, 'INFO')
        box = layout.box()
        box.label(text='Apply', icon='TEXTURE')
        if not st.refreshed:
            box.label(text='Refresh first', icon='INFO')
            return
        sel = selected_sets(context)
        if sel is not None:
            box.label(text=f'Texture sets of the selection: {len(sel)} (none selected: all)', icon='RESTRICT_SELECT_OFF')
        box.template_list('FSS_UL_AOSets', '', st, 'sets', st, 'active_set', rows=4)
        material = apply_material(context, st)
        problem = ''
        if material is None:
            box.label(text='Pick a texture set in the list', icon='INFO')
        else:
            a = material.fss_ao_apply
            sub = box.column(align=True)
            sub.label(text=f'Texture set: {material.name}', icon='MATERIAL')
            orm = apply_mod.orm_image(material)
            problem = target_problem(context, material)
            sub.prop(s, 'apply_ao', text='AO')
            if s.apply_ao:
                ind = sub.row()
                ind.separator(factor=2.0)
                col = ind.column(align=True)
                row = col.row(align=True)
                row.label(text='Target')
                row.prop(a, 'target', expand=True)
                if a.target == 'ORM':
                    if orm is not None:
                        col.label(text=f'ORM texture: {orm.name}', icon='IMAGE_DATA')
                    if not problem:
                        col.label(text='Red is written; green and blue kept')
                        if orm.depth and orm.depth < 48 and not orm.is_float:
                            col.label(text='8-bit file: written as 16-bit, green and blue kept', icon='ERROR')
                        col.label(text='The next ORM export from Substance replaces red again', icon='ERROR')
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
            sub.prop(s, 'apply_cm', text='Curvature Map')
            if s.apply_cm:  # decision 54
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
        ticked, blocked = apply_check(context)
        row = box.row(align=True)
        row.enabled = (s.apply_ao or s.apply_cm) and bool(ticked) and not blocked
        row.operator('fss.ao_apply', text=f'Apply Selected ({len(context.selected_objects)} objects, '
                     f'{len(ticked)} sets)', icon='TEXTURE').scope = 'SELECTED'
        if not context.selected_objects:
            box.label(text='Select the objects to apply', icon='INFO')
        elif not ticked:
            box.label(text="None of the selection's texture sets is ticked", icon='INFO')
        for name, problem in blocked[:4]:
            box.label(text=f'{name}: {problem}', icon='ERROR')
        if len(blocked) > 4:
            box.label(text=f'and {len(blocked) - 4} more sets that cannot be written', icon='BLANK1')
        if blocked:
            box.label(text='Untick them, or fix their target', icon='BLANK1')
        if st.apply_report:
            _lines(box.column(align=True), st.apply_report, 'INFO')


@persistent
def _on_load_post(*_args):
    store._state.update(items={}, by_object={}, excluded={}, sets={}, refreshed=None, folder=None)
    try:
        wm = bpy.context.window_manager
        st = wm.fss_ao_bake_state
        st.refreshed = False
        st.applying = False  # a file load ends a running Apply's modal operator
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
           FSS_OT_AOCustomOccluders, FSS_OT_AOApply, FSS_OT_AOApplyCancel, FSS_UL_AOSets, FSS_UL_AOOccluders, FSS_PT_AOBake)


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


def unregister():
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    if bpy.app.timers.is_registered(_poll_timer):
        bpy.app.timers.unregister(_poll_timer)
    del bpy.types.WindowManager.fss_ao_bake_state
    del bpy.types.Object.fss_ao_bake
    del bpy.types.Mesh.fss_ao_shared
    del bpy.types.Material.fss_ao_apply
    del bpy.types.Scene.fss_ao_bake
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
