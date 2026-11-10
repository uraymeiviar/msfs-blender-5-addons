"""Tags: generic labels on objects, so grouping does not need Blender collections.

A tag is any name the artist chooses. Tags are stored on the object as the custom property "fss_tags", a
semicolon-separated string, so they stay readable and editable in Blender without this add-on (Object Properties >
Custom Properties). Nothing is inferred: an object has exactly the tags someone gave it.
Rules and decisions: codes/wasm/doc/journal/20261014.fss-blender-tools-tags-and-merge.md (FSS repository).
"""

import bpy

TAGS_KEY = "fss_tags"
SEPARATOR = ";"
AO_NO_OCCLUDER_PROP = "fss_ao_no_occluder_tags"  # scene: the tags of objects that never occlude in an AO bake
AO_SKIP_BAKE_PROP = "fss_ao_skip_bake_tags"  # scene: the tags of objects that an AO bake leaves out as targets
INVISIBLE_PROP = "fss_invisible_tags"  # scene: the tags of objects marked as invisible in MSFS; only a mark
ANIMATED_PROP = "fss_animated_tags"  # scene: the tags of objects marked as animated; only a mark
WHOLE_PROP = "fss_whole_tags"  # scene: the tags of objects whose loose pieces the LOD export never drops one by one
NO_TEXTURE_PROP = "fss_no_texture_tags"  # scene: the tags of objects that need no texture, for example gauge screens
NO_EXPORT_PROP = "fss_no_export_tags"  # scene: the tags of objects that no export writes, with their children
MARK_PROPS = (AO_NO_OCCLUDER_PROP, AO_SKIP_BAKE_PROP, INVISIBLE_PROP, ANIMATED_PROP, WHOLE_PROP, NO_TEXTURE_PROP,
              NO_EXPORT_PROP)


def get_tags(obj) -> list:
    value = obj.get(TAGS_KEY)
    if not isinstance(value, str):
        return []
    return [tag for tag in (part.strip() for part in value.split(SEPARATOR)) if tag]


def set_tags(obj, tags):
    unique = list(dict.fromkeys(tag for tag in tags if tag))
    if unique:
        obj[TAGS_KEY] = SEPARATOR.join(unique)
    elif TAGS_KEY in obj:
        del obj[TAGS_KEY]


def has_tag(obj, tag) -> bool:
    return tag in get_tags(obj)


def parse_tag_list(text) -> list:
    """Tags typed in one field, separated by ; or ,"""
    return [tag for tag in (part.strip() for part in text.replace(",", SEPARATOR).split(SEPARATOR)) if tag]


def tag_counts() -> dict:
    counts = {}
    for obj in bpy.data.objects:
        for tag in get_tags(obj):
            counts[tag] = counts.get(tag, 0) + 1
    return counts


def _editable(obj) -> bool:
    return obj.library is None and obj.override_library is None


def get_skip_tags(scene) -> list:
    merge_settings = getattr(scene, "fss_merge", None)
    if merge_settings is None:
        return []
    return parse_tag_list(merge_settings.skip_tags)


def set_skip_tags(scene, skip_tags):
    merge_settings = getattr(scene, "fss_merge", None)
    if merge_settings is None:
        return
    unique = list(dict.fromkeys(tag for tag in skip_tags if tag))
    merge_settings.skip_tags = SEPARATOR.join(unique)
    if merge_settings.scanned and hasattr(bpy.ops, "fss") and hasattr(bpy.ops.fss, "merge_refresh"):
        bpy.ops.fss.merge_refresh()


def get_keep_tags(scene):
    return parse_tag_list(scene.fss_lod_settings.keep_tags)


def set_keep_tags(scene, values):
    scene.fss_lod_settings.keep_tags = SEPARATOR.join(dict.fromkeys(values))


def get_mark_tags(scene, prop) -> list:
    return parse_tag_list(getattr(scene, prop))


def set_mark_tags(scene, prop, values):
    setattr(scene, prop, SEPARATOR.join(dict.fromkeys(values)))


def _toggle_mark_tag(scene, prop, tag):
    current = get_mark_tags(scene, prop)
    set_mark_tags(scene, prop, [other for other in current if other != tag] if tag in current else current + [tag])


def is_ao_occluder(obj, scene) -> bool:
    """For the AO bake: False when a tag of the object says it must not darken other objects."""
    return not set(get_tags(obj)).intersection(get_mark_tags(scene, AO_NO_OCCLUDER_PROP))


def is_ao_baked(obj, scene) -> bool:
    """For the AO bake: False when a tag of the object says it gets no AO of its own, or that it needs no texture to
    bake it into."""
    return not (set(get_tags(obj)).intersection(get_mark_tags(scene, AO_SKIP_BAKE_PROP)) or needs_no_texture(obj, scene))


def is_marked_invisible(obj, scene) -> bool:
    """True when a tag of the object marks it as invisible in MSFS. A mark only: the export does not read it."""
    return bool(set(get_tags(obj)).intersection(get_mark_tags(scene, INVISIBLE_PROP)))


def is_marked_animated(obj, scene) -> bool:
    """True when a tag of the object marks it as animated. A mark only: the export and the merge do not read it."""
    return bool(set(get_tags(obj)).intersection(get_mark_tags(scene, ANIMATED_PROP)))


def needs_no_texture(obj, scene) -> bool:
    """True when a tag of the object says it needs no texture."""
    return bool(set(get_tags(obj)).intersection(get_mark_tags(scene, NO_TEXTURE_PROP)))


def is_no_export(obj, scene) -> bool:
    """True when a tag of the object or of one of its parents keeps it out of every export (UV journal decision 130)."""
    marks = set(get_mark_tags(scene, NO_EXPORT_PROP))
    if not marks:
        return False
    while obj is not None:
        if marks.intersection(get_tags(obj)):
            return True
        obj = obj.parent
    return False


def is_whole(obj, scene) -> bool:
    """True when a tag of the object says that the LOD export must not drop its loose pieces one by one."""
    return bool(set(get_tags(obj)).intersection(get_mark_tags(scene, WHOLE_PROP)))


class FSS_OT_TagAdd(bpy.types.Operator):
    bl_idname = "fss.tag_add"
    bl_label = "Add Tag"
    bl_description = "Add the tag to every selected object that does not already have it"
    bl_options = {'REGISTER', 'UNDO'}

    tag: bpy.props.StringProperty(name="Tag")

    def execute(self, context):
        tags = parse_tag_list(self.tag or context.scene.fss_tag_name)
        if not tags:
            self.report({'WARNING'}, "Type a tag name first")
            return {'CANCELLED'}
        count = 0
        for obj in context.selected_objects:
            if _editable(obj):
                existing = get_tags(obj)
                if any(tag not in existing for tag in tags):
                    set_tags(obj, existing + tags)
                    count += 1
        self.report({'INFO'}, f"Tagged {count} object(s) with {', '.join(tags)}")
        return {'FINISHED'}


class FSS_OT_TagRemove(bpy.types.Operator):
    bl_idname = "fss.tag_remove"
    bl_label = "Remove Tag"
    bl_description = "Remove the tag from the selected objects that have it, or from the active object only"
    bl_options = {'REGISTER', 'UNDO'}

    tag: bpy.props.StringProperty(name="Tag")
    active_only: bpy.props.BoolProperty(options={'SKIP_SAVE'})

    def execute(self, context):
        tags = set(parse_tag_list(self.tag or context.scene.fss_tag_name))
        if not tags:
            self.report({'WARNING'}, "Type a tag name first")
            return {'CANCELLED'}
        objects = [context.active_object] if self.active_only else context.selected_objects
        count = 0
        for obj in objects:
            if obj is not None and _editable(obj) and tags & set(get_tags(obj)):
                set_tags(obj, [tag for tag in get_tags(obj) if tag not in tags])
                count += 1
        self.report({'INFO'}, f"Removed {', '.join(sorted(tags))} from {count} object(s)")
        return {'FINISHED'}


class FSS_OT_TagSelect(bpy.types.Operator):
    bl_idname = "fss.tag_select"
    bl_label = "Select Tagged"
    bl_description = "Select every object with this tag in the current view layer (Shift: add to the selection)"
    bl_options = {'REGISTER', 'UNDO'}

    tag: bpy.props.StringProperty(name="Tag")
    extend: bpy.props.BoolProperty(options={'SKIP_SAVE'})

    def invoke(self, context, event):
        self.extend = event.shift
        return self.execute(context)

    def execute(self, context):
        view_layer = context.view_layer
        if not self.extend:
            for obj in view_layer.objects:
                obj.select_set(False)
        selected = hidden = 0
        for obj in view_layer.objects:
            if has_tag(obj, self.tag):
                if obj.visible_get(view_layer=view_layer):
                    obj.select_set(True)
                    view_layer.objects.active = obj
                    selected += 1
                else:
                    hidden += 1
        message = f"Selected {selected} object(s) tagged {self.tag}"
        if hidden:
            message += f"; {hidden} hidden object(s) not selected"
        self.report({'INFO'}, message)
        return {'FINISHED'}


class FSS_OT_TagToggleSkipMerge(bpy.types.Operator):
    bl_idname = "fss.tag_toggle_skip_merge"
    bl_label = "Don't Merge Tag"
    bl_description = "Toggle skipping objects with this tag (and their subtrees) when merging"
    bl_options = {'REGISTER', 'UNDO'}

    tag: bpy.props.StringProperty(name="Tag")

    def execute(self, context):
        scene = context.scene
        current = get_skip_tags(scene)
        if self.tag in current:
            set_skip_tags(scene, [tag for tag in current if tag != self.tag])
            self.report({'INFO'}, f"Tag {self.tag}: included in merge")
        else:
            set_skip_tags(scene, current + [self.tag])
            self.report({'INFO'}, f"Tag {self.tag}: skipped by merge")
        return {'FINISHED'}


class FSS_OT_TagToggleKeep(bpy.types.Operator):
    bl_idname = 'fss.tag_toggle_keep'
    bl_label = 'Keep Tag in LODs'
    bl_description = ("Never hide objects with this tag for being small: the automatic LOD size rule leaves them, and "
                      "the Auto objects above them, in every LOD. A Hidden from or Visible from mark still wins")
    bl_options = {'REGISTER', 'UNDO'}

    tag: bpy.props.StringProperty(name='Tag')

    def execute(self, context):
        current = get_keep_tags(context.scene)
        set_keep_tags(context.scene, [tag for tag in current if tag != self.tag]
                      if self.tag in current else current + [self.tag])
        return {'FINISHED'}


class FSS_OT_TagToggleAONoOccluder(bpy.types.Operator):
    bl_idname = 'fss.tag_toggle_ao_no_occluder'
    bl_label = 'Non-AO-Occluder Tag'
    bl_description = ("Objects with this tag never darken other objects in the AO auto-bake. They can still get AO of "
                      "their own. No auto-bake exists yet: this only records the setting for it")
    bl_options = {'REGISTER', 'UNDO'}

    tag: bpy.props.StringProperty(name='Tag')

    def execute(self, context):
        _toggle_mark_tag(context.scene, AO_NO_OCCLUDER_PROP, self.tag)
        return {'FINISHED'}


class FSS_OT_TagToggleAOSkipBake(bpy.types.Operator):
    bl_idname = 'fss.tag_toggle_ao_skip_bake'
    bl_label = 'Skip-AO-Bake Tag'
    bl_description = ("Objects with this tag get no AO in the AO auto-bake. They can still darken other objects. No "
                      "auto-bake exists yet: this only records the setting for it")
    bl_options = {'REGISTER', 'UNDO'}

    tag: bpy.props.StringProperty(name='Tag')

    def execute(self, context):
        _toggle_mark_tag(context.scene, AO_SKIP_BAKE_PROP, self.tag)
        return {'FINISHED'}


class FSS_OT_TagToggleInvisible(bpy.types.Operator):
    bl_idname = 'fss.tag_toggle_invisible'
    bl_label = 'Invisible Tag'
    bl_description = ("Mark objects with this tag as invisible in MSFS. Only a mark: it changes nothing in the model "
                      "or the export")
    bl_options = {'REGISTER', 'UNDO'}

    tag: bpy.props.StringProperty(name='Tag')

    def execute(self, context):
        _toggle_mark_tag(context.scene, INVISIBLE_PROP, self.tag)
        return {'FINISHED'}


class FSS_OT_TagToggleAnimated(bpy.types.Operator):
    bl_idname = 'fss.tag_toggle_animated'
    bl_label = 'Animated Tag'
    bl_description = ("Mark objects with this tag as animated, for parts Blender has no animation for (model XML). They "
                      "are not counted as stray, and neither are the direct children of a marked empty. Only a mark: "
                      "it changes nothing in the model, the merge or the export")
    bl_options = {'REGISTER', 'UNDO'}

    tag: bpy.props.StringProperty(name='Tag')

    def execute(self, context):
        _toggle_mark_tag(context.scene, ANIMATED_PROP, self.tag)
        return {'FINISHED'}


class FSS_OT_TagToggleWhole(bpy.types.Operator):
    bl_idname = 'fss.tag_toggle_whole'
    bl_label = 'Whole Mesh Tag'
    bl_description = ("Keep the mesh of objects with this tag whole in the LODs: the export does not drop its small "
                      "loose pieces one by one. The object still leaves by the size rule or a mark, all at once")
    bl_options = {'REGISTER', 'UNDO'}

    tag: bpy.props.StringProperty(name='Tag')

    def execute(self, context):
        _toggle_mark_tag(context.scene, WHOLE_PROP, self.tag)
        return {'FINISHED'}


class FSS_OT_TagToggleNoTexture(bpy.types.Operator):
    bl_idname = 'fss.tag_toggle_no_texture'
    bl_label = 'No Texture Tag'
    bl_description = ("Objects with this tag need no texture, for example gauge screens. A material only they use leaves "
                      "By Texture Need at the next Refresh in Materials, and the AO auto-bake skips them. They can "
                      "still darken other objects. Pack does not read it yet")
    bl_options = {'REGISTER', 'UNDO'}

    tag: bpy.props.StringProperty(name='Tag')

    def execute(self, context):
        _toggle_mark_tag(context.scene, NO_TEXTURE_PROP, self.tag)
        return {'FINISHED'}


class FSS_OT_TagToggleNoExport(bpy.types.Operator):
    bl_idname = 'fss.tag_toggle_no_export'
    bl_label = 'No Export Tag'
    bl_description = ("Objects with this tag, and everything parented below them, are left out of every export (MSFS "
                      "2024 and 2020) and of the merge. For helpers that live in the file, such as the probe lights of "
                      "Visibility Scoring")
    bl_options = {'REGISTER', 'UNDO'}

    tag: bpy.props.StringProperty(name='Tag')

    def execute(self, context):
        _toggle_mark_tag(context.scene, NO_EXPORT_PROP, self.tag)
        return {'FINISHED'}


class FSS_OT_TagRename(bpy.types.Operator):
    bl_idname = "fss.tag_rename"
    bl_label = "Rename Tag"
    bl_description = "Rename the tag on every object in the file"
    bl_options = {'REGISTER', 'UNDO'}

    tag: bpy.props.StringProperty(name="Tag")
    new_name: bpy.props.StringProperty(name="New Name")

    def invoke(self, context, event):
        self.new_name = self.tag
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        new_tags = parse_tag_list(self.new_name)
        if len(new_tags) != 1:
            self.report({'WARNING'}, "Type exactly one new tag name")
            return {'CANCELLED'}
        count = 0
        for obj in bpy.data.objects:
            tags = get_tags(obj)
            if self.tag in tags and _editable(obj):
                set_tags(obj, [new_tags[0] if tag == self.tag else tag for tag in tags])
                count += 1
        skip_tags = get_skip_tags(context.scene)
        if self.tag in skip_tags:
            set_skip_tags(context.scene, [new_tags[0] if tag == self.tag else tag for tag in skip_tags])
        keep_tags = get_keep_tags(context.scene)
        if self.tag in keep_tags:
            set_keep_tags(context.scene, [new_tags[0] if tag == self.tag else tag for tag in keep_tags])
        for prop in MARK_PROPS:
            set_mark_tags(context.scene, prop, [new_tags[0] if tag == self.tag else tag
                                              for tag in get_mark_tags(context.scene, prop)])
        self.report({'INFO'}, f"Renamed {self.tag} to {new_tags[0]} on {count} object(s)")
        return {'FINISHED'}


class FSS_OT_TagDelete(bpy.types.Operator):
    bl_idname = "fss.tag_delete"
    bl_label = "Delete Tag"
    bl_description = "Remove the tag from every object in the file"
    bl_options = {'REGISTER', 'UNDO'}

    tag: bpy.props.StringProperty(name="Tag")

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        count = 0
        for obj in bpy.data.objects:
            if has_tag(obj, self.tag) and _editable(obj):
                set_tags(obj, [tag for tag in get_tags(obj) if tag != self.tag])
                count += 1
        skip_tags = get_skip_tags(context.scene)
        if self.tag in skip_tags:
            set_skip_tags(context.scene, [tag for tag in skip_tags if tag != self.tag])
        set_keep_tags(context.scene, [tag for tag in get_keep_tags(context.scene) if tag != self.tag])
        for prop in MARK_PROPS:
            set_mark_tags(context.scene, prop, [tag for tag in get_mark_tags(context.scene, prop) if tag != self.tag])
        self.report({'INFO'}, f"Removed {self.tag} from {count} object(s)")
        return {'FINISHED'}


class FSS_PT_Tags(bpy.types.Panel):
    bl_idname = "FSS_PT_tags"
    bl_label = "Tags"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "FSS MSFS Tools"
    bl_order = 2

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        row = layout.row(align=True)
        row.prop(scene, "fss_tag_name", text="", icon='BOOKMARKS')
        op_add = row.operator(FSS_OT_TagAdd.bl_idname, text="", icon='ADD')
        op_add.tag = ""
        op_rem = row.operator(FSS_OT_TagRemove.bl_idname, text="", icon='REMOVE')
        op_rem.tag = ""
        op_rem.active_only = False

        obj = context.active_object
        if obj is not None and obj.select_get():
            box = layout.box()
            tags = get_tags(obj)
            box.label(text=f"{obj.name}: {len(tags)} tag(s)", icon='OBJECT_DATA')
            for tag in tags:
                tag_row = box.row(align=True)
                tag_row.label(text=tag)
                op = tag_row.operator(FSS_OT_TagRemove.bl_idname, text="", icon='X')
                op.tag = tag
                op.active_only = True

        selected = [o for o in context.selected_objects if _editable(o)]
        has_selection = bool(selected)
        is_multi = len(selected) > 1

        counts = tag_counts()
        if counts:
            skip_tags = set(get_skip_tags(scene))
            keep_tags = set(get_keep_tags(scene))
            no_occluder_tags = set(get_mark_tags(scene, AO_NO_OCCLUDER_PROP))
            skip_bake_tags = set(get_mark_tags(scene, AO_SKIP_BAKE_PROP))
            invisible_tags = set(get_mark_tags(scene, INVISIBLE_PROP))
            animated_tags = set(get_mark_tags(scene, ANIMATED_PROP))
            whole_tags = set(get_mark_tags(scene, WHOLE_PROP))
            no_texture_tags = set(get_mark_tags(scene, NO_TEXTURE_PROP))
            no_export_tags = set(get_mark_tags(scene, NO_EXPORT_PROP))
            column = layout.column(align=True)
            for tag in sorted(counts):
                skipped = tag in skip_tags
                kept = tag in keep_tags
                # A split, so the buttons on the right do not move with the length of the tag name
                split = column.split(factor=0.37, align=True)
                tag_row = split.row(align=True)

                if has_selection:
                    can_remove = any(has_tag(o, tag) for o in selected)
                    can_add = any(not has_tag(o, tag) for o in selected)

                    sub_minus = tag_row.row(align=True)
                    sub_minus.enabled = can_remove
                    sub_minus.alert = is_multi
                    op_minus = sub_minus.operator(FSS_OT_TagRemove.bl_idname, text="", icon='REMOVE')
                    op_minus.tag = tag
                    op_minus.active_only = False

                    sub_plus = tag_row.row(align=True)
                    sub_plus.enabled = can_add
                    sub_plus.alert = is_multi
                    op_plus = sub_plus.operator(FSS_OT_TagAdd.bl_idname, text="", icon='ADD')
                    op_plus.tag = tag

                tag_row.operator(FSS_OT_TagRename.bl_idname, text="", icon='GREASEPENCIL').tag = tag
                name_sub = tag_row.row(align=True)
                name_sub.alignment = 'LEFT'
                # Filled behind the text when a selected object has the tag
                carried = any(has_tag(o, tag) for o in context.selected_objects)
                name_sub.operator(
                    FSS_OT_TagSelect.bl_idname,
                    text=f"{tag} ({counts[tag]})",
                    emboss=carried,
                    depress=carried,
                ).tag = tag

                action_row = split.row(align=True)
                action_row.alignment = 'RIGHT'
                op = action_row.operator(
                    FSS_OT_TagToggleSkipMerge.bl_idname, text="",
                    icon='AUTOMERGE_OFF' if skipped else 'AUTOMERGE_ON',
                    depress=skipped,
                )
                op.tag = tag
                action_row.operator(FSS_OT_TagToggleKeep.bl_idname, text="", icon='PINNED' if kept else 'UNPINNED',
                                    depress=kept).tag = tag
                no_occluder = tag in no_occluder_tags
                action_row.operator(FSS_OT_TagToggleAONoOccluder.bl_idname, text="",
                                    icon='GHOST_ENABLED' if no_occluder else 'GHOST_DISABLED',
                                    depress=no_occluder).tag = tag
                skip_bake = tag in skip_bake_tags
                action_row.operator(FSS_OT_TagToggleAOSkipBake.bl_idname, text="",
                                    icon='RESTRICT_RENDER_ON' if skip_bake else 'RESTRICT_RENDER_OFF',
                                    depress=skip_bake).tag = tag
                invisible = tag in invisible_tags
                action_row.operator(FSS_OT_TagToggleInvisible.bl_idname, text="",
                                    icon='HIDE_ON' if invisible else 'HIDE_OFF', depress=invisible).tag = tag
                action_row.operator(FSS_OT_TagToggleAnimated.bl_idname, text="", icon='ACTION',
                                    depress=tag in animated_tags).tag = tag
                action_row.operator(FSS_OT_TagToggleWhole.bl_idname, text="", icon='MESH_CUBE',
                                    depress=tag in whole_tags).tag = tag
                action_row.operator(FSS_OT_TagToggleNoTexture.bl_idname, text="", icon='TEXTURE',
                                    depress=tag in no_texture_tags).tag = tag
                action_row.operator(FSS_OT_TagToggleNoExport.bl_idname, text="", icon='EXPORT',
                                    depress=tag in no_export_tags).tag = tag
                action_row.separator(factor=0.5)
                action_row.operator(FSS_OT_TagDelete.bl_idname, text="", icon='TRASH').tag = tag
        else:
            layout.label(text="No tags in this file")


CLASSES = (
    FSS_OT_TagAdd,
    FSS_OT_TagRemove,
    FSS_OT_TagSelect,
    FSS_OT_TagToggleSkipMerge,
    FSS_OT_TagToggleKeep,
    FSS_OT_TagToggleAONoOccluder,
    FSS_OT_TagToggleAOSkipBake,
    FSS_OT_TagToggleInvisible,
    FSS_OT_TagToggleAnimated,
    FSS_OT_TagToggleWhole,
    FSS_OT_TagToggleNoTexture,
    FSS_OT_TagToggleNoExport,
    FSS_OT_TagRename,
    FSS_OT_TagDelete,
    FSS_PT_Tags,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.fss_tag_name = bpy.props.StringProperty(
        name="Tag", description="Tag to add or remove (several: separate with ;)")
    bpy.types.Scene.fss_ao_no_occluder_tags = bpy.props.StringProperty(name="Non-AO-Occluder Tags")
    bpy.types.Scene.fss_ao_skip_bake_tags = bpy.props.StringProperty(name="Skip-AO-Bake Tags")
    bpy.types.Scene.fss_invisible_tags = bpy.props.StringProperty(name="Invisible Tags")
    bpy.types.Scene.fss_animated_tags = bpy.props.StringProperty(name="Animated Tags")
    bpy.types.Scene.fss_whole_tags = bpy.props.StringProperty(name="Whole Mesh Tags")
    bpy.types.Scene.fss_no_texture_tags = bpy.props.StringProperty(name="No Texture Tags")
    bpy.types.Scene.fss_no_export_tags = bpy.props.StringProperty(name="No Export Tags")


def unregister():
    del bpy.types.Scene.fss_no_export_tags
    del bpy.types.Scene.fss_no_texture_tags
    del bpy.types.Scene.fss_whole_tags
    del bpy.types.Scene.fss_animated_tags
    del bpy.types.Scene.fss_invisible_tags
    del bpy.types.Scene.fss_ao_skip_bake_tags
    del bpy.types.Scene.fss_ao_no_occluder_tags
    del bpy.types.Scene.fss_tag_name
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
