"""
Runs inside Blender (--background --factory-startup). Builds one harness scene and
exports it through the add-on's own multi-exporter glTF call, so the exact Khronos
operator arguments an artist's export uses are exercised.

    blender --background --factory-startup --python blender_case.py -- \
        --addon io_scene_gltf2_msfs_fss --case materials --out <dir> [--vanilla]

Writes <out>/<case>.gltf(+.bin, textures) and <out>/result.json.
"""
import argparse
import json
import os
import sys
import traceback

import addon_utils
import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scenes  # noqa: E402


def _args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--addon", required=True)
    p.add_argument("--case", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--vanilla", action="store_true", help="export with the MSFS extension disabled")
    return p.parse_args(argv)


def _select_all():
    for obj in bpy.context.scene.objects:
        obj.select_set(True)


# --------------------------------------------------------------------------- adapters

def _export_2024(out_dir, case, msfs_on, result):
    """Full artist path: OBJECTS-mode LOD group discovery + msfs2024.multi_export_gltf
    (object duplication, modifier apply, mesh merge, glTF export, model XML)."""
    from io_scene_gltf2_msfs_fss.io.com import msfs_logs
    from io_scene_gltf2_msfs_fss.io.exp import export_settings as es
    from io_scene_gltf2_msfs_fss.io.exp import lod_groups
    scene = bpy.context.scene
    es.init_setting_presets(scene)
    es.get_active_export_settings(scene).enable_msfs_extension = msfs_on
    scene.msfs_background_export = False
    scene.msfs_export_mode = "OBJECTS"

    root = bpy.data.objects.new(case + "_LOD0", None)
    scene.collection.objects.link(root)
    for obj in list(scene.objects):
        if obj is not root and obj.parent is None:
            obj.parent = root
    lod_groups.reload_lod_groups(scene, reset=True)
    for group in lod_groups.get_scene_lod_groups(scene):
        group.folder_path = out_dir
        group.enabled = True
        group.generate_xml = True
        for lod in group.lods:
            lod.enabled = True

    logger = msfs_logs.get_logger()
    for level in ("error", "warning"):
        original = getattr(logger, level)

        def capture(message, details="", _orig=original, _level=level):
            result["msfs_log"].append(f"[{_level}] {message} {details}".strip())
            return _orig(message, details)
        setattr(logger, level, capture)
    return bpy.ops.msfs2024.multi_export_gltf(export_mode="OBJECTS")


def _export_2020(out_dir, case, msfs_on, result):
    path = os.path.join(out_dir, case + ".gltf")
    from io_scene_gltf2_msfs_2020.io import msfs_multi_export
    scene = bpy.context.scene
    scene.msfs_multi_exporter_settings.enable_msfs_extension = msfs_on
    scene.msfs_exporter_settings.enable_msfs_extension = msfs_on
    if bpy.app.version < (3, 6, 0):
        fn = msfs_multi_export.export_blender_3_3
    elif bpy.app.version < (4, 2, 0):
        fn = msfs_multi_export.export_blender_3_6
    else:
        fn = msfs_multi_export.export_blender_4_2
    return fn(path, scene.msfs_multi_exporter_settings)


EXPORTERS = {
    "io_scene_gltf2_msfs_fss": _export_2024,
    "io_scene_gltf2_msfs_2020": _export_2020,
}


def main():
    args = _args()
    os.makedirs(args.out, exist_ok=True)
    result = {
        "blender": bpy.app.version_string,
        "addon": args.addon,
        "case": args.case,
        "msfs": not args.vanilla,
        "enable_errors": [],
        "build_warnings": [],
        "export_error": None,
        "exported": False,
        "outputs": [],
        "msfs_log": [],
    }

    def on_enable_error(_exc):
        result["enable_errors"].append(traceback.format_exc())

    # default_set=True: the Khronos exporter only discovers glTF2ExportUserExtension
    # from add-ons registered in preferences (--factory-startup keeps this unsaved).
    mod = addon_utils.enable(args.addon, default_set=True, persistent=False, handle_error=on_enable_error)
    if not mod:
        result["export_error"] = "add-on failed to enable"
    else:
        log = scenes.CaseLog()
        try:
            scenes.clear_scene()
            scenes.CASES[args.case](args.out, log)
            scenes.push_actions_to_nla()
            bpy.context.scene.frame_set(1)
            if bpy.context.object and bpy.context.object.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            _select_all()
            ret = EXPORTERS[args.addon](args.out, args.case, not args.vanilla, result)
            for dirpath, _dirs, files in os.walk(args.out):
                for name in files:
                    if name.endswith((".gltf", ".xml")):
                        result["outputs"].append(os.path.relpath(os.path.join(dirpath, name), args.out).replace("\\", "/"))
            result["outputs"].sort()
            # Exporters must leave the artist's scene untouched (e.g. no temp shader nodes)
            result["leftover_temp_nodes"] = sorted(
                f"{m.name}/{n.name}" for m in bpy.data.materials if m.node_tree
                for n in m.node_tree.nodes if "Temp" in n.name)
            result["exported"] = any(o.endswith(".gltf") for o in result["outputs"])
            if not result["exported"]:
                result["export_error"] = f"exporter returned {ret!r} and wrote no glTF"
        except Exception:  # noqa: BLE001
            result["export_error"] = traceback.format_exc()
        result["build_warnings"] = log.messages

    with open(os.path.join(args.out, "result.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)


main()
