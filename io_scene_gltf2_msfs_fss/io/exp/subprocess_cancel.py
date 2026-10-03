"""_summary_

Returns:
    _type_: _description_
"""
from __future__ import annotations
from typing import TYPE_CHECKING

import os
import sys
import threading

if TYPE_CHECKING:
    import subprocess

# region Main Instance functions

def send_cancel_request(subprocess:subprocess.Popen):
    """Used in main blender instance to kill export subprocess.
    """
    try:
        subprocess.stdin.write(f"{_CANCEL_TAG}\n")
        subprocess.stdin.flush()
    except:
        pass

# endregion


# region Subprocess functions
# Used in subprocess in order to listen for cancel request

_cancel_requested = False  # Only set in subprocess
_CANCEL_TAG = "MSFS_EXPORT_CANCEL"

def _read_stdin():
    global _cancel_requested
    for line in sys.stdin:
        if line.strip() == _CANCEL_TAG:
            _cancel_requested = True
            print("CANCEL REQUEST RECEIVED")
            break


def read_cancel_requests_from_stdin():
    """
    Runs in a background thread.
    Listens to stdin for 'CANCEL' messages and sets the _cancel_requested flag.
    Stops after receiving the first cancel request.
    """
    threading.Thread(target=_read_stdin, daemon=True).start()


def is_cancel_requested():

    global _cancel_requested
    return _cancel_requested


def process_cancel_request():
    """
    Kill subprocess if main process requested cancel.
    """
    global _cancel_requested
    if _cancel_requested:
        os._exit(1)


# endregion