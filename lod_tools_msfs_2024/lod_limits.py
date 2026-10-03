import math

# ModelLodLimits constants
tw_Lod_limitCurvePower = 1
tw_Lod_limitCurvePowerAbove100 = 2
tw_Lod_ms0_MaxVertexCount = 1000 #Limits below 1%/VtxCount
tw_Lod_ms1_MaxVertexCount = 2500 #Limits at 1%/VtxCount
tw_Lod_ms100_MaxVertexCount = 250000 #Limits At 100%
Default_LastLod_MinScreenSizeRatio = 0.001
Default_SecondToLastLod_MinScreenSizeRatio = 0.01
Float_Eps = 1.e-6

# Linear from screen size 0.1 to 100
# Parabolic after screen size 100
def get_last_lod_min_screen_size_ratio()->float:
    return Default_LastLod_MinScreenSizeRatio

def get_second_to_last_lod_min_screen_size_ratio()->float:
    return Default_SecondToLastLod_MinScreenSizeRatio

def lowest_screen_size_from_vcount(v_count: int) -> float:
    """Return min size in range 0-1
    """
    if v_count <= tw_Lod_ms0_MaxVertexCount:
        return 0
    if v_count <= tw_Lod_ms1_MaxVertexCount:
        return 0.01
    value = (v_count - tw_Lod_ms1_MaxVertexCount) / (
        tw_Lod_ms100_MaxVertexCount - tw_Lod_ms1_MaxVertexCount
    )
    power = tw_Lod_limitCurvePowerAbove100
    if value < 1.0:
        power = tw_Lod_limitCurvePower

    result = math.pow(value, 1 / power)
    return (result * 0.99 + 0.01)


def max_vertex_count(screen_size: float) -> int:

    

    if screen_size <= 0.01 - Float_Eps:
        return tw_Lod_ms0_MaxVertexCount
    value = max(0, screen_size - 0.01) / 0.99
    power = tw_Lod_limitCurvePowerAbove100
    if screen_size <= 1.0:
        power = tw_Lod_limitCurvePower
    result = math.pow(value, power)
    if value == 0:
        result = 0
    return math.floor(
        (
            tw_Lod_ms1_MaxVertexCount
            + result * (tw_Lod_ms100_MaxVertexCount - tw_Lod_ms1_MaxVertexCount)
        )
        + 0.5
    )
