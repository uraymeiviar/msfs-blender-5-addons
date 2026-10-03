import bpy
from enum import Enum

class PopUpLevel(Enum):
    INFO = "information"
    CRITICAL = "critical"
    QUESTION = "question"
    WARNING = "warning"


def message_popup(level: PopUpLevel, title:str="Bridge", message:str=""):
    def draw(self, context):
        layout = self.layout
        layout.label(text=message)
    icon = 'INFO'
    if level == PopUpLevel.CRITICAL:
        icon = "CANCEL"
    elif level == PopUpLevel.QUESTION:
        icon = "QUESTION"
    elif level == PopUpLevel.WARNING:
        icon = "ERROR"
    bpy.context.window_manager.popup_menu(draw, title=title, icon=icon)