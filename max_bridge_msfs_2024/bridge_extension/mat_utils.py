from io_scene_gltf2_msfs_fss.blender import material as msfs_2024_material
from io_scene_gltf2_msfs_fss.blender.utils.msfs_material_utils import (
    MSFS2024_MaterialTypes,
)


def get_material_attributes_names(material_type:str)->list[str]:

    if material_type == "NONE":
        return None
    attributes = None
    match material_type:
        case MSFS2024_MaterialTypes.STANDARD.value:
            attributes = (
                msfs_2024_material.msfs_material_standard.MSFS2024_Standard.attributes
            )
        case MSFS2024_MaterialTypes.DECAL.value:
            attributes = (
                msfs_2024_material.msfs_material_geo_decal.MSFS2024_Geo_Decal.attributes
            )
        case MSFS2024_MaterialTypes.WINDSHIELD.value:
            attributes = (
                msfs_2024_material.msfs_material_windshield.MSFS2024_Windshield.attributes
            )
        case MSFS2024_MaterialTypes.PORTHOLE.value:
            attributes = (
                msfs_2024_material.msfs_material_porthole.MSFS2024_Porthole.attributes
            )
        case MSFS2024_MaterialTypes.GLASS.value:
            attributes = (
                msfs_2024_material.msfs_material_glass.MSFS2024_Glass.attributes
            )
        case MSFS2024_MaterialTypes.GEODECALFROSTED.value:
            attributes = (
                msfs_2024_material.msfs_material_geo_decal_frosted.MSFS2024_Geo_Decal_Frosted.attributes
            )
        case MSFS2024_MaterialTypes.GEODECALBLENDMASKED.value:
            attributes = (
                msfs_2024_material.msfs_material_geo_decal_blendmasked.MSFS2024_Geo_Decal_BlendMasked.attributes
            )
        case MSFS2024_MaterialTypes.CLEARCOAT.value:
            attributes = (
                msfs_2024_material.msfs_material_clearcoat.MSFS2024_Clearcoat.attributes
            )
        case MSFS2024_MaterialTypes.PARALLAXWINDOW.value:
            attributes = (
                msfs_2024_material.msfs_material_parallax.MSFS2024_Parallax.attributes
            )
        case MSFS2024_MaterialTypes.ANISOTROPIC.value:
            attributes = (
                msfs_2024_material.msfs_material_anisotropic.MSFS2024_Anisotropic.attributes
            )
        case MSFS2024_MaterialTypes.HAIR.value:
            attributes = msfs_2024_material.msfs_material_hair.MSFS2024_Hair.attributes
        case MSFS2024_MaterialTypes.SUBSURFACESCATTERING.value:
            attributes = msfs_2024_material.msfs_material_sss.MSFS2024_SSS.attributes
        case MSFS2024_MaterialTypes.INVISIBLE.value:
            attributes = (
                msfs_2024_material.msfs_material_invisible.MSFS2024_Invisible.attributes
            )
        case MSFS2024_MaterialTypes.FAKETERRAIN.value:
            attributes = (
                msfs_2024_material.msfs_material_fake_terrain.MSFS2024_Fake_Terrain.attributes
            )
        case MSFS2024_MaterialTypes.FRESNELFADE.value:
            attributes = (
                msfs_2024_material.msfs_material_fresnel_fade.MSFS2024_Fresnel_Fade.attributes
            )
        case MSFS2024_MaterialTypes.ENVIRONMENTOCCLUDER.value:
            attributes = (
                msfs_2024_material.msfs_material_environment_occluder.MSFS2024_Environment_Occluder.attributes
            )
        case MSFS2024_MaterialTypes.GHOST.value:
            attributes = (
                msfs_2024_material.msfs_material_ghost.MSFS2024_Ghost.attributes
            )
        case MSFS2024_MaterialTypes.SAIL.value:
            attributes = msfs_2024_material.msfs_material_sail.MSFS2024_Sail.attributes
        case MSFS2024_MaterialTypes.PROPELLER.value:
            attributes = (
                msfs_2024_material.msfs_material_propeller.MSFS2024_Propeller.attributes
            )
        case MSFS2024_MaterialTypes.TREE.value:
            attributes = msfs_2024_material.msfs_material_tree.MSFS2024_Tree.attributes
        case MSFS2024_MaterialTypes.VEGETATION.value:
            attributes = (
                msfs_2024_material.msfs_material_vegetation.MSFS2024_Vegetation.attributes
            )

    attributes_names = []
    if attributes:
        for attrib in attributes:
            attributes_names.append(attrib.attribute_name())
    return attributes_names
