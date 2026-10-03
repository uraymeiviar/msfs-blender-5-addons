"""
THIS MODULE IS IDENTICAL IN 3DSMAX PLUGIN AND BLENDER ADDON.

USD Properties (object definitions, materials etc ).
These are used to generate .json associated with USD.
"""

from __future__ import annotations
from typing import Any
import json

from enum import Enum, IntEnum
from dataclasses import dataclass, field
from pathlib import Path

from . import path_utils

DEFAULT_EXPORT_DIR = Path.home() / "Documents/bridge_export"
NOTIMPLEMENTED = "NOTIMPLEMENTED"


class DCCNames(Enum):

    max = "3DSMAX"
    blender = "BLENDER"

class PropertyTypes(IntEnum):

    COLOR = 0
    FLOAT = 1
    INT = 2
    BOOL = 3
    TEXTURE = 4
    PATH = 5
    STRING = 6
    REAL_SIZE = 7 #float representing real life dimension. Value must be converted to meters.
    VECTOR = 8

@dataclass
class SeriazableDef:

    handle: int
    name: str

@dataclass
class ObjectDef(SeriazableDef):

    custom_properties: dict | None
    custom_class_properties : dict | None
    obj_data: str | int | None = None  # obj.data for blender / handle for instance source for 3dsmax
    type: str | None = None
    animated: bool = False

@dataclass
class LayerDef(SeriazableDef):

    custom_properties: dict | None
    parent_name: str | None
    nodes_handle: list[int]

@dataclass
class MaterialDef(SeriazableDef):

    custom_properties: dict


@dataclass
class ExportDef:
    objects: list[ObjectDef]
    layers:list[LayerDef]
    material_library: list[MaterialDef]
    custom_properties: dict = field(default_factory=lambda: {})
    path: str = ""
    from_dcc : str = ""
    target_dcc : str = ""
    exporter : str = ""

@dataclass
class BasicObjectTypes:

    NONE = "NONE"
    DUMMY = "DUMMY"
    MESH = "MESH"

_sentinel = object()

class BridgePropertiesDef(Enum):
    """
    Enum describing properties in both blender and 3dsmax.
    ( 
        Blender default Value, 
        blender attribute name of the property, 
        3dsmax attribute name of the property, 
        blender PropertyType,
        Optionnal 3dsMax default Value
    )
    """
    def __init__(
        self,
        blender_default: Any,
        blender_name: str,
        max_name: str,
        prop_type: PropertyTypes,
        max_default: Any = _sentinel,
    ):
        self.blender_default: Any = blender_default
        self.blender_name: str = blender_name
        self.max_name: str = max_name
        self.prop_type: PropertyTypes = prop_type
        if max_default is _sentinel:
            self.max_default: Any = blender_default
        else:
            self.max_default: Any = max_default


class CustomClassPropertiesDef(BridgePropertiesDef):
    """
    Abstract Enum, reimplement it to define a custom object class properties.
    ( 
        Blender default Value, 
        blender attribute name of the property, 
        3dsmax attribute name of the property, 
        blender PropertyType,
        Optionnal 3dsMax default Value
    )
    """
    def __init__(self,*args, **kwargs):
        super().__init__(*args, **kwargs)
    # PROPERTY =  "NONE", "BlenderPropertyName","3dsMaxPropertyName",PropertyTypes.STRING


class CustomObjectClasses(Enum):

    # EXAMPLE_CLASS:tuple[str,CustomClassProperties] = ("blenderClassName","3dSMaxClassName",CustomClassPropertiesDef)#placeholder do not use
    def __init__(
        self,
        blender_class_name: str,
        max_class_name: str,
        class_properties: CustomClassPropertiesDef
    ):
        self.blender_class_name: str = blender_class_name
        self.max_class_name: str = max_class_name
        self.class_properties: CustomClassPropertiesDef = class_properties

@dataclass
class CustomClassDef():
    """
    Enum describing a custom class not supported by usd.
    """
    name : str
    properties : dict 

class USDMeshAttributes(Enum):
    """
    Names of mesh color channels in USD exported by 3dsMax.
    """

    DISPLAY_COLOR = "displayColor"
    VERTEX_COLOR = "VertexColor"
    VERTEX_ALPHA = "VertexAlpha"


def get_object_definitions_from_json(json_data) -> list[ObjectDef]:
    """
    Retrieve objects definitions from json
    and cast it to a ObjectDef
    """
    object_definitions = []
    for obj_def_dict in json_data["objects"]:
        obj_def = ObjectDef(**obj_def_dict)
        object_definitions.append(obj_def)

    return object_definitions


def get_material_definitions_from_json(json_data) -> list[MaterialDef]:
    """
    Retrieve materials definitions from json
    and cast it to a ObjectDef
    """
    materials_definitions = []
    for mat_def_dict in json_data["material_library"]:
        mat_def = MaterialDef(**mat_def_dict)
        materials_definitions.append(mat_def)

    return materials_definitions

def get_layer_definitions_from_json(json_data) -> list[LayerDef]:
    """
    Retrieve layers definitions from json
    and cast it to a ObjectDef
    """
    layers_definitions = []
    for layer_def_dict in json_data["layers"]:
        layer_def = LayerDef(**layer_def_dict)
        layers_definitions.append(layer_def)

    return layers_definitions

def get_additional_custom_properties_from_json(json_data) -> dict|None:
    """
    Retrieve additional_custom_properties dict
    """
    return json_data["custom_properties"]

def create_json_from_def(export_def: ExportDef):

    json_data = json.dumps(export_def, default=vars)
    _path = path_utils.remove_file_extension(export_def.path)
    json_path = path_utils.add_file_extension(_path, "json")
    return path_utils.save_ascii_to_file(json_path, json_data)
