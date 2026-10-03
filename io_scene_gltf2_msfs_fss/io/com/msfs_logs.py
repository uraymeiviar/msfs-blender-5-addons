import bpy
from _addons_common.logging.logger import Logger

MSFS2024_LOGGER : Logger


def get_logger() -> Logger:
    global MSFS2024_LOGGER
    return MSFS2024_LOGGER


def process_logger_report(operator: bpy.types.Operator, logger: Logger):

    logs_props = logger.get_logs_prop()
    if not logs_props:
        return

    if logs_props.error_count:
        operator.report(
            {"ERROR"}, 
            f"{logs_props.error_count} errors occured during export!"
        )
    elif logs_props.warning_count:
        operator.report(
            {"WARNING"}, 
            f"{logs_props.warning_count} warnings occured during export."
        )
    else:
        operator.report({"INFO"}, "Export Done!")
    MSFS2024_LOGGER.push_logs_in_ui()


def register():
    global MSFS2024_LOGGER
    MSFS2024_LOGGER = Logger(unique_name="MSFS2024")


def unregister():
    global MSFS2024_LOGGER
    try:
        MSFS2024_LOGGER.unregister()
    except:
        pass
