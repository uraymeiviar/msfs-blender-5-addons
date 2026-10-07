"""
This module contains function wrappers for the built-in glTF exporter.

These wrappers monkey-patch internal exporter functions because no
appropriate public hooks are currently provided by the glTF addon.

This approach is fragile and version-dependent, and should be used
only as a last resort.

Be carrefull, these wrappers are not correctly reloaded at runtime. It's safer to restart
blender after updating them.
"""

from ..com.extensions import asobo_property_animation
import bpy

# Functions before patch
_original_gather_sample_object_channel = None
_original_gather_sample_bone_channel = None
_original_get_positions = None
_original_get_normals = None
_PrimitiveCreator = None
_gltf2_blender_extract = None
_original_gather_mesh = None
_nodes = None

def _msfs2020_export() -> bool:
    """
    Unified add-on: these patches implement MSFS 2024 export behaviour and are installed globally,
    so they step aside while the scene exports for MSFS 2020 (FSS MSFS 2020 pipeline parity).
    """
    from io_scene_gltf2_msfs_fss.msfs2020_target import is_msfs2020_target
    return is_msfs2020_target(bpy.context.scene)

# region Animation
def _reset_force_keep_animation(khronos_export_settings: dict):
    khronos_export_settings["gltf_optimize_animation_keep_object"] = (
        asobo_property_animation.export_cache.force_keep_obj_anim_original_value
    )
    khronos_export_settings["gltf_optimize_animation_keep_armature"] = (
        asobo_property_animation.export_cache.force_keep_bone_anim_original_value
    )

def _force_keep_animation(khronos_export_settings: dict):
    """
    Prevent an action from being skipped by the glTF addon.
    By default, Empty or constant animations are ignored 
    (see `keyframes.py` and `fcurve_is_constant()` in the glTF addon).

    Only supported since version 3.6.0
    """
    khronos_export_settings["gltf_optimize_animation_keep_object"] = True
    khronos_export_settings["gltf_optimize_animation_keep_armature"] = True

def force_keep_animation(
    obj_uuid: str,
    action_name: str,
    slot_identifier: None | str,
    channel: str,
    khronos_export_settings: dict,
    bone_name: str = "",
):
    """
    Preserve animation channels that are listed in export_cache.animations_to_force_keep.
    """

    if _msfs2020_export():
        return
    if not asobo_property_animation.export_cache:
        return
    _reset_force_keep_animation(khronos_export_settings)
    anims_to_keep = asobo_property_animation.export_cache.animations_to_force_keep.get(obj_uuid, None)
    if not anims_to_keep:
        return  
    for anim in anims_to_keep:
        if channel not in anim.channels:
            continue
        # In nla track export mode, slot identifier is always None. 
        # It's not implemented yet in builtin gltf exporter.
        # So in this case we only check if action_name matches
        # slot_identifier only works in action mode
        if (
            slot_identifier is None
            and action_name == anim.name
            and bone_name == anim.bone_name
        ) or (
            slot_identifier is not None
            and slot_identifier == anim.slot_identifier
            and action_name == anim.name
            and bone_name == anim.bone_name
        ):
            _force_keep_animation(khronos_export_settings)
            break


if bpy.app.version >= (4,5,0):           

    def msfs_gather_sampled_object_channel(
            obj_uuid: str,
            channel: str,
            action_name: str,
            slot_identifier: str | None,
            node_channel_is_animated: bool,
            node_channel_interpolation: str,
            khronos_export_settings:dict
    ):
        """
        Empty or constant animations are ignored (see `keyframes.py` and `fcurve_is_constant()` in the glTF addon),
        except when the export setting `gltf_optimize_animation_keep_object` is enabled.

        We patch `gather_sampled_object_channel` because there is no available hook that allows
        enabling `gltf_optimize_animation_keep_object` selectively for specific actions
        that must be preserved for material animations.

        The hook `gather_animation_object_sampled_channel_target_hook` is invoked just before
        channel sampling and appears suitable, but it fails in a specific case.

        This hook is called only once per object because it is executed inside the cached
        function `gather_object_sampled_channel_target(obj_uuid, channel, export_settings)`.

        As a result in blender 4.5, in Action export mode, if an object has an active action unrelated to
        material animation (i.e., the action does not share the same name), the unrelated action
        is sampled, while the placeholder action added on the NLA track for material animation
        is ignored.
        """

        force_keep_animation(
            obj_uuid, 
            action_name, 
            slot_identifier, 
            channel, 
            khronos_export_settings
        )
        global _original_gather_sample_object_channel
        return _original_gather_sample_object_channel(
            obj_uuid,
            channel,
            action_name,
            slot_identifier,
            node_channel_is_animated,
            node_channel_interpolation,
            khronos_export_settings
        )

    def msfs_gather_sampled_bone_channel(
        armature_uuid: str,
        bone: str,
        channel: str,
        action_name: str,
        slot_identifier: str,
        node_channel_is_animated: bool,
        node_channel_interpolation: str,
        khronos_export_settings
    ):  
        """Same thing that msfs_gather_sampled_object_channel but for bones.
        """
        force_keep_animation(
            armature_uuid,
            action_name,
            slot_identifier,
            channel,
            khronos_export_settings,
            bone,
        )
        global _original_gather_sample_bone_channel
        return _original_gather_sample_bone_channel(
            armature_uuid,
            bone,
            channel,
            action_name,
            slot_identifier,
            node_channel_is_animated,
            node_channel_interpolation,
            khronos_export_settings
        ) # type: ignore

elif bpy.app.version >= (3,6,0):

    def msfs_gather_sampled_object_channel(
            obj_uuid: str,
            channel: str,
            action_name: str,
            node_channel_is_animated: bool,
            node_channel_interpolation: str,
            khronos_export_settings:dict
    ):
        force_keep_animation(
            obj_uuid, 
            action_name, 
            None, 
            channel, 
            khronos_export_settings
        )
        global _original_gather_sample_object_channel
        return _original_gather_sample_object_channel(
            obj_uuid,
            channel,
            action_name,
            node_channel_is_animated,
            node_channel_interpolation,
            khronos_export_settings
        ) # type: ignore
    
    def msfs_gather_sampled_bone_channel(
            armature_uuid: str,
            bone: str,
            channel: str,
            action_name: str,
            node_channel_is_animated: bool,
            node_channel_interpolation: str,
            khronos_export_settings
    ):

        force_keep_animation(
            armature_uuid,
            action_name,
            None,
            channel,
            khronos_export_settings,
            bone,
        )
        global _original_gather_sample_bone_channel
        return _original_gather_sample_bone_channel(
            armature_uuid,
            bone,
            channel,
            action_name,
            node_channel_is_animated,
            node_channel_interpolation,
            khronos_export_settings
        ) # type: ignore
# endregion

# region Skinning
def _yup2zup(array):
    # x,z,-y ->  x,y,z
    array[:, [1, 2]] = array[:, [2, 1]]  # x,-y,z
    array[:, 1] *= -1  # x,y,z

if bpy.app.version >= (3, 6, 0):
    def msfs_get_positions(
            self
    ):  
        """Revert the matrix world offset applied to skinned meshes.
        This does not follow the glTF spec, but is required for the
        engine to correctly load skinned meshes.
        """
        global _original_get_positions

        _original_get_positions(self)

        if _msfs2020_export():
            return

        if not self.uuid_for_skined_data:
            return
        
        apply_mat_to_all = _PrimitiveCreator.apply_mat_to_all
        zup2yup = _PrimitiveCreator.zup2yup
    

        # Revert location transformation
        _yup2zup(self.locs)
        for vs in self.morph_locs:
            _yup2zup(vs)

        # Revert glTF stores deltas in morph targets
        for vs in self.morph_locs:
            vs += self.locs

        # Revert location transform
        if self.armature and self.blender_object:

            loc_transform = self.blender_object.matrix_world.inverted_safe() 

            self.locs[:] = apply_mat_to_all(loc_transform, self.locs)
            for vs in self.morph_locs:
                vs[:] = apply_mat_to_all(loc_transform, vs)

        # glTF stores deltas in morph targets
        for vs in self.morph_locs:
            vs -= self.locs

        zup2yup(self.locs)
        for vs in self.morph_locs:
            zup2yup(vs)

    def msfs_get_normals(
            self
    ):  
        """Revert the matrix world offset applied to skinned meshes.
        This does not follow the glTF spec, but is required for the
        engine to correctly load skinned meshes.
        """
        global _original_get_normals

        _original_get_normals(self)

        if _msfs2020_export():
            return

        if not self.armature and self.blender_object:
            return
        
        apply_mat_to_all = _PrimitiveCreator.apply_mat_to_all
        zup2yup = _PrimitiveCreator.zup2yup
        normalize_vecs = _PrimitiveCreator.normalize_vecs

        # Revert location transformation
        _yup2zup(self.normals)
        for ns in self.morph_normals:
            _yup2zup(ns)

        # Revert glTF stores deltas in morph targets
        for ns in self.morph_normals:
            ns += self.normals

        # Revert normals transform
        if self.armature and self.blender_object:
            apply_matrix = (self.armature.matrix_world.inverted_safe() @ self.blender_object.matrix_world)
            apply_matrix = apply_matrix.to_3x3().inverted_safe().transposed()
            normal_transform = self.armature.matrix_world.to_3x3() @ apply_matrix
            normal_transform = normal_transform.inverted_safe()

            self.normals[:] = apply_mat_to_all(normal_transform, self.normals)
            normalize_vecs(self.normals)
            for ns in self.morph_normals:
                ns[:] = apply_mat_to_all(normal_transform, ns)
                normalize_vecs(ns)
    
        for ns in [self.normals, *self.morph_normals]:
            # Replace zero normals with the unit UP vector.
            # Seems to happen sometimes with degenerate tris?
            is_zero = ~ns.any(axis=1)
            ns[is_zero, 2] = 1

        # glTF stores deltas in morph targets
        for ns in self.morph_normals:
            ns -= self.normals

        zup2yup(self.normals)
        for ns in self.morph_normals:
            zup2yup(ns)

elif bpy.app.version >= (3, 3, 0):
    def msfs_get_positions(
            blender_mesh, key_blocks, armature, blender_object, export_settings
    ):  
        """Revert the matrix world offset applied to skinned meshes.
        This does not follow the glTF spec, but is required for the
        engine to correctly load skinned meshes.
        """
        global _original_get_positions
        
        locs, morph_locs = _original_get_positions(blender_mesh, key_blocks, armature, blender_object, export_settings)

        if not armature:
            return locs, morph_locs
     
        global _gltf2_blender_extract
        apply_mat_to_all = _gltf2_blender_extract.__apply_mat_to_all
        zup2yup = _gltf2_blender_extract.__zup2yup
    
        

        # Revert location transformation
        _yup2zup(locs)
        for vs in morph_locs:
            _yup2zup(vs)

        # Revert glTF stores deltas in morph targets
        for vs in morph_locs:
            vs += locs

        # Revert location transform
        if armature and blender_object:

            loc_transform = blender_object.matrix_world.inverted_safe() 

            locs[:] = apply_mat_to_all(loc_transform, locs)
            for vs in morph_locs:
                vs[:] = apply_mat_to_all(loc_transform, vs)

        # glTF stores deltas in morph targets
        for vs in morph_locs:
            vs -= locs

        zup2yup(locs)
        for vs in morph_locs:
            zup2yup(vs)
        return locs, morph_locs
    
    def msfs_get_normals(blender_mesh, key_blocks, armature, blender_object, export_settings):
        global _original_get_normals
        
        normals, morph_normals =_original_get_normals(blender_mesh, key_blocks, armature, blender_object, export_settings)

        if not armature and blender_object:
            return normals, morph_normals
        
        global _gltf2_blender_extract
        apply_mat_to_all = _gltf2_blender_extract.__apply_mat_to_all
        zup2yup = _gltf2_blender_extract.__zup2yup
        normalize_vecs = _gltf2_blender_extract.__normalize_vecs

        # Revert location transformation
        _yup2zup(normals)
        for ns in morph_normals:
            _yup2zup(ns)

        # Revert glTF stores deltas in morph targets
        for ns in morph_normals:
            ns += normals

        # Revert normals transform
        if armature and blender_object:
            apply_matrix = (armature.matrix_world.inverted_safe() @ blender_object.matrix_world)
            apply_matrix = apply_matrix.to_3x3().inverted_safe().transposed()
            normal_transform = armature.matrix_world.to_3x3() @ apply_matrix
            normal_transform = normal_transform.inverted_safe()

            normals[:] = apply_mat_to_all(normal_transform, normals)
            normalize_vecs(normals)
            for ns in morph_normals:
                ns[:] = apply_mat_to_all(normal_transform, ns)
                normalize_vecs(ns)
    
        for ns in [normals, *morph_normals]:
            # Replace zero normals with the unit UP vector.
            # Seems to happen sometimes with degenerate tris?
            is_zero = ~ns.any(axis=1)
            ns[is_zero, 2] = 1

        # glTF stores deltas in morph targets
        for ns in morph_normals:
            ns -= normals

        zup2yup(normals)
        for ns in morph_normals:
            zup2yup(ns)

        return normals, morph_normals
# endregion


# region Object linked materials (unified add-on, both simulators)
def msfs_gather_mesh(vnode, blender_object, export_settings):
    """
    With modifiers applied, Khronos takes the materials of the evaluated mesh, which only carries the mesh data's
    materials: slots linked to the object lost their material. Blender 5 turns Auto Smooth into a modifier, so
    objects that exported correctly with Blender 4.0 or older are affected. For this object's export only, the mesh
    data gets the object's materials in those slots.
    """
    swapped = []
    if (export_settings.get("gltf_apply") and blender_object is not None and blender_object.type == "MESH"
            and blender_object.modifiers and blender_object.data.library is None):
        materials = blender_object.data.materials
        for index, slot in enumerate(blender_object.material_slots):
            if slot.link == "OBJECT" and index < len(materials) and materials[index] != slot.material:
                swapped.append((index, materials[index]))
                materials[index] = slot.material
    try:
        return _original_gather_mesh(vnode, blender_object, export_settings)
    finally:
        for index, material in swapped:
            blender_object.data.materials[index] = material
# endregion


def register():
    # Not following pep8 but import must be done in register in order to correctly patch exporter in background mode.
    global _original_gather_sample_object_channel
    global _original_gather_sample_bone_channel
    if bpy.app.version >= (4, 5, 0):
        from io_scene_gltf2.blender.exp.animation.sampled.object import channels as obj_channels
        _original_gather_sample_object_channel = obj_channels.gather_sampled_object_channel
        obj_channels.gather_sampled_object_channel = msfs_gather_sampled_object_channel

        from io_scene_gltf2.blender.exp.animation.sampled.armature import channels as bone_channels
        _original_gather_sample_bone_channel = bone_channels.gather_sampled_bone_channel
        bone_channels.gather_sampled_bone_channel = msfs_gather_sampled_bone_channel

    elif bpy.app.version >= (4, 2, 0):
        from io_scene_gltf2.blender.exp.animation.sampled.object import gltf2_blender_gather_object_channels
        _original_gather_sample_object_channel = gltf2_blender_gather_object_channels.gather_sampled_object_channel
        gltf2_blender_gather_object_channels.gather_sampled_object_channel = msfs_gather_sampled_object_channel

        from io_scene_gltf2.blender.exp.animation.sampled.armature import armature_channels
        _original_gather_sample_bone_channel = armature_channels.gather_sampled_bone_channel
        armature_channels.gather_sampled_bone_channel = msfs_gather_sampled_bone_channel

    elif bpy.app.version >= (3, 6, 0):
        from io_scene_gltf2.blender.exp.animation.sampled.object import gltf2_blender_gather_object_channels
        _original_gather_sample_object_channel = gltf2_blender_gather_object_channels.gather_sampled_object_channel
        gltf2_blender_gather_object_channels.gather_sampled_object_channel = msfs_gather_sampled_object_channel

        from io_scene_gltf2.blender.exp.animation.sampled.armature import gltf2_blender_gather_armature_channels
        _original_gather_sample_bone_channel = gltf2_blender_gather_armature_channels.gather_sampled_bone_channel
        gltf2_blender_gather_armature_channels.gather_sampled_bone_channel = msfs_gather_sampled_bone_channel

    global _original_get_positions
    global _original_get_normals
    global _PrimitiveCreator
    global _gltf2_blender_extract
    if bpy.app.version >= (4, 5, 0):
        from io_scene_gltf2.blender.exp.primitive_extract import (
            PrimitiveCreator as _PrimitiveCreator,
        )

        _original_get_positions = _PrimitiveCreator._PrimitiveCreator__get_positions
        _PrimitiveCreator._PrimitiveCreator__get_positions = msfs_get_positions
        _original_get_normals = _PrimitiveCreator._PrimitiveCreator__get_normals
        _PrimitiveCreator._PrimitiveCreator__get_normals = msfs_get_normals

    elif bpy.app.version >= (3, 6, 0):
        from io_scene_gltf2.blender.exp.gltf2_blender_gather_primitives_extract import (
            PrimitiveCreator as _PrimitiveCreator,
        )

        _original_get_positions = _PrimitiveCreator._PrimitiveCreator__get_positions
        _PrimitiveCreator._PrimitiveCreator__get_positions = msfs_get_positions
        _original_get_normals = _PrimitiveCreator._PrimitiveCreator__get_normals
        _PrimitiveCreator._PrimitiveCreator__get_normals = msfs_get_normals
    elif bpy.app.version >= (3, 3, 0):
        from io_scene_gltf2.blender.exp import (
            gltf2_blender_extract as _gltf2_blender_extract,
        )

        _original_get_positions = _gltf2_blender_extract.__get_positions
        _gltf2_blender_extract.__get_positions = msfs_get_positions
        _original_get_normals = _gltf2_blender_extract.__get_normals
        _gltf2_blender_extract.__get_normals = msfs_get_normals

    global _original_gather_mesh
    global _nodes
    if bpy.app.version >= (4, 5, 0):
        from io_scene_gltf2.blender.exp import nodes as _nodes
        _original_gather_mesh = getattr(_nodes, "__gather_mesh")
        setattr(_nodes, "__gather_mesh", msfs_gather_mesh)

def unregister():
    # Reload patched modules to undo patch
    to_reload = []

    if bpy.app.version >= (4, 5, 0):
        from io_scene_gltf2.blender.exp.animation.sampled.object import channels
        to_reload.append(channels)
        from io_scene_gltf2.blender.exp.animation.sampled.armature import channels
        to_reload.append(channels)

    elif bpy.app.version >= (4, 2, 0):
        from io_scene_gltf2.blender.exp.animation.sampled.object import gltf2_blender_gather_object_channels
        to_reload.append(gltf2_blender_gather_object_channels)
        from io_scene_gltf2.blender.exp.animation.sampled.armature import armature_channels
        to_reload.append(armature_channels)

    elif bpy.app.version >= (3, 6, 0):
        from io_scene_gltf2.blender.exp.animation.sampled.object import gltf2_blender_gather_object_channels
        to_reload.append(gltf2_blender_gather_object_channels)
        from io_scene_gltf2.blender.exp.animation.sampled.armature import gltf2_blender_gather_armature_channels
        to_reload.append(gltf2_blender_gather_armature_channels)



    primitive_extract = None
    if bpy.app.version >= (4, 5, 0):
        from io_scene_gltf2.blender.exp import primitive_extract
    elif bpy.app.version >= (3, 6, 0):
        from io_scene_gltf2.blender.exp import (
            gltf2_blender_gather_primitives_extract as primitive_extract,
        )
    elif bpy.app.version >= (3, 3, 0):
        from io_scene_gltf2.blender.exp import (
            gltf2_blender_extract as primitive_extract,
        )
    if primitive_extract:
        to_reload.append(primitive_extract)
    if _nodes is not None:
        to_reload.append(_nodes)

    if not to_reload:
        return

    for mod in to_reload:
        try:
            import importlib

            importlib.reload(mod)
        except:
            pass
