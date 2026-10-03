"""
Differential test driver: exports every harness case on a reference Blender and a
target Blender, then semantically diffs the glTF output.

Each case is exported twice per Blender: with the MSFS extension ("msfs") and
without it ("vanilla"). Differences that also appear in the vanilla diff come
from the Khronos exporter itself, not from the MSFS add-on, and are tagged so.

    python tests/run_tests.py                      # all cases, default versions
    python tests/run_tests.py --case skinning --target 5.2 --ref 4.5
    python tests/run_tests.py --target-only        # smoke test: no comparison

Any Python 3.10+ works (e.g. Blender's bundled python.exe). Output: tests/_work/
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "harness"))
import compare  # noqa: E402

# Must match harness/scenes.py CASES (kept here so the driver never imports bpy)
CASES = ["materials", "skinning", "hierarchy", "lights", "gizmos", "vertex_data"]

BLENDER_ROOT = os.environ.get("BLENDER_ROOT", r"C:\Program Files\Blender Foundation")

# Add-on module -> (add-on folders to install, default reference Blender)
ADDONS = {
    "io_scene_gltf2_msfs_fss": (["_addons_common", "io_scene_gltf2_msfs_fss", "lod_tools_msfs_2024",
                                  "wipermask_generator_msfs_2024", "max_bridge_msfs_2024"], "4.5"),
    "io_scene_gltf2_msfs_2020": (["io_scene_gltf2_msfs_2020"], "4.5"),
}


def blender_exe(version):
    return os.path.join(BLENDER_ROOT, f"Blender {version}", "blender.exe")


def detect_addon():
    for name in ADDONS:
        if os.path.isdir(os.path.join(REPO, name)):
            return name
    sys.exit("no known MSFS add-on folder in repo root")


def install_addons(addon, version, work):
    """Copy the add-ons into a private BLENDER_USER_SCRIPTS so the user's Blender setup is untouched."""
    scripts = os.path.join(work, "scripts", version)
    dst_root = os.path.join(scripts, "addons")
    if os.path.isdir(dst_root):
        shutil.rmtree(dst_root)
    for folder in ADDONS[addon][0]:
        src = os.path.join(REPO, folder)
        if os.path.isdir(src):
            shutil.copytree(src, os.path.join(dst_root, folder),
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "documentation*"))
    return scripts


def run_case(addon, version, case, mode, work, scripts, timeout):
    out = os.path.join(work, version, mode, case)
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)
    cmd = [blender_exe(version), "--background", "--factory-startup",
           "--python", os.path.join(HERE, "harness", "blender_case.py"), "--",
           "--addon", addon, "--case", case, "--out", out] + (["--vanilla"] if mode == "vanilla" else [])
    env = dict(os.environ, BLENDER_USER_SCRIPTS=scripts)
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True, errors="replace", timeout=timeout)
        console = proc.stdout + proc.stderr
    except subprocess.TimeoutExpired as e:
        console = f"TIMEOUT after {timeout}s\n{e.stdout or ''}{e.stderr or ''}"
    with open(os.path.join(out, "console.log"), "w", encoding="utf-8") as f:
        f.write(console)
    res_path = os.path.join(out, "result.json")
    if os.path.isfile(res_path):
        with open(res_path, encoding="utf-8") as f:
            res = json.load(f)
    else:
        res = {"exported": False, "export_error": "Blender produced no result.json (crash?)",
               "enable_errors": [], "build_warnings": [], "outputs": [], "msfs_log": []}
    # Python errors Blender swallows (property update callbacks, handlers) still reach the console
    res["console_tracebacks"] = console.count("Traceback (most recent call last)")
    res["msfs_errors"] = [m for m in res.get("msfs_log", []) if m.startswith("[error]")]
    res["seconds"] = round(time.time() - t0, 1)
    res["dir"] = out
    return res


def _xml_lines(path):
    # GUIDs are regenerated per export; everything else in the model XML must match
    with open(path, encoding="utf-8", errors="replace") as f:
        text = re.sub(r'guid="\{?[0-9A-Fa-f-]+\}?"', 'guid="*"', f.read())
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def diff_outputs(r_ref, r_new):
    out = []
    ref_set, new_set = set(r_ref["outputs"]), set(r_new["outputs"])
    for missing in sorted(ref_set - new_set):
        out.append((f"{missing}", "<file>", "<missing>"))
    for extra in sorted(new_set - ref_set):
        out.append((f"{extra}", "<missing>", "<file>"))
    for rel in sorted(ref_set & new_set):
        a, b = os.path.join(r_ref["dir"], rel), os.path.join(r_new["dir"], rel)
        if rel.endswith(".gltf"):
            out += [(rel + p, x, y) for p, x, y in compare.compare_files(a, b)]
        else:
            la, lb = _xml_lines(a), _xml_lines(b)
            if la != lb:
                out.append((rel, "\n".join(la), "\n".join(lb)))
    return out


def is_problem(r):
    return not r["exported"] or r["console_tracebacks"] or r["msfs_errors"] or r.get("leftover_temp_nodes")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--addon", default=None)
    ap.add_argument("--target", default="5.2")
    ap.add_argument("--ref", default=None)
    ap.add_argument("--case", action="append")
    ap.add_argument("--target-only", action="store_true")
    ap.add_argument("--no-vanilla", action="store_true")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--max-diffs", type=int, default=25)
    a = ap.parse_args()

    addon = a.addon or detect_addon()
    ref = a.ref or ADDONS[addon][1]
    cases = a.case or CASES
    versions = [a.target] if a.target_only else [ref, a.target]
    modes = ["msfs"] if a.no_vanilla else ["msfs", "vanilla"]
    work = os.path.join(HERE, "_work", addon)

    results = {}
    for v in versions:
        if not os.path.isfile(blender_exe(v)):
            sys.exit(f"Blender {v} not found at {blender_exe(v)} (set BLENDER_ROOT)")
        scripts = install_addons(addon, v, work)
        for case in cases:
            for mode in modes:
                r = run_case(addon, v, case, mode, work, scripts, a.timeout)
                results[(v, case, mode)] = r
                status = "ok" if r["exported"] else "EXPORT FAILED"
                extra = f", {r['console_tracebacks']} console traceback(s)" if r["console_tracebacks"] else ""
                extra += f", {len(r['msfs_errors'])} MSFS log error(s)" if r["msfs_errors"] else ""
                print(f"[{v}] {case:<12} {mode:<8} {status} ({r['seconds']}s{extra}) -> {', '.join(r['outputs'])}",
                      flush=True)
                if r.get("export_error"):
                    print("    " + r["export_error"].strip().replace("\n", "\n    "))
                for e in r.get("enable_errors", []):
                    print("    enable: " + e.strip().splitlines()[-1])
                for e in r["msfs_errors"]:
                    print("    " + e.replace("\n", "\n    ")[:600])
                if r.get("leftover_temp_nodes"):
                    print(f"    {len(r['leftover_temp_nodes'])} temp node(s) left in materials, e.g. "
                          + ", ".join(r["leftover_temp_nodes"][:3]))

    failed = sum(1 for r in results.values() if is_problem(r))
    if a.target_only:
        print(f"\n{failed} problem run(s)")
        return 1 if failed else 0

    print(f"\n==== diff {ref} -> {a.target} ({addon}) ====")
    total = 0
    for case in cases:
        r_ref, r_new = results[(ref, case, "msfs")], results[(a.target, case, "msfs")]
        if not (r_ref["exported"] and r_new["exported"]):
            print(f"{case}: skipped (export failed)")
            continue
        d = diff_outputs(r_ref, r_new)
        vanilla_paths = set()
        if not a.no_vanilla and results[(ref, case, "vanilla")]["exported"] and results[(a.target, case, "vanilla")]["exported"]:
            vanilla_paths = {p for p, _, _ in diff_outputs(results[(ref, case, "vanilla")],
                                                          results[(a.target, case, "vanilla")])}
        msfs_only = [x for x in d if x[0] not in vanilla_paths]
        total += len(msfs_only)
        print(f"{case}: {len(d)} diff(s), {len(msfs_only)} not explained by vanilla Khronos")
        for p, x, y in d[: a.max_diffs]:
            tag = "  [khronos]" if p in vanilla_paths else ""
            print(f"  {p}{tag}\n      ref: {x}\n      new: {y}")
        if len(d) > a.max_diffs:
            print(f"  ... {len(d) - a.max_diffs} more")
    print(f"\n{failed} problem run(s), {total} MSFS-attributable diff(s)")
    return 1 if failed or total else 0


if __name__ == "__main__":
    sys.exit(main())
