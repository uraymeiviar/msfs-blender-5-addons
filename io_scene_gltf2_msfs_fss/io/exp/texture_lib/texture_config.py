class TextureConfig:
    """ 
        Simple structure:
            id: int, 
            bitmap_config: BitmapConfig
            material_name : str 
    """
    def __init__(self, gltf_texture_id=-1, bitmap_config=None, material_name=None) -> None:
        self.gltf_texture_id = gltf_texture_id
        self.bitmap_config = bitmap_config
        self.material_name = material_name
