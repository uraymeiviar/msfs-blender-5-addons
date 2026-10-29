"""Tags: generic labels on objects, so grouping does not need Blender collections.

A tag is any name the artist chooses. Tags are stored on the object as the custom property "fss_tags", a
semicolon-separated string, so they stay readable and editable in Blender without this add-on (Object Properties >
Custom Properties). Nothing is inferred: an object has exactly the tags someone gave it.
Rules and decisions: codes/wasm/doc/journal/20261014.fss-blender-tools-tags-and-merge.md (FSS repository).
"""

import bpy

TAGS_KEY = "fss_tags"
SEPARATOR = ";"


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
    bl_description = 'Keep tagged objects and their Auto ancestor chains against size culling'
    bl_options = {'REGISTER', 'UNDO'}

    tag: bpy.props.StringProperty(name='Tag')

    def execute(self, context):
        current = get_keep_tags(context.scene)
        set_keep_tags(context.scene, [tag for tag in current if tag != self.tag]
                      if self.tag in current else current + [self.tag])
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
        box = layout.box()
        if obj is None:
            box.label(text="No active object", icon='INFO')
        else:
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
            column = layout.column(align=True)
            for tag in sorted(counts):
                skipped = tag in skip_tags
                tag_row = column.row(align=True)

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

                tag_row.operator(FSS_OT_TagSelect.bl_idname, text="", icon='RESTRICT_SELECT_OFF').tag = tag
                name_sub = tag_row.row(align=True)
                name_sub.alignment = 'LEFT'
                name_sub.operator(
                    FSS_OT_TagSelect.bl_idname,
                    text=f"{tag} ({counts[tag]})",
                    emboss=False,
                ).tag = tag
                tag_row.label(text="")

                op = tag_row.operator(
                    FSS_OT_TagToggleSkipMerge.bl_idname, text="",
                    icon='AUTOMERGE_OFF' if skipped else 'AUTOMERGE_ON',
                    depress=skipped,
                )
                op.tag = tag
                tag_row.operator('fss.tag_toggle_keep', text='Keep', depress=tag in keep_tags).tag = tag
                tag_row.operator(FSS_OT_TagRename.bl_idname, text="", icon='GREASEPENCIL').tag = tag
                tag_row.operator(FSS_OT_TagDelete.bl_idname, text="", icon='TRASH').tag = tag
        else:
            layout.label(text="No tags in this file")


CLASSES = (
    FSS_OT_TagAdd,
    FSS_OT_TagRemove,
    FSS_OT_TagSelect,
    FSS_OT_TagToggleSkipMerge,
    FSS_OT_TagToggleKeep,
    FSS_OT_TagRename,
    FSS_OT_TagDelete,
    FSS_PT_Tags,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.fss_tag_name = bpy.props.StringProperty(
        name="Tag", description="Tag to add or remove (several: separate with ;)")


def unregister():
    del bpy.types.Scene.fss_tag_name
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
