from _addons_common.p4 import use_p4

class DefaultUV():

    UV1_NAME: str = "UV1"
    UV2_NAME: str = "UV2"


class DefaultVertexColor():

    NAME: str = "Color"
    TYPE: str = "BYTE_COLOR"
    DOMAIN: str = "CORNER"
    COLOR: tuple[float] = (1.0, 1.0, 1.0, 1.0)

USE_P4 = use_p4()
