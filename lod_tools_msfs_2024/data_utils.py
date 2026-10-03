import bpy

def data_is_valid(data: bpy.types.ID):
    try:
        data.name
        return True
    except:
        # Object deleted
        return False