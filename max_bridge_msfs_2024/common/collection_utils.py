import bpy


def create_collection(name: str) -> bpy.types.Collection | None:

    return bpy.data.collections.new(name)


def get_collection(name: str) -> bpy.types.Collection | None:
    return bpy.data.collections.get(name)


def link_collection_in_scene(collection: bpy.types.Collection):
    try:
        bpy.context.scene.collection.children.link(collection)
    except RuntimeError:
        # Already in Scene Collection
        pass


def unlink_collection_from_scene(collection: bpy.types.Collection):
    if collection in bpy.context.scene.collection.children:
        bpy.context.scene.collection.children.unlink(collection)


def unlink_from_all_collections(obj: bpy.types.Object):
    """
    Unlinks the specified object from all collections.
    """

    # Iterate through all collections in the scene
    for collection in bpy.data.collections:
        if obj.name in collection.objects:
            collection.objects.unlink(obj)
    try:
        bpy.context.scene.collection.objects.unlink(obj)
    except RuntimeError:
        # When not in scene collection
        pass


def link_collection_in_collection(
    collection: bpy.types.Collection, parent_collection: bpy.types.Collection
):
    try:
        parent_collection.children.link(collection)
    except RuntimeError:
        pass
        # Already in collection

def add_object_to_collection(
    obj: bpy.types.Object, 
    collection: bpy.types.Collection
):

    try:
        collection.objects.link(obj)
    except RuntimeError:
        # Already in collection
        pass
def add_objects_to_collection(
    objects: list[bpy.types.Object], 
    collection: bpy.types.Collection
):

    # Add objects to the collection
    for obj in objects:
        add_object_to_collection(obj,collection)

def instantiate_collection(
    collection: bpy.types.Collection, 
    parent: None | bpy.types.Object | bpy.types.Collection = None
) -> bpy.types.Object:
    """
    Instantiates a collection in the current scene by creating an empty object
    that references the collection.
    Optionnal parent can be an object or a collection.
    """

    # Create an empty object to hold the collection instance
    empty_obj = bpy.data.objects.new(name=collection.name, object_data=None)
    empty_obj.instance_type = "COLLECTION"
    empty_obj.instance_collection = collection

    # empty display
    empty_obj.empty_display_type = "ARROWS"
    empty_obj.empty_display_size = 0.4

    # Link the empty object to the current scene
    if not parent:
        bpy.context.scene.collection.objects.link(empty_obj)
    else:
        if type(parent) == bpy.types.Collection:
            parent.objects.link(empty_obj)
        else:
            empty_obj.parent = parent
    return empty_obj


def collection_exists(collection_name:str)->bool:
    """
    Checks if a collection with the given name exists.
    """
    return bpy.data.collections.find(collection_name) != -1


def get_all_child_collections(
    collection: bpy.types.Collection,
) -> list[bpy.types.Collection | bpy.types.Object]:
    """
    Retrieve all child collections, including instanciated collection (dummies)
    """

    child_collections = list(collection.children)
    if not hasattr(collection, "objects"):
        collection = collection.instance_collection

    for obj in collection.objects:
        if obj.instance_type == "COLLECTION" and obj.instance_collection:
            child_collections.append(obj)
    return child_collections


def sort_collection_children(
    collection: bpy.types.Collection,
    affect_nested_children: bool = True,
    reverse_order: bool = False,
):
    """
    Order collection children in alphabetical order.
    """

    def sort_child_colls(collection: bpy.types.Collection, reverse_order: bool = False):
        children = collection.children
        sorted_children = sorted(children.keys(), reverse=reverse_order)
        for col in children:
            children.unlink(col)
        for col in sorted_children:
            children.link(bpy.data.collections.get(col))

    def sort_child_rec(collection: bpy.types.Collection, reverse_order: bool = False):
        children = collection.children_recursive
        for col in list(children):
            if len(col.children) == 0:
                children.remove(col)
        for col in children:
            sort_child_colls(col, reverse_order)
        sort_child_colls(collection, reverse_order)

    if not affect_nested_children:
        sort_child_colls(collection, reverse_order)
    else:
        sort_child_rec(collection, reverse_order)
