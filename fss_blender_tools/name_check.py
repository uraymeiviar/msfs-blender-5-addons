"""Name check: lists objects and bones whose names break the FSS naming rules and renames them in one batch.

The Blender object name becomes the glTF node name, and the model XML, .cfg files and attachments find nodes by that
exact name. This check does not read the MSFS project: it cannot know which names the project refers to, so suffix
collisions and default names are only reported, and every proposal can be edited or unticked before applying.
Rules and decisions: codes/wasm/doc/journal/20261011.fss-blender-tools-name-check.md (FSS repository).
"""

import re

import bpy

from .merge import PREFIX as MERGE_PREFIX

SUFFIX = re.compile(r"^(.*)\.(\d{3,})$")
# Asobo LOD prefix (x0_, x1_ ...), matched case-insensitively by the multi-exporter; kept as written
LOD_PREFIX = re.compile(r"^x[0-9]_")
ILLEGAL_CHARS = re.compile(r"[^A-Za-z0-9_]+")
DEFAULT_BASES = (
    "Area", "Armature", "BezierCircle", "BezierCurve", "Bone", "Camera", "Circle", "Cone", "Cube", "Curve",
    "Cylinder", "Empty", "Grid", "Icosphere", "Lattice", "Light", "Mball", "Mesh", "NurbsCircle", "NurbsCurve",
    "NurbsPath", "Plane", "Point", "Speaker", "Sphere", "Spot", "Sun", "Suzanne", "Text", "Torus",
)
DEFAULT_NAME = re.compile(r"^(?:" + "|".join(DEFAULT_BASES) + r")$", re.IGNORECASE)

RULES = (
    ("SUFFIX", "Suffix", "Ends in .NNN and the name without it is free: the suffix is removed"),
    ("COLLISION", "Collision", "Ends in .NNN and the name without it is taken: report only, rename by hand"),
    ("CASE", "Case", "Contains lower-case letters: upper-cased"),
    ("CHARS", "Characters", "Contains characters other than A-Z, 0-9 and _: replaced with _"),
    ("DEFAULT", "Default", "Blender default name: report only, rename by hand"),
    ("TAKEN", "Taken", "The proposed name is already used: edit the proposal or rename the other item first"),
)
RULE_TAGS = {"SUFFIX": "SFX", "COLLISION": "COL", "CASE": "CASE", "CHARS": "CHR", "DEFAULT": "DEF", "TAKEN": "TKN"}


def _suffix_number(name):
    return int(SUFFIX.match(name).group(2))


def check_names(names, taken):
    """Checks the names of one namespace (all objects, or the bones of one armature).

    Returns {name: (rules, proposal)} for every name that breaks a rule; proposal equals the name when the tool has
    nothing to propose. taken holds every name of the namespace, including ones that are not checked.
    """
    # A free base name goes to the lowest-numbered copy; the other copies collide with it once it is renamed
    claims = {}
    for name in names:
        match = SUFFIX.match(name)
        if match and match.group(1) not in taken:
            claimant = claims.get(match.group(1))
            if claimant is None or _suffix_number(name) < _suffix_number(claimant):
                claims[match.group(1)] = name

    findings = {}
    planned = set()
    for name in sorted(names):
        rules = set()
        match = SUFFIX.match(name)
        base, suffix = (match.group(1), "." + match.group(2)) if match else (name, "")
        if suffix:
            if claims.get(base) == name:
                rules.add("SUFFIX")
                suffix = ""
            else:
                rules.add("COLLISION")

        if DEFAULT_NAME.match(base):
            rules = (rules - {"SUFFIX"}) | {"DEFAULT"}
            proposal = name
        else:
            # The merge-group marker is allowed; the rules apply to the rest of the name
            group_prefix = MERGE_PREFIX if base.startswith(MERGE_PREFIX) else ""
            fixed = ILLEGAL_CHARS.sub("_", base[len(group_prefix):])
            if fixed != base[len(group_prefix):]:
                rules.add("CHARS")
            prefix = LOD_PREFIX.match(fixed)
            prefix = prefix.group(0) if prefix else ""
            body = fixed[len(prefix):]
            if any(c.islower() for c in body):
                rules.add("CASE")
                body = body.upper()
            proposal = group_prefix + prefix + body + suffix

        if proposal != name:
            if proposal in taken or proposal in planned:
                rules.add("TAKEN")
            else:
                planned.add(proposal)
        if rules:
            findings[name] = (rules, proposal)
    return findings


def _local_objects():
    return {obj.name: obj for obj in bpy.data.objects if obj.library is None}


def _armature_object(armature):
    return next((obj for obj in bpy.data.objects if obj.data == armature), None)


def _is_pending(item):
    return (item.selected and not item.locked and "TAKEN" not in item.rules
            and item.proposed.strip() not in ("", item.name))


def scan(settings, include_bones=True):
    """Fills settings.items with the findings for every object and bone in the file; returns the number of rows."""
    settings.items.clear()
    rows = []

    object_names = [obj.name for obj in bpy.data.objects]
    findings = check_names(object_names, set(object_names))
    for obj in bpy.data.objects:
        if obj.name in findings:
            rows.append(("OBJECT", "", obj.name, findings[obj.name], obj.library is not None))

    if include_bones:
        for armature in bpy.data.armatures:
            bone_names = [bone.name for bone in armature.bones]
            findings = check_names(bone_names, set(bone_names))
            for name in bone_names:
                if name in findings:
                    rows.append(("BONE", armature.name, name, findings[name], armature.library is not None))

    rows.sort(key=lambda row: (row[0] != "OBJECT", row[1], row[2]))
    for kind, owner, name, (rules, proposal), locked in rows:
        item = settings.items.add()
        item.kind = kind
        item.owner = owner
        item.name = name
        item.proposed = proposal
        item.rules = rules
        item.locked = locked
        item.selected = not locked and proposal != name and "TAKEN" not in rules
    settings.active = 0
    settings.scanned = True
    return len(rows)


def rename(settings):
    """Renames every pending row; returns (renamed count, list of skip reasons). Never forces a taken name."""
    objects = _local_objects()
    renamed = 0
    skipped = []
    for item in settings.items:
        if not _is_pending(item):
            continue
        target = item.proposed.strip()
        if item.kind == 'OBJECT':
            obj = objects.get(item.name)
            if obj is None:
                skipped.append(f"{item.name}: object not found (renamed since the scan?)")
                continue
            if target in bpy.data.objects:
                skipped.append(f"{item.name}: {target} is already used")
                continue
            del objects[item.name]
            obj.name = target
            objects[obj.name] = obj
            actual = obj.name
        else:
            armature = bpy.data.armatures.get(item.owner)
            bone = armature.bones.get(item.name) if armature else None
            if bone is None:
                skipped.append(f"{item.owner}/{item.name}: bone not found (renamed since the scan?)")
                continue
            if armature.is_editmode:
                skipped.append(f"{item.owner}/{item.name}: armature is in Edit Mode")
                continue
            if target in armature.bones:
                skipped.append(f"{item.owner}/{item.name}: {target} is already used")
                continue
            bone.name = target
            actual = bone.name
        renamed += 1
        if actual != target:
            skipped.append(f"{item.name}: renamed to {actual}, not {target} (name too long?)")
    return renamed, skipped


def _select_item(settings, context):
    """Selects the object (or the armature and bone) of the active row, so Frame Selected can show it."""
    if not 0 <= settings.active < len(settings.items) or context.mode not in ('OBJECT', 'POSE'):
        return
    item = settings.items[settings.active]
    if item.kind == 'OBJECT':
        obj = _local_objects().get(item.name) or bpy.data.objects.get(item.name)
        bone_name = None
    else:
        armature = bpy.data.armatures.get(item.owner)
        obj = _armature_object(armature) if armature else None
        bone_name = item.name
    view_layer = context.view_layer
    if obj is None or obj.name not in view_layer.objects or not obj.visible_get(view_layer=view_layer):
        return
    if context.mode == 'POSE' and view_layer.objects.active is not obj:
        return
    if context.mode == 'OBJECT':
        for selected in context.selected_objects:
            selected.select_set(False)
        obj.select_set(True)
        view_layer.objects.active = obj
    if bone_name:
        bone = obj.data.bones.get(bone_name)
        if bone:
            obj.data.bones.active = bone
            pose_bone = obj.pose.bones.get(bone_name)
            if context.mode == 'POSE' and pose_bone is not None:
                for other in obj.pose.bones:
                    other.select = other is pose_bone


class FSS_NameCheckItem(bpy.types.PropertyGroup):
    # name (built in) holds the current name, so the list's name filter works
    kind: bpy.props.EnumProperty(items=(("OBJECT", "Object", ""), ("BONE", "Bone", "")))
    owner: bpy.props.StringProperty(description="Armature data of a bone")
    proposed: bpy.props.StringProperty(name="Proposed Name", description="Name given when the row is renamed")
    rules: bpy.props.EnumProperty(items=RULES, options={'ENUM_FLAG'})
    selected: bpy.props.BoolProperty(name="Rename", description="Rename this item with Rename Selected")
    locked: bpy.props.BoolProperty(description="Linked from a library; cannot be renamed here")


def _on_active_changed(settings, context):
    _select_item(settings, context)


class FSS_NameCheckSettings(bpy.types.PropertyGroup):
    items: bpy.props.CollectionProperty(type=FSS_NameCheckItem)
    active: bpy.props.IntProperty(update=_on_active_changed)
    scanned: bpy.props.BoolProperty()
    include_bones: bpy.props.BoolProperty(name="Bones", default=True, description="Also check bone names")
    show_rules: bpy.props.EnumProperty(
        name="Show", items=RULES, options={'ENUM_FLAG'}, default={rule[0] for rule in RULES},
        description="Rules whose findings are listed",
    )


class FSS_UL_NameCheck(bpy.types.UIList):
    bl_idname = "FSS_UL_name_check"

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        toggle = row.row(align=True)
        toggle.enabled = not item.locked and item.proposed.strip() != item.name
        toggle.prop(item, "selected", text="")
        split = row.split(factor=0.5, align=True)
        if item.locked:
            item_icon = 'LIBRARY_DATA_DIRECT'
        else:
            item_icon = 'BONE_DATA' if item.kind == 'BONE' else 'OBJECT_DATA'
        label = f"{item.owner}: {item.name}" if item.kind == 'BONE' else item.name
        split.label(text=label, icon=item_icon)
        field = split.row(align=True)
        field.enabled = not item.locked
        field.prop(item, "proposed", text="")
        row.label(text=" ".join(RULE_TAGS[rule] for rule in sorted(item.rules)))

    def filter_items(self, context, data, propname):
        items = getattr(data, propname)
        helper = bpy.types.UI_UL_list
        if self.filter_name:
            flags = helper.filter_items_by_name(self.filter_name, self.bitflag_filter_item, items, "name")
        else:
            flags = [self.bitflag_filter_item] * len(items)
        shown = data.show_rules
        for index, item in enumerate(items):
            if not item.rules & shown:
                flags[index] = 0
        order = helper.sort_items_by_name(items, "name") if self.use_filter_sort_alpha else []
        return flags, order


class FSS_OT_NameCheckScan(bpy.types.Operator):
    bl_idname = "fss.name_check_scan"
    bl_label = "Scan Names"
    bl_description = "List every object and bone whose name breaks the naming rules"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        settings = context.scene.fss_name_check
        count = scan(settings, settings.include_bones)
        self.report({'INFO'}, f"Name check: {count} finding(s)")
        return {'FINISHED'}


class FSS_OT_NameCheckRename(bpy.types.Operator):
    bl_idname = "fss.name_check_rename"
    bl_label = "Rename Selected"
    bl_description = "Rename every ticked row to its proposed name, then scan again"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return any(_is_pending(item) for item in context.scene.fss_name_check.items)

    def execute(self, context):
        settings = context.scene.fss_name_check
        renamed, skipped = rename(settings)
        for reason in skipped:
            print(f"FSS name check: skipped {reason}")
        scan(settings, settings.include_bones)
        if skipped:
            self.report({'WARNING'}, f"Renamed {renamed}, skipped {len(skipped)} (see the console): {skipped[0]}")
        else:
            self.report({'INFO'}, f"Renamed {renamed}")
        return {'FINISHED'}


class FSS_OT_NameCheckSelect(bpy.types.Operator):
    bl_idname = "fss.name_check_select"
    bl_label = "Tick Rows"
    bl_description = "Tick or untick every row that has a proposal and is shown by the rule filter"
    bl_options = {'REGISTER', 'UNDO'}

    tick: bpy.props.BoolProperty(default=True)

    def execute(self, context):
        settings = context.scene.fss_name_check
        for item in settings.items:
            if item.rules & settings.show_rules and not item.locked and item.proposed.strip() != item.name:
                item.selected = self.tick
        return {'FINISHED'}


class FSS_PT_NameCheck(bpy.types.Panel):
    bl_idname = "FSS_PT_name_check"
    bl_label = "Name Check"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "FSS Tools"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.fss_name_check
        row = layout.row(align=True)
        row.operator(FSS_OT_NameCheckScan.bl_idname, icon='VIEWZOOM')
        row.prop(settings, "include_bones", toggle=True, icon='BONE_DATA')
        if not settings.scanned:
            return
        if not settings.items:
            layout.label(text="No naming issues found", icon='CHECKMARK')
            return

        counts = {rule[0]: 0 for rule in RULES}
        for item in settings.items:
            for rule in item.rules:
                counts[rule] += 1
        layout.label(text="  ".join(f"{RULE_TAGS[rule]} {count}" for rule, count in counts.items() if count))
        layout.row(align=True).prop(settings, "show_rules", expand=True)
        layout.template_list(FSS_UL_NameCheck.bl_idname, "", settings, "items", settings, "active", rows=12)

        row = layout.row(align=True)
        row.operator(FSS_OT_NameCheckSelect.bl_idname, text="Tick All", icon='CHECKBOX_HLT').tick = True
        row.operator(FSS_OT_NameCheckSelect.bl_idname, text="Untick All", icon='CHECKBOX_DEHLT').tick = False
        row.operator("view3d.view_selected", text="Frame", icon='ZOOM_SELECTED')
        pending = sum(1 for item in settings.items if _is_pending(item))
        layout.operator(FSS_OT_NameCheckRename.bl_idname, text=f"Rename Selected ({pending})", icon='SORTALPHA')


CLASSES = (
    FSS_NameCheckItem,
    FSS_NameCheckSettings,
    FSS_UL_NameCheck,
    FSS_OT_NameCheckScan,
    FSS_OT_NameCheckRename,
    FSS_OT_NameCheckSelect,
    FSS_PT_NameCheck,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.fss_name_check = bpy.props.PointerProperty(type=FSS_NameCheckSettings)


def unregister():
    del bpy.types.Scene.fss_name_check
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
