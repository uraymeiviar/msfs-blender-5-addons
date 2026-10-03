"""
Semantic diff of two glTF exports (pure Python, no Blender needed).

Index-based references (nodes, meshes, accessors, textures, skins, lights) are
resolved into a canonical, order-independent tree before comparing, so a
Khronos version that merely reorders nodes or vertices is not reported:

- nodes are keyed by name; children / joints / channel targets become names
- primitives become a sorted multiset of triangles, each corner carrying every
  vertex attribute (joint indices mapped to joint names, morph target deltas
  included), quantized to a tolerance grid
- animation samplers keep their full key arrays (compared with tolerance)
- textures referenced from materials or extensions are inlined as image URIs

Usage:  python compare.py <ref.gltf> <new.gltf> [--json]
"""
import base64
import json
import math
import os
import struct
import sys

ABS_TOL = 1e-4
REL_TOL = 1e-4
QUANT = 1e-3  # grid used to make triangle signatures order-independent

_COMP = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
_NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}
_NORM_DIV = {5120: 127.0, 5121: 255.0, 5122: 32767.0, 5123: 65535.0}


class Gltf:
    def __init__(self, path):
        self.path = path
        self.dir = os.path.dirname(os.path.abspath(path))
        with open(path, "r", encoding="utf-8") as f:
            self.j = json.load(f)
        self.buffers = [self._load_buffer(b) for b in self.j.get("buffers", [])]
        nodes = self.j.get("nodes", [])
        seen = {}
        self.node_names = []
        for i, n in enumerate(nodes):
            base = n.get("name", f"#node{i}")
            seen[base] = seen.get(base, 0) + 1
            self.node_names.append(base if seen[base] == 1 else f"{base}#{seen[base]}")

    def _load_buffer(self, b):
        uri = b.get("uri")
        if uri is None:
            return b""
        if uri.startswith("data:"):
            return base64.b64decode(uri.split(",", 1)[1])
        with open(os.path.join(self.dir, uri), "rb") as f:
            return f.read()

    def accessor(self, idx):
        acc = self.j["accessors"][idx]
        fmt, size = _COMP[acc["componentType"]]
        ncomp = _NCOMP[acc["type"]]
        count = acc["count"]
        out = [[0.0] * ncomp for _ in range(count)]
        if "bufferView" in acc:
            bv = self.j["bufferViews"][acc["bufferView"]]
            data = self.buffers[bv["buffer"]]
            base = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
            stride = bv.get("byteStride", size * ncomp)
            for i in range(count):
                out[i] = list(struct.unpack_from("<" + fmt * ncomp, data, base + i * stride))
        sparse = acc.get("sparse")
        if sparse:
            ibv = self.j["bufferViews"][sparse["indices"]["bufferView"]]
            ifmt, isz = _COMP[sparse["indices"]["componentType"]]
            vbv = self.j["bufferViews"][sparse["values"]["bufferView"]]
            ib = self.buffers[ibv["buffer"]]
            vb = self.buffers[vbv["buffer"]]
            ioff = ibv.get("byteOffset", 0) + sparse["indices"].get("byteOffset", 0)
            voff = vbv.get("byteOffset", 0) + sparse["values"].get("byteOffset", 0)
            for k in range(sparse["count"]):
                (ti,) = struct.unpack_from("<" + ifmt, ib, ioff + k * isz)
                out[ti] = list(struct.unpack_from("<" + fmt * ncomp, vb, voff + k * size * ncomp))
        if acc.get("normalized") and acc["componentType"] in _NORM_DIV:
            d = _NORM_DIV[acc["componentType"]]
            out = [[max(-1.0, v / d) for v in row] for row in out]
        return out


# --------------------------------------------------------------------------- canonicalization

def _q(v):
    return round(v / QUANT) * QUANT if isinstance(v, float) else v


def _texture(g, idx):
    tex = g.j["textures"][idx]
    src = tex.get("source")
    for ext in (tex.get("extensions") or {}).values():
        if isinstance(ext, dict) and "source" in ext:
            src = ext["source"]
    img = g.j["images"][src] if src is not None else {}
    uri = img.get("uri") or img.get("name") or "?"
    sampler = g.j["samplers"][tex["sampler"]] if "sampler" in tex else {}
    return {"image": os.path.basename(uri), "mimeType": img.get("mimeType"), "sampler": sampler,
            "extensions": tex.get("extensions")}


def _resolve_refs(g, obj, key_hint=""):
    """Deep copy that inlines texture references ({'index': n} under a *texture* key)."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k == "index" and "exture" in key_hint and isinstance(v, int) and g.j.get("textures"):
                out["texture"] = _texture(g, v)
            else:
                out[k] = _resolve_refs(g, v, k if isinstance(v, (dict, list)) else key_hint)
        return out
    if isinstance(obj, list):
        return [_resolve_refs(g, v, key_hint) for v in obj]
    return obj


def _primitive(g, prim, joint_names):
    attrs = prim.get("attributes", {})
    data = {name: g.accessor(idx) for name, idx in attrs.items()}
    nverts = len(next(iter(data.values()))) if data else 0
    targets = [{name: g.accessor(idx) for name, idx in t.items()} for t in prim.get("targets", [])]

    def corner(v):
        c = []
        for name in sorted(data):
            row = data[name][v]
            if name.startswith("JOINTS_"):
                wname = "WEIGHTS_" + name.split("_")[1]
                weights = data.get(wname, [[1.0] * len(row)])[v]
                pairs = sorted((joint_names[int(j)] if int(j) < len(joint_names) else int(j), _q(float(w)))
                               for j, w in zip(row, weights) if float(w) > 0.0)
                c.append((name, tuple(pairs)))
            elif name.startswith("WEIGHTS_"):
                continue
            else:
                c.append((name, tuple(_q(float(x)) for x in row)))
        for ti, t in enumerate(targets):
            for name in sorted(t):
                c.append((f"T{ti}.{name}", tuple(_q(float(x)) for x in t[name][v])))
        return tuple(c)

    indices = [int(r[0]) for r in g.accessor(prim["indices"])] if "indices" in prim else list(range(nverts))
    mode = prim.get("mode", 4)
    if mode == 4:
        tris = []
        for t in range(0, len(indices) - 2, 3):
            cs = [corner(indices[t + k]) for k in range(3)]
            r = min(range(3), key=lambda k: repr(cs[k]))  # rotation-normalize, keep winding
            tris.append(repr(tuple(cs[r:] + cs[:r])))
        elems = sorted(tris)
    else:
        elems = sorted(repr(corner(i)) for i in indices)
    mat = prim.get("material")
    mat_name = g.j["materials"][mat].get("name", f"#mat{mat}") if mat is not None else None
    out = _resolve_refs(g, {k: v for k, v in prim.items()
                            if k not in {"attributes", "indices", "targets", "material", "mode"}})
    out.update({"mode": mode, "material": mat_name, "attributes": sorted(attrs),
                "vertex_count": nverts, "elements": elems})
    return out


def canonical(g):
    j = g.j
    out = {
        "asset": {k: v for k, v in j.get("asset", {}).items() if k != "generator"},
        "asset_generator_has_asobo": "Asobo" in j.get("asset", {}).get("generator", ""),
        "extensionsUsed": sorted(j.get("extensionsUsed", [])),
        "extensionsRequired": sorted(j.get("extensionsRequired", [])),
        "extensions": _resolve_refs(g, j.get("extensions")),
        "scenes": [dict(_resolve_refs(g, {k: v for k, v in s.items() if k != "nodes"}),
                        nodes=sorted(g.node_names[n] for n in s.get("nodes", []))) for s in j.get("scenes", [])],
        "cameras": j.get("cameras"),
        "extras": j.get("extras"),
    }
    lights = (j.get("extensions") or {}).get("KHR_lights_punctual", {}).get("lights", [])
    nodes = {}
    for i, n in enumerate(j.get("nodes", [])):
        c = {k: v for k, v in n.items() if k not in {"children", "mesh", "skin", "name", "extensions"}}
        c["children"] = sorted(g.node_names[ch] for ch in n.get("children", []))
        if "skin" in n:
            skin = j["skins"][n["skin"]]
            jn = [g.node_names[x] for x in skin["joints"]]
            c["skin"] = {"name": skin.get("name"), "extensions": _resolve_refs(g, skin.get("extensions")),
                         "extras": skin.get("extras"), "joints": sorted(jn),
                         "skeleton": g.node_names[skin["skeleton"]] if "skeleton" in skin else None,
                         "inverseBindMatrices": dict(zip(jn, g.accessor(skin["inverseBindMatrices"])))
                         if "inverseBindMatrices" in skin else None}
        else:
            jn = []
        if "mesh" in n:
            mesh = j["meshes"][n["mesh"]]
            # keep every mesh key (e.g. ASOBO_gizmo_object lives in mesh.extensions)
            c["mesh"] = _resolve_refs(g, {k: v for k, v in mesh.items() if k != "primitives"})
            c["mesh"]["primitives"] = sorted((_primitive(g, p, jn) for p in mesh["primitives"]),
                                             key=lambda p: (str(p["material"]), p["vertex_count"]))
        ext = _resolve_refs(g, n.get("extensions") or {})
        klp = ext.get("KHR_lights_punctual")
        if isinstance(klp, dict) and "light" in klp and klp["light"] < len(lights):
            ext["KHR_lights_punctual"] = lights[klp["light"]]
        c["extensions"] = ext
        nodes[g.node_names[i]] = c
    out["nodes"] = nodes
    anims = {}
    for a in j.get("animations", []):
        chans = []
        for ch in a["channels"]:
            s = a["samplers"][ch["sampler"]]
            tgt = ch["target"]
            chans.append({"node": g.node_names[tgt["node"]] if "node" in tgt else None,
                          "path": tgt.get("path"), "target_extensions": _resolve_refs(g, tgt.get("extensions")),
                          "target_extras": tgt.get("extras"),
                          "interpolation": s.get("interpolation", "LINEAR"),
                          "input": [r[0] for r in g.accessor(s["input"])],
                          "output": g.accessor(s["output"]),
                          "sampler_extensions": _resolve_refs(g, s.get("extensions")),
                          "extensions": _resolve_refs(g, ch.get("extensions")), "extras": ch.get("extras")})
        chans.sort(key=lambda c: (str(c["node"]), str(c["path"]), json.dumps(c["target_extensions"], sort_keys=True)))
        anim = _resolve_refs(g, {k: v for k, v in a.items() if k not in {"channels", "samplers", "name"}})
        anim["channels"] = chans
        anims[a.get("name", "#anim")] = anim
    out["animations"] = anims
    out["materials"] = {m.get("name", f"#mat{i}"): _resolve_refs(g, {k: v for k, v in m.items() if k != "name"})
                        for i, m in enumerate(j.get("materials", []))}
    out["images"] = sorted(os.path.basename(im.get("uri", im.get("name", "?"))) for im in j.get("images", []))
    return out


# --------------------------------------------------------------------------- diff

def _close(a, b):
    return math.isclose(a, b, rel_tol=REL_TOL, abs_tol=ABS_TOL)


def diff(a, b, path="", out=None, limit=100000):
    if out is None:
        out = []
    if len(out) >= limit:
        return out
    if isinstance(a, bool) or isinstance(b, bool):
        if a != b:
            out.append((path, a, b))
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if not _close(float(a), float(b)):
            out.append((path, a, b))
    elif isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b), key=str):
            if k not in a:
                out.append((f"{path}/{k}", "<missing>", _short(b[k])))
            elif k not in b:
                out.append((f"{path}/{k}", _short(a[k]), "<missing>"))
            else:
                diff(a[k], b[k], f"{path}/{k}", out, limit)
    elif isinstance(a, list) and isinstance(b, list):
        if path.endswith("/elements"):
            sa, sb = set(a), set(b)
            if sa != sb or len(a) != len(b):
                out.append((path, f"{len(a)} elems ({len(sa - sb)} unmatched)",
                            f"{len(b)} elems ({len(sb - sa)} unmatched)"))
        elif len(a) != len(b):
            out.append((path + "/len", len(a), len(b)))
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                diff(x, y, f"{path}[{i}]", out, limit)
    elif a != b:
        out.append((path, _short(a), _short(b)))
    return out


def _short(v, n=160):
    s = json.dumps(v, sort_keys=True) if not isinstance(v, str) else v
    return s if len(s) <= n else s[:n] + "..."


def compare_files(ref_path, new_path):
    return diff(canonical(Gltf(ref_path)), canonical(Gltf(new_path)))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    d = compare_files(args[0], args[1])
    if "--json" in sys.argv:
        print(json.dumps(d, indent=1))
    else:
        for p, x, y in d:
            print(f"{p}\n    ref: {x}\n    new: {y}")
        print(f"{len(d)} difference(s)")
    sys.exit(1 if d else 0)
