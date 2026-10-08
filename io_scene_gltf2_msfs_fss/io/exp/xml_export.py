from __future__ import annotations
from typing import TYPE_CHECKING

import uuid
import os
import xml.etree.ElementTree as ET
import xml.dom.minidom
from enum import Enum

from _addons_common import p4, file_info


from ..com import msfs_logs

if TYPE_CHECKING:
    from .lod_groups import MultiExporterLODGroup, MultiExporterLOD


class XMLTags(Enum):
    ROOT = "ModelInfo"
    LODS = "LODS"

    def __init__(self, tag):
        self.tag = tag


class RootAttribs(Enum):
    GUID = ("guid", None)
    VERSION = ("version", "1.1")

    def __init__(self, key, description):
        self.key: str = key
        self.defaut_value: str = description


class LODSAttribs(Enum):
    AUTOGENERATE = ("autoGenerate", "true")

    def __init__(self, key, description):
        self.key: str = key
        self.defaut_value: str = description


def _generate_guid() -> str:
    return "{" + str(uuid.uuid4()) + "}"


def _get_lod_group_xml_export_name(lod_group: MultiExporterLODGroup) -> str:
    """
    Return lod group xml name with .xml extension
    """
    # Remove .001 suffix
    return os.path.splitext(lod_group.name)[0] + ".xml"


def _get_lod_export_name(lod: MultiExporterLOD) -> str:
    """
    Return lod name with .gltf extension
    """
    return os.path.splitext(lod.file_name)[0] + ".gltf"


def _clear_elem_children(elem: ET.Element):
    for child in list(elem):
        elem.remove(child)


def _set_root_guid(root: ET.Element, guid: str | None = None):
    if guid is None:
        guid = _generate_guid()
    root.set(RootAttribs.GUID.key, guid)


def _set_root_version(
    root: ET.Element, version: str = RootAttribs.VERSION.defaut_value
):
    root.set(RootAttribs.VERSION.key, version)


def _create_root_element() -> ET.Element:
    root = ET.Element(XMLTags.ROOT.tag)
    _set_root_guid(root)
    _set_root_version(root)
    return root


def _create_lods_root_element(
    root: ET.Element, autogenerate_lods: bool = False
) -> ET.Element:
    lods = ET.SubElement(root, XMLTags.LODS.tag)
    if autogenerate_lods:
        lods.set(LODSAttribs.AUTOGENERATE.key, LODSAttribs.AUTOGENERATE.defaut_value)
    return lods


def _populate_lods_root(
    lod_group: MultiExporterLODGroup, export_path: str, lods_root_elem: ET.Element
):
    # Get lods infos, only keep lod entry corresponding to an existing gltf
    lod_infos = _get_lods_export_infos(lod_group, export_path)
    lod_infos = lod_infos.items()
    last_lod = list(lod_infos)[-1:]
    for filename, lod_value in lod_infos:
        lod_elem = ET.SubElement(lods_root_elem, "LOD")

        if filename != last_lod[0]:
            lod_elem.set("minSize", str(lod_value))

        lod_elem.set("ModelFile", filename)


def _get_lods_export_infos(
    lod_group: MultiExporterLODGroup, export_path: str
) -> dict[str, float]:
    """Construct a dict of lod export paths that exist on disk.
    Value corresponds to lod min size
    """

    lod_files = {}
    for lod in lod_group.lods:
        # Remove .001 suffix
        lod_name = _get_lod_export_name(lod)
        final_lod_path = os.path.join(export_path, lod_name)
        if not os.path.exists(final_lod_path):
            continue
        lod_files[lod_name] = lod.lod_value
    return lod_files


def _generate_xml_element_tree(
    lod_group: MultiExporterLODGroup, export_path: str, xml_path: str
) -> None | ET.Element:

    MSFS2024_LOGGER = msfs_logs.get_logger()
    # Get xml root
    root: None | ET.Element = None
    if os.path.exists(xml_path):
        try:
            tree = ET.parse(xml_path)
        except:
            MSFS2024_LOGGER.error(
                message=f"'{lod_group.name}' : Fail to parse xml",
                details=(
                    f"Existing xml couldn't be parsed: \n"
                    f"{xml_path}\n"
                    "Check if xml is correctly formatted"
                ),
            )
            return None
        root = tree.getroot()

    if root is None:
        # Create root
        root = _create_root_element()
        lods_root_elem = _create_lods_root_element(root, lod_group.autogenerate_lods)
        _populate_lods_root(lod_group, export_path, lods_root_elem)
        return root

    # Check if existing root is valid
    if not root.tag == XMLTags.ROOT.tag:
        MSFS2024_LOGGER.error(
            message="XML root tag is invalid!",
            details=(
                f"Tag is {root.tag} instead of {XMLTags.ROOT.tag}\n"
                f"Path : {xml_path}"
            ),
        )
        return None

    found_guid = root.get("guid", None)

    # Set guid attribute if it doesn't exist or if overwrite is enabled
    if (
        root.get(RootAttribs.GUID.key, None) is None
        or found_guid is None
        or lod_group.overwrite_guid
    ):
        _set_root_guid(root)

    # Set version attribute
    version_attrib = root.get(RootAttribs.VERSION.key, None)
    if version_attrib is None:
        _set_root_version(root)

    # check if LODs sub element exists
    lods_root_elem = root.find(XMLTags.LODS.tag)
    if lods_root_elem is None:
        # Existing xml doesnt have a lods element
        lods_root_elem = _create_lods_root_element(root, lod_group.autogenerate_lods)
        if lod_group.autogenerate_lods:
            return root

        _populate_lods_root(lod_group, export_path, lods_root_elem)
        return root
   
    if lod_group.autogenerate_lods:
        autogenerate_attrib = lods_root_elem.get(LODSAttribs.AUTOGENERATE.key, None)
        if autogenerate_attrib is None:
            # Enable autogenerate on an xml that was not in autogenerate lod mode
            lods_root_elem.set(
                LODSAttribs.AUTOGENERATE.key, LODSAttribs.AUTOGENERATE.defaut_value
            )
            _clear_elem_children(lods_root_elem)
            return root

        # Existing Xml is valid, we keep intact
        return None
    else:
        # Make sure that there is no autogenerate attrib
        try:
            lods_root_elem.attrib.pop(LODSAttribs.AUTOGENERATE.key)
        except KeyError:
            pass
        _clear_elem_children(lods_root_elem)
        _populate_lods_root(lod_group, export_path, lods_root_elem)
        return root

    return None


def _save_xml(root: ET.Element, xml_path: str):
    """
    Create xml using provided Element Tree root.
    """
    MSFS2024_LOGGER = msfs_logs.get_logger()
    # Format XML
    dom = xml.dom.minidom.parseString(ET.tostring(root))
    xml_string = dom.toprettyxml(encoding="utf-8")
    # Remove empty lines
    xml_string = b"\n".join(line for line in xml_string.splitlines() if line.strip())
    xml_base_name = os.path.basename(xml_path)
    # Checkout File
    if p4.USE_P4 and not p4.p4_session_edit(xml_path):
        MSFS2024_LOGGER.error(
            message=f"'{xml_base_name}' : Could not be opened for edit.",
        )

    xml_read_only = file_info.is_read_only(xml_path)

    if xml_read_only:
        MSFS2024_LOGGER.error(
            message=f"'{xml_base_name}' : File is read-only.",
            details=(
                "Disable the read-only attribute to make the file writable:\n"
                + xml_path
            ),
        )
        return

    try:
        with open(xml_path, "wb") as f:
            f.write(xml_string)
            f.close()
    except IOError:
        MSFS2024_LOGGER.error(
            message=f"'{xml_base_name}' : Could not be opened.",
            details=(f"Access Denied:\n{xml_path}\n" "XML will not be written"),
        )


def generate_xml(lod_group: MultiExporterLODGroup, export_path: str):

    xml_name = _get_lod_group_xml_export_name(lod_group)
    xml_path = os.path.join(export_path, xml_name)
    root = _generate_xml_element_tree(lod_group, export_path, xml_path)

    if root is not None:
        _save_xml(root, xml_path)
