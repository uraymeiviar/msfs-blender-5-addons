from _addons_common import addon_dependencies

class AddonDependencies(addon_dependencies.DependencieDefs):
    MFS2024_EXPORTER = ("io_scene_gltf2_msfs_fss", "Microsoft Flight Simulator 2024: glTF Extension")


def are_dependencies_loaded(show_warning: bool = False) -> bool:
    return addon_dependencies.are_dependencies_loaded(AddonDependencies, show_warning)
