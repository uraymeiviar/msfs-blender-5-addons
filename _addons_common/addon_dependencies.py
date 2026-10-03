
"""
Utilities to check if addon dependencies(other addons) are loaded
"""

from __future__ import annotations

import bpy

from enum import Enum

class DependencieDefs(Enum):
    # Exemple of a dependency entry
    # GLTF_EXPORTER = ("io_scene_gltf2", "glTF 2.0 format")

    # Subclass this in your addon to define your addon dependencies

    def __init__(self, package_name: str, ui_label: str):
        self.package_name = package_name
        self.ui_label = ui_label

def _draw_dependency_warning(layout, missing_dependencies: list[DependencieDefs]):
    layout.label(text="These addons needs to be enabled:")
    for d in missing_dependencies:
        layout.label(text=f"- {d.ui_label}")


def show_dependency_warning(missing_dependencies: list[DependencieDefs]):
    bpy.context.window_manager.popup_menu(
        draw_func=lambda self, context: _draw_dependency_warning(
            self.layout, missing_dependencies
        ),
        title="Addon Dependencies",
        icon="ERROR",
    )

def get_missing_dependencies(dependencies: type[DependencieDefs]) -> list[DependencieDefs]:
    missing_dependencies = []
    for d in dependencies:
        if d.package_name not in bpy.context.preferences.addons:
            missing_dependencies.append(d)
    return missing_dependencies

def are_dependencies_loaded(dependencies: type[DependencieDefs], show_warning:bool = False) -> bool:
    """Check if dependencies are loaded and warn user with a pop up if not.
    """

    missing_dependencies = get_missing_dependencies(dependencies)
    if not missing_dependencies:
        return True
    if show_warning:
        show_dependency_warning(missing_dependencies)
    return False
