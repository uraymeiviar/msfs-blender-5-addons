"""
Differential test driver: exports every harness case on a reference side and a new side, then
semantically diffs the output. A side is an add-on repository + a Blender version.

Each case is exported twice per side: with the MSFS extension ("msfs") and without it
("vanilla"). Differences that also appear in the vanilla diff come from the Khronos
exporter itself, not from the MSFS add-on, and are tagged [khronos].

    # unified add-on vs the per-simulator fork, same Blender
    python tests/run_tests.py --sim 2024 --ref-repo H:/git-repos/msfs2024-blender-5.2.x-addons --ref 5.2
    python tests/run_tests.py --sim 2020 --ref-repo H:/git-repos/msfs2020-blender-5.2.x-addons --ref 5.2
    # unified add-on, Blender 4.5 vs 5.2
    python tests/run_tests.py --sim 2024
    python tests/run_tests.py --target-only            # smoke test, no comparison

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

COMPANION_ADDONS = ["_addons_common", "lod_tools_msfs_2024", "wipermask_generator_msfs_2024", "max_bridge_msfs_2024"]

# Add-on module -> (folders to install, simulators it exports for)
ADDONS = {
    "io_scene_gltf2_msfs_fss": (["io_scene_gltf2_msfs_fss"] + COMPANION_ADDONS, ("2024", "2020")),
    "io_scene_gltf2_msfs_2024": (["io_scene_gltf2_msfs_2024"] + COMPANION_ADDONS, ("2024",)),
    "io_scene_gltf2_msfs_2020": (["io_scene_gltf2_msfs_2020"], ("2020",)),
}


def blender_exe(version):
    return os.path.join(BLENDER_ROOT, f"Blender {version}", "blender.exe")


def detect_addon(repo):
    for name in ADDONS:
        if os.path.isdir(os.path.join(repo, name)):
            return name
    sys.exit(f"no known MSFS add-on folder in {repo}")


class Side:
    def __init__(self, label, repo, version):
        self.label, self.repo, self.version = label, os.path.abspath(repo), version
        self.addon = detect_addon(self.repo)
        self.name = f"{os.path.basename(self.repo)}@{version}"

    def install(self, work):
        """Copy the add-ons into a private BLENDER_USER_SCRIPTS so the user's Blender setup is untouched."""
        scripts = os.path.join(work, "scripts", self.label)
        dst_root = os.path.join(scripts, "addons")
        if os.path.isdir(dst_root):
            shutil.rmtree(dst_root)
        for folder in ADDONS[self.addon][0]:
            src = os.path.join(self.repo, folder)
            if os.path.isdir(src):
                shutil.copytree(src, os.path.join(dst_root, folder),
                                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "documentation*"))
        return scripts


def run_case(side, sim, case, mode, work, scripts, timeout):
    out = os.path.join(work, side.label, mode, case)
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)
    cmd = [blender_exe(side.version), "--background", "--factory-startup",
           "--python", os.path.join(HERE, "harness", "blender_case.py"), "--",
           "--addon", side.addon, "--sim", sim, "--case", case, "--out", out] \
        + (["--vanilla"] if mode == "vanilla" else [])
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
    return (not r["exported"] or r["console_tracebacks"] or r["msfs_errors"] or r.get("leftover_temp_nodes")
            or r.get("changed_node_trees"))


def _print_run(side, case, mode, r):
    status = "ok" if r["exported"] else "EXPORT FAILED"
    extra = f", {r['console_tracebacks']} console traceback(s)" if r["console_tracebacks"] else ""
    extra += f", {len(r['msfs_errors'])} MSFS log error(s)" if r["msfs_errors"] else ""
    print(f"[{side.name}] {case:<12} {mode:<8} {status} ({r['seconds']}s{extra}) -> {', '.join(r['outputs'])}",
          flush=True)
    if r.get("export_error"):
        print("    " + r["export_error"].strip().replace("\n", "\n    "))
    for e in r.get("enable_errors", []):
        print("    enable: " + e.strip().splitlines()[-1])
    for e in r["msfs_errors"]:
        print("    " + e.replace("\n", "\n    ")[:600])
    if r.get("changed_node_trees"):
        print(f"    export changed the node tree of {len(r['changed_node_trees'])} material(s), e.g. "
              + ", ".join(r["changed_node_trees"][:3]))
    if r.get("leftover_temp_nodes"):
        print(f"    {len(r['leftover_temp_nodes'])} temp node(s) left in materials, e.g. "
              + ", ".join(r["leftover_temp_nodes"][:3]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim", choices=("2024", "2020"), default="2024", help="simulator the exports are for")
    ap.add_argument("--repo", default=REPO, help="add-on repository under test (new side)")
    ap.add_argument("--target", default="5.2", help="Blender version of the new side")
    ap.add_argument("--ref-repo", default=None, help="add-on repository of the reference side (default: --repo)")
    ap.add_argument("--ref", default="4.5", help="Blender version of the reference side")
    ap.add_argument("--case", action="append")
    ap.add_argument("--target-only", action="store_true")
    ap.add_argument("--no-vanilla", action="store_true")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--max-diffs", type=int, default=25)
    a = ap.parse_args()

    new = Side("new", a.repo, a.target)
    sides = [new] if a.target_only else [Side("ref", a.ref_repo or a.repo, a.ref), new]
    for side in sides:
        if a.sim not in ADDONS[side.addon][1]:
            sys.exit(f"{side.addon} does not export for MSFS {a.sim}")
        if not os.path.isfile(blender_exe(side.version)):
            sys.exit(f"Blender {side.version} not found at {blender_exe(side.version)} (set BLENDER_ROOT)")
    cases = a.case or CASES
    modes = ["msfs"] if a.no_vanilla else ["msfs", "vanilla"]
    work = os.path.join(HERE, "_work", f"msfs{a.sim}")

    results = {}
    for side in sides:
        scripts = side.install(work)
        for case in cases:
            for mode in modes:
                r = run_case(side, a.sim, case, mode, work, scripts, a.timeout)
                results[(side.label, case, mode)] = r
                _print_run(side, case, mode, r)

    failed = sum(1 for r in results.values() if is_problem(r))
    if a.target_only:
        print(f"\n{failed} problem run(s)")
        return 1 if failed else 0

    ref = sides[0]
    print(f"\n==== MSFS {a.sim}: {ref.name} ({ref.addon}) -> {new.name} ({new.addon}) ====")
    total = 0
    for case in cases:
        r_ref, r_new = results[("ref", case, "msfs")], results[("new", case, "msfs")]
        if not (r_ref["exported"] and r_new["exported"]):
            print(f"{case}: skipped (export failed)")
            continue
        d = diff_outputs(r_ref, r_new)
        vanilla_paths = set()
        if (not a.no_vanilla and results[("ref", case, "vanilla")]["exported"]
                and results[("new", case, "vanilla")]["exported"]):
            vanilla_paths = {p for p, _, _ in diff_outputs(results[("ref", case, "vanilla")],
                                                          results[("new", case, "vanilla")])}
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
