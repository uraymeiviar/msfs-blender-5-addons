# Copyright 2023-2024 The glTF-Blender-IO-MSFS2024 authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

INCORRECT_BITMAP_SLOT = "<-- incorrect/different config -->"
INCORRECT_USER_FLAG = "<-- incorrect/different userFlags -->"


# List of texture bitmap slots, with index 0 beeing incorrect value  
BITMAP_SLOTS = [
    INCORRECT_BITMAP_SLOT,
    "MTL_BITMAP_DECAL0",					# 1 # False
    "MTL_BITMAP_BLENDMASK",					# 2 # False
    "MTL_BITMAP_NORMAL",					# 3 # False
    "MTL_BITMAP_DIRT",						# 4 # NOT USED
    "MTL_BITMAP_ADD_DECAL0",				# 5 # False
    "MTL_BITMAP_ADD_NORMAL",				# 6 # False
    "MTL_BITMAP_EMISSIVE",					# 7 # False
    "MTL_BITMAP_DETAILDIFFUSE",				# 8 # False
    "MTL_BITMAP_DETAILNORMAL",				# 9 # False
    "MTL_BITMAP_WETNESS_AO",				# 10 # NOT USED
    "MTL_BITMAP_METAL_ROUGH_AO",			# 11 # True
    "MTL_BITMAP_DETAIL_METAL_ROUGH_AO",		# 12 # False
    "MTL_BITMAP_ADD_METAL_ROUGH_AO",		# 13 # False
    "MTL_BITMAP_OCCLUSION",					# 14 # True for occlusion and False for extraOcclusion
    "MTL_BITMAP_CLEARCOATCOLORROUGHNESS",	# 15 # False
    "MTL_BITMAP_CLEARCOATNORMAL",			# 16 # False
    "MTL_BITMAP_ANISO_DIR_ROUGH",			# 17 # True
    "MTL_BITMAP_WIPERMASK",					# 18 # False
    "MTL_BITMAP_WINDSHIELDDETAILNORMAL",	# 19 # False
    "MTL_BITMAP_SCRATCHESNORMAL",			# 20 # False
    "MTL_BITMAP_ALPHABLENDMASK",			# 21 # False
    "MTL_BITMAP_IRIDESCENTTHICKNESS",		# 22 # False
    "MTL_BITMAP_WINDSHIELDINSECTS",			# 23 # False
    "MTL_BITMAP_WINDSHIELDINSECTSMASK",		# 24 # False
    "MTL_BITMAP_DIRTOVERLAY_METAL_ROUGH_AO",# 25 # False
    "MTL_BITMAP_TIREDETAILS",				# 26 # False
    "MTL_BITMAP_TIREMUDNORMAL",				# 27 # False
    "MTL_BITMAP_DIRTOVERLAY"				# 28 # False

]

def find_bitmap_index(slot) :
    """
        Return the index of the string of bitmap materials list (or 0 for invalid text) from str 
    """
    for i, bitmap_slot in enumerate(BITMAP_SLOTS):
        if bitmap_slot == slot:
            return i
    return 0

# Array of compatible bitmap slot index 
COMPATIBLE_INDEXES = [
    [1, 5, 7],		# MTL_BITMAP_DECAL0, MTL_BITMAP_ADD_DECAL0, MTL_BITMAP_EMISSIVE
    [3, 6],			# MTL_BITMAP_NORMAL, MTL_BITMAP_ADD_NORMAL
    [4, 8],			# MTL_BITMAP_DIRT, MTL_BITMAP_DETAILDIFFUSE
    [10, 12],		# MTL_BITMAP_WETNESS_AO, MTL_BITMAP_DETAIL_METAL_ROUGH_AO
    [11, 13, 25],	# MTL_BITMAP_METAL_ROUGH_AO, MTL_BITMAP_ADD_METAL_ROUGH_AO, MTL_BITMAP_DIRTOVERLAY_METAL_ROUGH_AO
    [14],			# MTL_BITMAP_OCCLUSION
    [15],			# MTL_BITMAP_CLEARCOATCOLORROUGHNESS
    [16],			# MTL_BITMAP_CLEARCOATNORMAL
    [17],			# MTL_BITMAP_ANISO_DIR_ROUGH
    [18],			# MTL_BITMAP_WIPERMASK
    [19],			# MTL_BITMAP_WINDSHIELDDETAILNORMAL
    [20],			# MTL_BITMAP_SCRATCHESNORMAL
    [21],			# MTL_BITMAP_ALPHABLENDMASK
    [22],			# MTL_BITMAP_IRIDESCENTTHICKNESS
    [23],			# MTL_BITMAP_WINDSHIELDINSECTS
    [24],			# MTL_BITMAP_WINDSHIELDINSECTSMASK
    [26],			# MTL_BITMAP_TIREDETAILS
    [27],			# MTL_BITMAP_TIREMUDNORMAL
    [28]			# MTL_BITMAP_DIRTOVERLAY
]

###################################################################################################

class BitmapConfig:
    """ 
        Simple struct :
        material_bitmap : int (0 is incorrect value), 
        user_flags : str, 
        force_no_alpha : bool (or None for incorrect value) 
    """
    def __init__(self, material_bitmap=0, user_flags=INCORRECT_USER_FLAG, force_no_alpha=None):
        if material_bitmap > len(BITMAP_SLOTS) or material_bitmap < 0 :
            material_bitmap = 0
        self.material_bitmap = material_bitmap
        self.user_flags = user_flags
        self.force_no_alpha = force_no_alpha

    def to_string(self) :

        return (f"Bitmap Slot: {BITMAP_SLOTS[self.material_bitmap]} \n "
                f"User Flags: {self.user_flags} \n "
                f"No Alpha: {str(self.force_no_alpha)}")
    
    def copy(self, other):
        self.material_bitmap = other.material_bitmap
        self.user_flags = other.user_flags
        self.force_no_alpha = other.force_no_alpha
    
    def compare(self, other):
        equal = True
        equal = equal and self.material_bitmap == other.material_bitmap
        equal = equal and self.user_flags == other.user_flags
        equal = equal and self.force_no_alpha == other.force_no_alpha
        return equal

    def is_compatible_id(self, other):
        if self.material_bitmap == 0 or other.material_bitmap == 0:
            return False

        if self.material_bitmap == other.material_bitmap:
            return True

        for compatible_index in COMPATIBLE_INDEXES:
            if (self.material_bitmap in compatible_index) and (other.material_bitmap in compatible_index):
                return True

        return False
