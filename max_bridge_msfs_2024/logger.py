import logging
from pathlib import Path
import sys

LOGGER = None

log_filepath = Path.home() / "Documents/From_Blender_MaxBridge.log"


def getLogger():
    global LOGGER
    if log_filepath.exists():
        try:
            log_filepath.unlink()
        except PermissionError:  # multiple instances of blender
            pass

    if LOGGER is None:
        LOGGER = logging.getLogger(__name__)
        if LOGGER.handlers:
            LOGGER.handlers.clear()

        LOGGER.propagate = False
        LOGGER.setLevel(logging.DEBUG)

        file_handler = logging.FileHandler(log_filepath, mode="a+")
        LOGGER.addHandler(file_handler)
        formatter = logging.Formatter("%(asctime)-15s %(levelname)-8s %(message)s")
        file_handler.setFormatter(formatter)

        # Blender console logging (INFO+ only)
        console_handler = logging.StreamHandler(sys.__stdout__)
        console_handler.setLevel(logging.INFO)
        formatter = logging.Formatter("%(levelname)-8s %(message)s")
        console_handler.setFormatter(formatter)
        LOGGER.addHandler(console_handler)

    return LOGGER
