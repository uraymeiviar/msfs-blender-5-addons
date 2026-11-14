"""The client end of the AO Baker's channel for the tests: the add-on's own client, fss_blender_tools/ao_bake_native.py
(OptiX baker journal 20261114.optix-baker.md, decision 25), loaded from its file without the add-on (no bpy), its names
put here. The tests of steps (a) to (d) started from this file; the protocol moved into the add-on on 20261115."""
import importlib.util
import os

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'fss_blender_tools', 'ao_bake_native.py')
_spec = importlib.util.spec_from_file_location('ao_bake_native_standalone', os.path.normpath(_PATH))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
globals().update({k: v for k, v in vars(_mod).items() if not k.startswith('__')})
