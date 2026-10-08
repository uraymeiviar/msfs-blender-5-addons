from __future__ import annotations
from enum import Enum

INCORRECT_BITMAP_SLOT = "<-- incorrect/different config -->"
INCORRECT_USER_FLAG = "<-- incorrect/different userFlags -->"

class BitmapSlots(Enum):
    INCORRECT_BITMAP_SLOT = (0, INCORRECT_BITMAP_SLOT)
    MTL_BITMAP_DECAL0 = (1, "MTL_BITMAP_DECAL0")
    MTL_BITMAP_BLENDMASK = (2, "MTL_BITMAP_BLENDMASK")
    MTL_BITMAP_NORMAL = (3, "MTL_BITMAP_NORMAL")
    MTL_BITMAP_DIRT = (4, "MTL_BITMAP_DIRT")
    MTL_BITMAP_ADD_DECAL0 = (5, "MTL_BITMAP_ADD_DECAL0")
    MTL_BITMAP_ADD_NORMAL = (6, "MTL_BITMAP_ADD_NORMAL")
    MTL_BITMAP_EMISSIVE = (7, "MTL_BITMAP_EMISSIVE")
    MTL_BITMAP_DETAILDIFFUSE = (8, "MTL_BITMAP_DETAILDIFFUSE")
    MTL_BITMAP_DETAILNORMAL = (9, "MTL_BITMAP_DETAILNORMAL")
    MTL_BITMAP_WETNESS_AO = (10, "MTL_BITMAP_WETNESS_AO")
    MTL_BITMAP_METAL_ROUGH_AO = (11, "MTL_BITMAP_METAL_ROUGH_AO")
    MTL_BITMAP_DETAIL_METAL_ROUGH_AO = (12, "MTL_BITMAP_DETAIL_METAL_ROUGH_AO")
    MTL_BITMAP_ADD_METAL_ROUGH_AO = (13, "MTL_BITMAP_ADD_METAL_ROUGH_AO")
    MTL_BITMAP_OCCLUSION = (14, "MTL_BITMAP_OCCLUSION")
    MTL_BITMAP_CLEARCOATCOLORROUGHNESS = (15, "MTL_BITMAP_CLEARCOATCOLORROUGHNESS")
    MTL_BITMAP_CLEARCOATNORMAL = (16, "MTL_BITMAP_CLEARCOATNORMAL")
    MTL_BITMAP_ANISO_DIR_ROUGH = (17, "MTL_BITMAP_ANISO_DIR_ROUGH")
    MTL_BITMAP_WIPERMASK = (18, "MTL_BITMAP_WIPERMASK")
    MTL_BITMAP_WINDSHIELDDETAILNORMAL = (19, "MTL_BITMAP_WINDSHIELDDETAILNORMAL")
    MTL_BITMAP_SCRATCHESNORMAL = (20, "MTL_BITMAP_SCRATCHESNORMAL")
    MTL_BITMAP_ALPHABLENDMASK = (21, "MTL_BITMAP_ALPHABLENDMASK")
    MTL_BITMAP_IRIDESCENTTHICKNESS = (22, "MTL_BITMAP_IRIDESCENTTHICKNESS")
    MTL_BITMAP_WINDSHIELDINSECTS = (23, "MTL_BITMAP_WINDSHIELDINSECTS")
    MTL_BITMAP_WINDSHIELDINSECTSMASK = (24, "MTL_BITMAP_WINDSHIELDINSECTSMASK")
    MTL_BITMAP_DIRTOVERLAY_METAL_ROUGH_AO = (25, "MTL_BITMAP_DIRTOVERLAY_METAL_ROUGH_AO")
    MTL_BITMAP_TIREDETAILS = (26, "MTL_BITMAP_TIREDETAILS")
    MTL_BITMAP_TIREMUDNORMAL = (27, "MTL_BITMAP_TIREMUDNORMAL")
    MTL_BITMAP_DIRTOVERLAY = (28, "MTL_BITMAP_DIRTOVERLAY")

    def __init__(self, index: int, flag: str):
        self.flag = flag
        self.index = index

    @classmethod
    def from_index(cls, index: int) -> BitmapSlots | None:
        for slot in cls:
            if slot.index == index:
                return slot
        return None

    @classmethod
    def from_flag(cls, flag: str) -> BitmapSlots | None:
        for slot in cls:
            if slot.flag == flag:
                return slot
        return None
    
    @classmethod
    def get_flag_from_index(cls, index: int) -> str | None:
        slot = cls.from_index(index)
        if slot:
            return slot.flag
        return None

    @classmethod
    def get_index_from_flag(cls, flag: str) -> int | None:
        slot = cls.from_flag(flag)
        if slot:
            return slot.index
        return None
    
COMPATIBLE_SLOTS = (
    (
        BitmapSlots.MTL_BITMAP_DECAL0,
        BitmapSlots.MTL_BITMAP_ADD_DECAL0,
        BitmapSlots.MTL_BITMAP_EMISSIVE,
        BitmapSlots.MTL_BITMAP_DETAILDIFFUSE,
        BitmapSlots.MTL_BITMAP_CLEARCOATCOLORROUGHNESS,
        BitmapSlots.MTL_BITMAP_WINDSHIELDINSECTS,
        BitmapSlots.MTL_BITMAP_DIRTOVERLAY,
    ),

    (
        BitmapSlots.MTL_BITMAP_BLENDMASK,
        BitmapSlots.MTL_BITMAP_ANISO_DIR_ROUGH,
        BitmapSlots.MTL_BITMAP_ALPHABLENDMASK,
        BitmapSlots.MTL_BITMAP_WIPERMASK,
        BitmapSlots.MTL_BITMAP_IRIDESCENTTHICKNESS,
        BitmapSlots.MTL_BITMAP_WINDSHIELDINSECTSMASK,
        BitmapSlots.MTL_BITMAP_DIRTOVERLAY_METAL_ROUGH_AO,
        BitmapSlots.MTL_BITMAP_TIREDETAILS,
    ),

    (
        BitmapSlots.MTL_BITMAP_NORMAL,
        BitmapSlots.MTL_BITMAP_ADD_NORMAL,
        BitmapSlots.MTL_BITMAP_DETAILNORMAL,
        BitmapSlots.MTL_BITMAP_CLEARCOATNORMAL,
        BitmapSlots.MTL_BITMAP_WINDSHIELDDETAILNORMAL,
        BitmapSlots.MTL_BITMAP_SCRATCHESNORMAL,
    ),

    (
        BitmapSlots.MTL_BITMAP_DIRT,
    ),

    (
        BitmapSlots.MTL_BITMAP_WETNESS_AO,
        BitmapSlots.MTL_BITMAP_DETAIL_METAL_ROUGH_AO,
    ),

    (
        BitmapSlots.MTL_BITMAP_METAL_ROUGH_AO,
        BitmapSlots.MTL_BITMAP_ADD_METAL_ROUGH_AO,
    ),

    (BitmapSlots.MTL_BITMAP_DIRTOVERLAY_METAL_ROUGH_AO,),
    (BitmapSlots.MTL_BITMAP_OCCLUSION,),
    (BitmapSlots.MTL_BITMAP_CLEARCOATCOLORROUGHNESS,),
    (BitmapSlots.MTL_BITMAP_TIREMUDNORMAL,),

)

###################################################################################################

class BitmapConfig:
    """ 
        Simple struct :
        material_bitmap : int (0 is incorrect value), 
        user_flags : str, 
        force_no_alpha : bool (or None for incorrect value) 
    """
    def __init__(
        self,
        material_bitmap: int = 0,
        user_flags: str = INCORRECT_USER_FLAG,
        force_no_alpha: bool | None = None,
    ):
        if material_bitmap > len(BitmapSlots) or material_bitmap < 0:
            material_bitmap = 0
        self.material_bitmap = material_bitmap
        self.user_flags = user_flags
        self.force_no_alpha = force_no_alpha

    def to_string(self) :

        return (f"Bitmap Slot: {BitmapSlots.get_flag_from_index(self.material_bitmap)} \n "
                f"User Flags: {self.user_flags} \n "
                f"No Alpha: {str(self.force_no_alpha)}")

    def copy(self, other):
        self.material_bitmap = other.material_bitmap
        self.user_flags = other.user_flags
        self.force_no_alpha = other.force_no_alpha

    def compare(self, other: BitmapConfig):
        equal = True
        equal = equal and self.material_bitmap == other.material_bitmap
        equal = equal and self.user_flags == other.user_flags
        equal = equal and self.force_no_alpha == other.force_no_alpha
        return equal

    def is_compatible_id(self, other: BitmapConfig):

        
        if self.material_bitmap == BitmapSlots.INCORRECT_BITMAP_SLOT.index or other.material_bitmap == BitmapSlots.INCORRECT_BITMAP_SLOT.index:
            return False

        if self.material_bitmap == other.material_bitmap:
            return True
        
        slot = BitmapSlots.from_index(self.material_bitmap)
        other_slot = BitmapSlots.from_index(other.material_bitmap)
        if slot is None or other_slot is None:
            return False
        
        for compatible_index in COMPATIBLE_SLOTS:
            if (slot in compatible_index) and (other_slot in compatible_index):
                return True

        return False
