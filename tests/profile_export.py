"""Profile one deploy export with cProfile.

Runs an export driver script (for example G:/e-jets-e2/scripts/export-blend-to-gltf.py) inside Blender under cProfile,
with its final quit removed, and writes the raw stats plus a text summary (cumulative and own time).

    blender.exe -b <copy of model.blend> --python tests/profile_export.py -- \
        <export driver .py> <stats file> <out dir> <name>.gltf [fs24|fs20]

Run it from the driver's folder (drivers resolve paths relative to it). Write <stats file> and <out dir> into a
scratch folder, never into an aircraft project.
"""
import cProfile
import pstats
import sys

argv = sys.argv[sys.argv.index("--") + 1:]
script, stats_out = argv[0], argv[1]
# The driver reads its own arguments after "--": out dir, file name, target
sys.argv = [sys.argv[0], "--"] + argv[2:]
code = open(script, encoding="utf-8").read().replace("bpy.ops.wm.quit_blender()", "pass")
profiler = cProfile.Profile()
profiler.enable()
exec(compile(code, script, "exec"), {"__name__": "__main__", "__file__": script})
profiler.disable()
profiler.dump_stats(stats_out)
stats = pstats.Stats(profiler)
with open(stats_out + ".txt", "w", encoding="utf-8") as f:
    stats.stream = f
    stats.sort_stats("cumulative").print_stats(60)
    stats.sort_stats("tottime").print_stats(40)
print("PROFILE_DONE", stats_out)
import bpy  # noqa: E402
bpy.ops.wm.quit_blender()
