"""
Asobo addons utilities.

WARNING :
Package starts with a "_" so it is loaded first.
So do not rename this addon.
"""

from .registration import Registration

RG = None
RG = Registration(
    file=__file__,
    package=__package__
)

RG.register()

def _pre_reload_cleanup():
    # Used by addons reloader
    if RG:
        RG.unregister()