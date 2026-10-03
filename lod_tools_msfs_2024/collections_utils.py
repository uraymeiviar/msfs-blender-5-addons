import bpy

def instantiate_collection(collection: bpy.types.Collection) -> bpy.types.Object:
    """
    Instantiate a collection.
    """
    # Create an empty object to hold the collection instance
    empty_obj = bpy.data.objects.new(name=collection.name, object_data=None)
    empty_obj.instance_type = "COLLECTION"
    empty_obj.instance_collection = collection
    return empty_obj
