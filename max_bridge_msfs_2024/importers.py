from enum import Enum
import json

from max_bridge_msfs_2024.common import path_utils, ui_utils
from max_bridge_msfs_2024.common.usd_import import GenericUSDImporter
from max_bridge_msfs_2024.msfs_2024.usd_import import MSFS2024USDImporter


class BridgeImporters(Enum):

    generic = "GenericUSDExporter", GenericUSDImporter
    msfs_2024 = "MSFS2024USDExporter", MSFS2024USDImporter

    def supported_exporter(self) -> str:

        return self.value[0]
        

    def importer_class(self)->GenericUSDImporter:
        
        return self.value[1]

def import_bridge_usd(usd_path:str):
    """Import bridge usd using correct importer.

    Args:
        usd_path: absolute usd path.
    """
    json_data :dict= {}
    json_path = path_utils.get_associated_json(usd_path)
    with open(json_path, "r", encoding="utf-8") as file:
        json_data = json.load(file)

    exporter_name = json_data.get("exporter",None)
    from_dcc_name = json_data.get("from_dcc",None)

    importer_class = None
    for imp in BridgeImporters:
        _imp_class = imp.importer_class()
        if imp.supported_exporter() == exporter_name and _imp_class.TARGET_DCC == from_dcc_name:
            importer_class = _imp_class
    
    if not importer_class:
        ui_utils.message_popup(
                ui_utils.PopUpLevel.CRITICAL,
                title="Import Error",
                message="No importer found for this USD.",
            )
        return
    importer_class.import_usd(usd_path)
