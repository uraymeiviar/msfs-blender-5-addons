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
    p.add_argument("--sim", choices=("2024", "2020"), default="2024", help="simulator the export is for")
    return p.parse_args(argv)


def _node_tree_signatures():
    out = {}
    for m in bpy.data.materials:
        if m.node_tree is None:
            continue
        nodes = sorted(f"{n.type}:{n.name}" for n in m.node_tree.nodes)
        links = sorted(f"{l.from_node.name}.{l.from_socket.identifier}>{l.to_node.name}.{l.to_socket.identifier}"
                       for l in m.node_tree.links)
        out[m.name] = (tuple(nodes), tuple(links))
    return out


def _select_all():
    for obj in bpy.context.scene.objects:
        obj.select_set(True)


# --------------------------------------------------------------------------- adapters

def _export_2024(addon, out_dir, case, msfs_on, result):
    """Full artist path: OBJECTS-mode LOD group discovery + msfs2024.multi_export_gltf
    (object duplication, modifier apply, mesh merge, glTF export, model XML)."""
    import importlib
    msfs_logs = importlib.import_module(addon + ".io.com.msfs_logs")
    es = importlib.import_module(addon + ".io.exp.export_settings")
    lod_groups = importlib.import_module(addon + ".io.exp.lod_groups")
    scene = bpy.context.scene
    if hasattr(scene, "msfs_fss_export_target"):
        scene.msfs_fss_export_target = "MSFS2024"
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


def _export_2020(addon, out_dir, case, msfs_on, result):
    """FSS production MSFS 2020 path: plain export_scene.gltf with the arguments of
    scripts/export-blend-to-gltf.py (mapped to Khronos 4.2+ where options were renamed)."""
    path = os.path.join(out_dir, case + ".gltf")
    scene = bpy.context.scene
    if hasattr(scene, "msfs_fss_export_target"):
        scene.msfs_fss_export_target = "MSFS2020"
    scene.msfs_exporter_settings.enable_msfs_extension = msfs_on
    kwargs = dict(
        filepath=path,
        export_format="GLTF_SEPARATE",
        use_visible=True,
        export_image_format="AUTO",
        export_force_sampling=False,
        export_apply=True,
        export_rest_position_armature=True,
        export_animation_mode="ACTIONS",
        export_reset_pose_bones=True,
        export_copyright="FlightSimStudio",
    )
    if bpy.app.version >= (4, 2, 0):
        kwargs.update(export_vertex_color="ACTIVE", export_merge_animation="NLA_TRACK")
    else:
        kwargs.update(export_colors=True)
    return bpy.ops.export_scene.gltf(**kwargs)


def _exporter(addon, sim):
    if addon == "io_scene_gltf2_msfs_2020" or sim == "2020":
        return _export_2020
    return _export_2024


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
        scenes.SIM = args.sim
        scenes.ADDON = args.addon
        try:
            scenes.clear_scene()
            # Unified add-on: choose the target before modelling, like an artist would (handlers such as
            # the MSFS 2024 default vertex color react to it while the scene is built)
            if hasattr(bpy.context.scene, "msfs_fss_export_target"):
                bpy.context.scene.msfs_fss_export_target = "MSFS2020" if args.sim == "2020" else "MSFS2024"
            scenes.CASES[args.case](args.out, log)
            scenes.push_actions_to_nla()
            bpy.context.scene.frame_set(1)
            if bpy.context.object and bpy.context.object.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            _select_all()
            trees_before = _node_tree_signatures()
            ret = _exporter(args.addon, args.sim)(args.addon, args.out, args.case, not args.vanilla, result)
            # Exporting must not leave the artist's materials with a different preview node tree
            trees_after = _node_tree_signatures()
            result["changed_node_trees"] = sorted(n for n in trees_before if trees_before[n] != trees_after.get(n))
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
