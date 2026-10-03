from __future__ import annotations
from pathlib import Path

import bpy

class MSFS2024_TextureUtils:

    @staticmethod
    def get_texture_dir(gltf_path: str) -> None | Path:
        """Try to find closest texture dir by parsing each level
        of gltf path.

        Args:
            gltf_path: absolute gltf path

        """
        for parent in Path(gltf_path).parents:
            possible_path = parent / "texture"
            if possible_path.is_dir() and possible_path.exists():
                return possible_path
        return None

    @staticmethod
    def get_texture_cfg(gltf_path: str) -> None | Path:
        """Try to find closest cfg file by parsing each level
        of gltf path.

        Args:
            gltf_path: absolute gltf path
        """
        for parent in Path(gltf_path).parents:
            possible_path = parent / "texture.cfg"
            if possible_path.is_file() and possible_path.exists():
                return possible_path
        return None

    @staticmethod
    def get_additionnal_texture_dirs() -> list[Path]:
        """Get texture dirs provided by user.
        Very usefull when gltf or .cfg fallbacks are referencing external folders that 
        are not relative to gltf.

        Returns:
            List of texture directories
        """
        tex_dirs = []
        try:
            importer_settings = bpy.context.scene.msfs_importer_settings
        except AttributeError:
            return tex_dirs

        for dir_item in importer_settings.additionnal_texture_dirs:
            dir_path = dir_item.path
            try:
                dir_path = Path(dir_path)
                if dir_path.is_dir() and dir_path.exists():
                    tex_dirs.append(dir_path)
            except:
                continue
        return tex_dirs

    @staticmethod
    def get_texture_dirs_from_cfg(cfg_path: Path) -> list[str]:
        """Retrieves absolute directories for each fallback entry from a given cfg file.

        Args:
            cfg_path: absolute .cfg path

        Returns:
            List of texture directories
        """
        cfg_path = Path(cfg_path)
        if not cfg_path.is_file():
            raise FileNotFoundError(
                f"The configuration file does not exist: {cfg_path}"
            )

        textures_dirs = []

        with cfg_path.open("r") as cfg_file:
            for line in cfg_file:
                line = line.strip()
                if line.startswith("fallback."):
                    # Extract the path after the equals sign
                    _, path = line.split("=", 1)
                    path = path.strip()

                    absolute_path = Path()
                    # Handle paths: relative vs directory style
                    if path.startswith(".."):
                        # Treat as a relative path
                        absolute_path = (cfg_path / path).resolve()
                    else:
                        # Try to resolve the path using each level in cfg_path
                        fallbacks_dirs = list(cfg_path.parents)
                        fallbacks_dirs += MSFS2024_TextureUtils.get_additionnal_texture_dirs()
                        for fb_dir in fallbacks_dirs:
                            possible_path = fb_dir / path
                            if possible_path.is_dir():
                                absolute_path = possible_path.resolve()
                                break

                    if absolute_path.exists() and absolute_path not in textures_dirs:
                        textures_dirs.append(absolute_path)

        return textures_dirs

    @staticmethod
    def get_gltf_texture_dirs(gltf_path: str) -> list[Path]:
        """Retrieve all possible texture directories that could contains gltf textures.
        Include default texture dir and fallbacks defined in .cfg.

        Args:
            gltf_path: absolute gltf path

        Returns:
            List of texture directories
        """
        main_tex_dir = MSFS2024_TextureUtils.get_texture_dir(gltf_path)
        texture_cfg = MSFS2024_TextureUtils.get_texture_cfg(gltf_path)
        additionnal_tex_dirs = MSFS2024_TextureUtils.get_additionnal_texture_dirs()
        cfg_tex_dirs = []
        if texture_cfg:
            cfg_tex_dirs = MSFS2024_TextureUtils.get_texture_dirs_from_cfg(texture_cfg)

        tex_dirs = []
        if main_tex_dir:
            tex_dirs.append(main_tex_dir)

        if cfg_tex_dirs:
            tex_dirs += cfg_tex_dirs

        if additionnal_tex_dirs:
            tex_dirs += additionnal_tex_dirs

        return tex_dirs

    @staticmethod
    def resolve_texture_path(tex_path: str, texture_dirs: list[Path]):
        """Try to resolve gltf texture path by checking if texture
        is present in one of the provided texture dirs.

        Do nothing if tex_path is already resolved.

        """
        if not tex_path:
            return tex_path

        path = Path(tex_path)
        if path.exists():
            return tex_path

        for dir in texture_dirs:
            resolved_tex_path = Path(dir) / path.name
            if resolved_tex_path.exists():
                return str(resolved_tex_path)

        return tex_path
