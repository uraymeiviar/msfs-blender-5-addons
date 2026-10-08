from os import path
from xml.etree import ElementTree

from .bitmap_config import (
    BitmapSlots,
    BitmapConfig
)

BMP_CONFIG_NODETAG = "BitmapConfiguration"
BMP_SLOT_NODETAG = "BitmapSlot"
EXTRA_FLAG_NODETAG = "UserFlags"
NO_ALPHA_NODETAG = "ForceNoAlpha"

class XmlSerializer:
    """ 
        Class holding an xmlPath and its xmlData tree, 
        with a xmlBmpConfig corresponding to the xml traduction, 
        and a modifiable bmpConfig 
    """

    def __init__(self, path: str = ""):
        self.xml_path = path
        self.bmp_config = BitmapConfig()
        self.xml_bmp_config = BitmapConfig()
        self.xml_data = None

    def is_dirty(self):
        """ 
            Tells if there is a difference between xml configs and modified config 
        """
        return not self.bmp_config.compare(self.xml_bmp_config)

    def reconcile(self):
        """ 
            Reload the xml configuration in the modifiable config 
            (also return true if there were already the same) 
        """
        if not self.is_dirty() :
            return True

        self.bmp_config.copy(self.xml_bmp_config)
        return False

    def parse_xml_tree(self):
        """ 
            Return false if the xml format is wrong 
        """
        try :
            self.xml_data = ElementTree.parse(self.xml_path)
        except ElementTree.ParseError:
            print("[ERROR] Fail at parsing xml")
            return False

        # Verify root node
        root_node = self.xml_data.getroot()
        if root_node.tag != BMP_CONFIG_NODETAG:
            print("[ERROR] Wrong root node name.")
            return False

        # Get bitmap node (mandatory)
        bmp_slot_node = root_node.find(BMP_SLOT_NODETAG)
        if bmp_slot_node is None:
            print("[ERROR] No mandatory bmp mat node found.")
            return False

        bmp_slot = bmp_slot_node.text
        if bmp_slot is None:
            print("[ERROR] Empty bmp mat node.")
            return False

        # Get user flags (optionnal)
        user_flag_node = root_node.find(EXTRA_FLAG_NODETAG)
        user_flags = ""
        if user_flag_node is not None:
            user_flags = user_flag_node.text

        # Get ForceNoAlpha (non defined if false)
        no_alpha_node = root_node.find(NO_ALPHA_NODETAG)
        no_alpha = False
        if no_alpha_node is not None:
            no_alpha = (no_alpha_node.text.lower() == "true") or (no_alpha_node.text == "1")

        # Save xml values
        flag_index = BitmapSlots.get_index_from_flag(bmp_slot)
        if flag_index is None:
            print(f"[ERROR] Flag {bmp_slot}not Found in BitmapSlots.")
            return False
        self.xml_bmp_config = BitmapConfig(
            material_bitmap=flag_index, 
            user_flags=user_flags, 
            force_no_alpha=no_alpha
        )
        return True

    def update_xml_tree(self):
        """ 
            Write the bmpConfig in the xml tree,
            Update the xml config
            and create the tree if needed 
        """
        self.xml_bmp_config.copy(self.bmp_config)

        # Bitmap configuration
        if self.xml_data is None:
            self.xml_data = ElementTree.ElementTree(
                ElementTree.Element(BMP_CONFIG_NODETAG)
            )

        root_node = self.xml_data.getroot()

        # Bitmap slot
        bmp_node = root_node.find(BMP_SLOT_NODETAG)
        if bmp_node is None:
            bmp_node = ElementTree.SubElement(
                root_node, 
                BMP_SLOT_NODETAG
            )

        bmp_node.text = BitmapSlots.get_flag_from_index(self.bmp_config.material_bitmap)

        # User flags
        user_node = root_node.find(EXTRA_FLAG_NODETAG)
        if self.bmp_config.user_flags != "":
            if user_node is None:
                user_node = ElementTree.SubElement(
                    root_node, 
                    EXTRA_FLAG_NODETAG, 
                    {"Type": "_DEFAULT"}
                )
            user_node.text = self.bmp_config.user_flags
        else:
            if user_node is not None:
                root_node.remove(user_node)

        # Force no alpha
        no_alpha_node = root_node.find(NO_ALPHA_NODETAG)
        if no_alpha_node is None:
            if self.bmp_config.force_no_alpha:
                no_alpha_node = ElementTree.SubElement(root_node, NO_ALPHA_NODETAG)
                no_alpha_node.text = "true"
        else:
            root_node.remove(no_alpha_node)

    def open(self, xml_path=None):
        """ 
            Return False if the file can't be opened (or wrong format) 
        """
        if xml_path is not None :
            self.xml_path = xml_path

        # Check path
        if not path.exists(self.xml_path):
            return False

        # Parse xml
        if not self.parse_xml_tree():
            return False

        # Update modifiable bitmap config
        self.reconcile()
        return True

    def save(self, xml_path=None):
        """ 
            Write the xml file on disc 
        """

        # Use the parameter (needed to change the writing path for example)
        if xml_path is not None:
            self.xml_path = xml_path

        # Check path
        if self.xml_path is None or self.xml_path == "":
            print("[TEXTURELIB][ERROR] Path for saving is empty.")
            return False

        # Update the xml with bmpConfig before writing
        self.update_xml_tree()
        if self.xml_data is None:
            print("[ERROR] Xml data to save is empty.")
            return False

        # Write the file
        try :
            with open(self.xml_path, 'wb') as file:
                self.xml_data.write(file, encoding="utf-8")
        except IOError:
            print("[ERROR] Error while writing the file.")
            return False
        return True
