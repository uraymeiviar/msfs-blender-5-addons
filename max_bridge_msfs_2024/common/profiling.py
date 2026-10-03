"""
THIS MODULE IS IDENTICAL IN 3DSMAX PLUGIN AND BLENDER ADDON.
"""
from __future__ import annotations
import cProfile
import pstats

PROFILER_ENABLED = False

def start_profiler()->cProfile.Profile|None:
    if not PROFILER_ENABLED:
        return None
    profiler = cProfile.Profile()
    profiler.enable()
    return profiler
    

def stop_profiler(profiler:cProfile.Profile, print_stats=True):
    if not PROFILER_ENABLED:
        return
    profiler.disable()
    if print_stats:
        # Print profiling results
        stats = pstats.Stats(profiler)
        stats.strip_dirs()  # Clean up paths
        stats.sort_stats("cumulative")  # Sort by time spent
        stats.print_stats()  # Display the stats