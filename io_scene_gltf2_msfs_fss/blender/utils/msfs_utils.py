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
from __future__ import annotations

from enum import Enum

class MSFS2024_Enum_Properties(Enum):
    """
        Enum virtual class describing parameters contains Tuples of:
        (
            The name that appears in the UI,
            Default Value,
            attribute name of the property,
            name that appear in the extension when it's exported/imported
        )
    """

    def property_name(self):
        assert isinstance(self.value, tuple) and len(self.value) > 0
        if isinstance(self.value, tuple) and len(self.value) > 0:
            return self.value[0]
        return None

    def default_value(self):
        assert isinstance(self.value, tuple) and len(self.value) > 1
        if isinstance(self.value, tuple) and len(self.value) > 1:
            return self.value[1]
        return None

    def attribute_name(self):
        assert isinstance(self.value, tuple) and len(self.value) > 2
        if isinstance(self.value, tuple) and len(self.value) > 2:
            return self.value[2]
        return None

    def extension_name(self):
        assert isinstance(self.value, tuple) and len(self.value) > 3
        if isinstance(self.value, tuple) and len(self.value) > 3:
            return self.value[3]
        return None

    @classmethod
    def from_attribute_name(cls, attribute_name: str)->MSFS2024_Enum_Properties|None:
        """
        Return the enum member matching the given attribute name.
        """
        for member in cls:
            if member.attribute_name() == attribute_name:
                return member
        return None