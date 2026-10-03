from __future__ import annotations
from typing import TYPE_CHECKING
import time
from dataclasses import dataclass, field
from enum import Enum
import bpy


from _addons_common.ui.tree_widget.view import UL_TreeView
from _addons_common.ui.tree_widget.manager import TreeManager

if TYPE_CHECKING:
    from _addons_common.ui.tree_widget.item import TreeItem


class LogLevels(Enum):
    DEBUG = ("[DEBUG]", "Debugging information")
    INFO = ("[INFO]", "General information")
    WARNING = ("[WARNING]", "Something might be wrong")
    ERROR = ("[ERROR]", "An error occurred")

    def __init__(self, tag, description):
        self.tag = tag
        self.description = description

class LogEntry(bpy.types.PropertyGroup):
    message: bpy.props.StringProperty(name="Message")  # type: ignore
    details: bpy.props.StringProperty(name="Details")  # type: ignore
    level: bpy.props.EnumProperty(
        name="Level",
        items=[
            (LogLevels.DEBUG.name, LogLevels.DEBUG.tag, LogLevels.DEBUG.description),
            (LogLevels.INFO.name, LogLevels.INFO.tag, LogLevels.INFO.description),
            (LogLevels.WARNING.name,LogLevels.WARNING.tag,LogLevels.WARNING.description),
            (LogLevels.ERROR.name, LogLevels.ERROR.tag, LogLevels.ERROR.description),
        ],
        default=LogLevels.INFO.name,
    )  # type: ignore
    timestamp: bpy.props.FloatProperty(name="Timestamp")  # type: ignore

class Logs(bpy.types.PropertyGroup):
    logs: bpy.props.CollectionProperty(type=LogEntry)  # type: ignore
    debug_count: bpy.props.IntProperty()  # type: ignore
    info_count: bpy.props.IntProperty()  # type: ignore
    warning_count: bpy.props.IntProperty()  # type: ignore
    error_count: bpy.props.IntProperty()  # type: ignore

@dataclass
class LoggerReport:
    debug_logs: list[LogEntry] = field(default_factory=list)
    info_logs: list[LogEntry] = field(default_factory=list)
    warning_logs: list[LogEntry] = field(default_factory=list)
    error_logs: list[LogEntry] = field(default_factory=list)


class LOGGER_UL_Logs(bpy.types.UIList, UL_TreeView):

    use_filter_invert: bpy.props.BoolProperty(
        name="Filter Invert", default=False, options=set()
    )  # type: ignore

    display_info: bpy.props.BoolProperty(
        name="display Info", default=True, options=set()
    )  # type: ignore

    display_warning: bpy.props.BoolProperty(
        name="display warning", default=True, options=set()
    )  # type: ignore

    display_error: bpy.props.BoolProperty(
        name="display error", default=True, options=set()
    )  # type: ignore


    @staticmethod
    def draw_log_entry(data: LogEntry, item, index, row: bpy.types.UILayout):
        level = data.level
        if level == LogLevels.INFO.name:
            row.label(text=data.message, icon="INFO")
        elif level == LogLevels.WARNING.name:
            row.label(text=data.message, icon="ERROR")
        elif level == LogLevels.ERROR.name:
            row.alert = True
            row.label(text=data.message, icon="CANCEL")
        elif level == LogLevels.DEBUG.name:
            row.label(text=data.message, icon="INFO")

    @classmethod
    def custom_draw_item(cls, context, index, item, layout):
        item: TreeItem
        data = item.get_data()
        if not data:
            return

        if isinstance(data, LogEntry):
            cls.draw_log_entry(data, item, index, layout)

        else:
            layout.label(text="Not Implemented")

    @staticmethod
    def draw_header_preset(context, layout: bpy.types.UILayout, logger: Logger):
        """Show error count in panel header"""
        logs_props = logger.get_logs_prop()
        if not logs_props:
            return
        if logs_props.error_count:

            row = layout.row(align=True)
            row.alert = True
            row.label(text=f"{logs_props.error_count} Error(s)")

        ope = layout.operator(LOGGER_OT_Clear_Logs.bl_idname, text="", icon="TRASH")
        ope.logger_name = logger.unique_name
        

    @classmethod
    def draw_UL_TreeView(
        cls, 
        context, 
        layout: bpy.types.UILayout, 
        rows: int = 10, 
        type: str = "DEFAULT"
    ):
        super().draw_UL_TreeView(context, layout, rows, type)

        tree_manager = cls.get_tree_manager()
        if not tree_manager:
            return
        active_item: TreeItem = tree_manager.get_active_item()

        if active_item:
            data: LogEntry = active_item.get_data()
            if not data or not data.details:
                return
            row = layout.row()
            row.label(text="Details:")
            row = row.row()
            row.alignment = "LEFT"
            ope = row.operator(
                operator=LOGGER_OT_Copy_Log_Text.bl_idname, icon="COPYDOWN", text=""
            )
            ope.message = data.message
            ope.details = data.details
            box = layout.box()

            for line in str(data.details).splitlines():
                box.label(text=line)


    def draw_filter(self, context, layout):
        row = layout.row(align=True)
        row.prop(self, "display_info", icon="INFO", icon_only=True)
        row.prop(self, "display_warning", icon="ERROR", icon_only=True)
        row.prop(self, "display_error", icon="CANCEL", icon_only=True)

        row.prop(self, "filter_name", text="", icon="VIEWZOOM")
        row.prop(
            self, "use_filter_invert", text="", icon="ARROW_LEFTRIGHT", icon_only=True
        )

    def filter_items(self, context, data, propname):
        """
        This function gets the collection property (as the usual tuple (data, propname)), and must return two lists:
        * The first one is for filtering, it must contain 32bit integers were self.bitflag_filter_item marks the
          matching item as filtered (i.e. to be shown). The upper 16 bits (including self.bitflag_filter_item) are
          reserved for internal use, the lower 16 bits are free for custom use.
        * The second one is for reordering, it must return a list containing the new indices of the items (which
          gives us a mapping org_idx -> new_idx).

        Please note that the default UI_UL_list defines helper functions for common tasks (see its doc for more info).
        If you do not make filtering and/or ordering, return empty list(s) (this will be more efficient than
        returning full lists doing nothing!).

        """
        flt_flags, flt_neworder = super().filter_items(context, data, propname)

        ui_list: list[TreeItem] = getattr(data, propname)
        helper_funcs = bpy.types.UI_UL_list

        # Filtering by name
        data_list: list[LogEntry] = list([item.get_data() for item in ui_list])

        if self.filter_name:
            flt_flags = helper_funcs.filter_items_by_name(
                self.filter_name,
                self.bitflag_filter_item,
                data_list,
                "message",
                reverse=self.use_filter_invert,
            )

        for i, data in enumerate(data_list):
            if not self.display_info and data.level == LogLevels.INFO.name:
                flt_flags[i] &= ~self.bitflag_filter_item
            if not self.display_warning and data.level == LogLevels.WARNING.name:
                flt_flags[i] &= ~self.bitflag_filter_item
            if not self.display_error and data.level == LogLevels.ERROR.name:
                flt_flags[i] &= ~self.bitflag_filter_item

        self.save_flags_in_tree_manager(flt_flags)

        return flt_flags, flt_neworder
    
    

class LOGGER_OT_Copy_Log_Text(bpy.types.Operator):
    bl_idname = "logger.copy_text"
    bl_label = "Copy Log details to clipboard"

    message: bpy.props.StringProperty(default="")  # type: ignore
    details: bpy.props.StringProperty(default="")  # type: ignore

    def execute(self, context):
        text = f"{self.message}:\n{self.details}"
        context.window_manager.clipboard = text
        self.report({"INFO"}, "Text copied to clipboard")
        return {"FINISHED"}

class LOGGER_OT_Clear_Logs(bpy.types.Operator):
    bl_idname = "logger.clear_logs"
    bl_label = "Clear Logs"

    logger_name: bpy.props.StringProperty(default="")  # type: ignore

    def execute(self, context):

        logger: Logger = Logger.logger_instances.get(self.logger_name, None)
        if not logger:
            return {"FINISHED"}
        logger.clear_logs()
        return {"FINISHED"}



class LoggerTreeManager(TreeManager):
    pass
    

class Logger:

    logger_instances = {}
    logger_tree_managers = {}
    detail_tag = "[DETAILS]"
    ul_tree_view_class = LOGGER_UL_Logs

    def __init__(self, unique_name: str) -> None:
        # Remove white spaces in unique name
        unique_name = "".join(unique_name.split())
        if unique_name in Logger.logger_instances:
            raise Exception("A Logger with same name already exists!")
        self.unique_name = unique_name
        self.collection_name = f"{type(self).__name__}_{self.unique_name}"
        self.register()
        # Store all Logs Tree Managers in class attribute
        self.logger_tree_managers[unique_name] = LoggerTreeManager(
            data_collection_getter=lambda: self.get_logs_prop().logs,
            ul_tree_view_class=self.ul_tree_view_class,
            alphabetical_order=False,
            multiselection_support=False,
            checkable_items=False,
        )
        self.tree_manager: LoggerTreeManager = self.logger_tree_managers[unique_name]

        # Save all instances of class
        Logger.logger_instances[self.unique_name] = self
        

    def _get_logger_unique_tag(self):
        return f"[{self.unique_name}]"

    def _print_log(self, level: LogLevels, message: str, details: str = ""):
        """Print log entry message using this nomenclature :
            [%unique_name%][%level_tag%] %message% ["DETAILS"]
            %details msssage%
            ["DETAILS"]

        ["DETAILS"] tags are only added when details are provided.
        """
        output = f"\n{self._get_logger_unique_tag()}{level.tag} {message}"
        if details:
            output = f"{output} {self.detail_tag}"
        print(output, flush=True)
        if details:
            print(f"\n{details}", flush=True)
            print(f"\n{self.detail_tag}", flush=True)

    def _print_item_log(self, item: LogEntry):
        self._print_log(LogLevels[item.level], item.message, item.details)

    def get_logs_prop(self) -> Logs | None:
        try:
            return getattr(bpy.context.window_manager, self.collection_name)
        except:
            self._print_log(
                level=LogLevels.ERROR, 
                message="Can't get logs collection property"
            )
            return None

    def _add_log(
        self, message: str, details: str = "", level: LogLevels = LogLevels.INFO
    ):

        logs_prop = self.get_logs_prop()
        if logs_prop is None:
            return
        log_collection = logs_prop.logs
        log_collection: bpy.types.bpy_prop_collection_idprop
        entry = log_collection.add()
        # make sure message is a one liner
        message = "".join(message.splitlines())
        entry.message = message
        entry.details = details
        entry.level = level.name
        if entry.level == LogLevels.DEBUG.name:
            logs_prop.debug_count += 1
        elif entry.level == LogLevels.INFO.name:
            logs_prop.info_count += 1
        elif entry.level == LogLevels.WARNING.name:
            logs_prop.warning_count += 1
        elif entry.level == LogLevels.ERROR.name:
            logs_prop.error_count += 1

        entry.timestamp = time.time()

        self._print_item_log(entry)

    def debug(self, message: str, details: str = ""):
        self._add_log(message, details, level=LogLevels.DEBUG)

    def info(self, message: str, details: str = ""):
        self._add_log(message, details, level=LogLevels.INFO)

    def warning(self, message: str, details: str = ""):
        self._add_log(message, details, level=LogLevels.WARNING)

    def error(self, message: str, details: str = ""):
        self._add_log(message, details, level=LogLevels.ERROR)

    def logs_from_strings(self, log_strings: list[str]):
        """
        Create log entries from strings that use logger formatting convention.
        """
        # list of list containing (tag, message, details)
        logs: list[list[str]] = []
        parsing_details = False
        for log_string in log_strings:
            log_string = log_string.strip()

            if parsing_details and log_string.startswith(self.detail_tag):
                # End of details parsing
                parsing_details = False

            if parsing_details:
                # Parse details string that can be on multiple lines
                logs[-1][2] += log_string + "\n"
                continue

            logger_unique_tag = self._get_logger_unique_tag()
            if not log_string.startswith(logger_unique_tag):
                continue

            log_string = log_string.removeprefix(logger_unique_tag)

            tag = None
            if log_string.startswith(LogLevels.DEBUG.tag):
                tag = LogLevels.DEBUG.tag
            elif log_string.startswith(LogLevels.INFO.tag):
                tag = LogLevels.INFO.tag
            elif log_string.startswith(LogLevels.WARNING.tag):
                tag = LogLevels.WARNING.tag

            elif log_string.startswith(LogLevels.ERROR.tag):
                tag = LogLevels.ERROR.tag

            if not tag:
                continue

            message = log_string.removeprefix(tag)
            if message.endswith(self.detail_tag):
                message = message.removesuffix(self.detail_tag)
                parsing_details = True
            logs.append([tag, message, ""])

        # Create log entries
        for log in logs:
            tag = log[0]
            message = log[1]
            details = log[2]
            if tag == LogLevels.DEBUG.tag:
                self.debug(message, details)
            elif tag == LogLevels.INFO.tag:
                self.info(message, details)
            elif tag == LogLevels.WARNING.tag:
                self.warning(message, details)
            elif tag == LogLevels.ERROR.tag:
                self.error(message, details)

    def push_logs_in_ui(self):
        if not self.tree_manager:
            return
        self.tree_manager.generate_ui_tree_collection()

    def clear_logs(self):
        logs_prop = self.get_logs_prop()
        if not logs_prop:
            return
        logs_prop.logs.clear()
        logs_prop.debug_count = 0
        logs_prop.info_count = 0
        logs_prop.warning_count = 0
        logs_prop.error_count = 0

        if not self.tree_manager:
            return

        self.tree_manager.generate_ui_tree_collection()

    def register(self):
        if getattr(bpy.types.WindowManager, self.unique_name, False):
            return

        setattr(
            bpy.types.WindowManager,
            self.collection_name,
            bpy.props.PointerProperty(type=Logs),
        )

    def unregister(self):
        try:
            Logger.logger_instances.pop(self.unique_name)
            delattr(bpy.types.WindowManager, self.collection_name)
            self.tree_manager.unregister()
        except Exception:
            pass
