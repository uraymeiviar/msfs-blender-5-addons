"""
Asobo Macro Lights are deprecated in MSFS2024.
They are replaced by street lights on gltf import.
"""

from . import asobo_street_light

class DeprecatedAsoboMacroLight(asobo_street_light.AsoboStreetLight):
    extension_name = "ASOBO_macro_light"