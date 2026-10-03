# try:
#     import debugpy
# except:
#     pass

import bpy
import threading
import time
import socket
import json

from max_bridge_msfs_2024.host import HOST, BLENDERPORT
from max_bridge_msfs_2024 import importers
from max_bridge_msfs_2024.common import ui_utils

from bpy.app.handlers import persistent

server_running = False

bridge_data = None
threaded_socket = None
thread_checker = None


class ThreadedSocket(threading.Thread):

    # Initialize the thread and assign the method (i.e. importer) to be called when it receives JSON data.
    def __init__(self, importer):
        threading.Thread.__init__(self)
        self.importer = importer
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.run_socket = True
        self.TotalData = b""

    # Start the thread to start listing to the port.
    def run(self):
        # try:
        #     debugpy.debug_this_thread()
        # except:
        #     pass

        try:
            # Binding the socket to host and port number mentioned at the start.
            self.socket.bind((HOST, BLENDERPORT))
            # Run until the thread starts receiving data.

            while self.run_socket:
                self.socket.listen(5)
                client, _ = self.socket.accept()
                data = ""
                buffer_size = 4096 * 2

                data = client.recv(buffer_size)

                if data != "":
                    self.TotalData = b""
                    self.TotalData += (
                        data  # Append the previously received data to the Total Data.
                    )
                    # Keep running until the connection is open and we are receiving data.
                    while True:
                        data = client.recv(4096 * 2)
                        if data:
                            self.TotalData += data
                        else:
                            self.importer(self.TotalData)
                            break
        except:  # temporary

            pass

    def stop(self):
        self.run_socket = False
        self.socket.close()
        self.join()
        self.importer = None


class ThreadChecker(threading.Thread):
    """
    Send kill signal to thread when mainthread is not alive (blender closing)
    """

    def __init__(self):
        threading.Thread.__init__(self)
        self.run_checker = True

    # Start the thread to start listing to the port.
    def run(self):

        while self.run_checker:
            time.sleep(3)
            for i in threading.enumerate():
                if i.getName() == "MainThread" and i.is_alive() == False:
                    global threaded_socket
                    threaded_socket.stop()
                    break

    def stop(self):
        self.run_checker = False
        self.join()


@persistent
def load_plugin(scene):
    try:
        bpy.ops.maxbridge.startserver()
        print("execute after scene load")
    except Exception as e:
        print("Bridge Plugin Error::Could not start the plugin. Description: ", str(e))


def is_handler_enabled():
    return (
        "load_plugin" in bpy.app.handlers.load_post[0].__name__.lower()
        or load_plugin in bpy.app.handlers.load_post
    )


class MAXBRIDGE_OT_start_max_bridge(bpy.types.Operator):

    bl_idname = "maxbridge.startserver"
    bl_label = "Start 3dsMax Bridge"

    def execute(self, context):

        try:
            if not is_handler_enabled():
                bpy.app.handlers.load_post.append(load_plugin)
            global bridge_data
            bridge_data = None
            self.start_server()
            bpy.app.timers.register(self.data_monitor)
            return {"FINISHED"}
        except Exception as e:
            print("Megascans Plugin Error starting blender plugin. Error: ", str(e))
            return {"FAILED"}

    def data_monitor(self):
        """
        Check everything second if bridge_data has been updated.
        """
        global bridge_data
        if not bridge_data : 
            return 1
        
        data = bridge_data
        json_data = json.loads(data)
        usd_path = json_data.get("path", None)
        if usd_path:
            importers.import_bridge_usd(usd_path)
        bridge_data = None
        return 1

    def importer(self, recv_data):
        global bridge_data
        try:
            bridge_data = recv_data
        except Exception as e:
            print(
                "MaxBridge Plugin Error starting blender plugin (importer). Error: ",
                str(e),
            )
            return {"FAILED"}
        
    @staticmethod
    def is_socket_launched() -> bool:
        """Check if socket is already launch by another process.
        Very usefull to check if other instances of Blender launched bridge.

        Returns:
            _description_
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1) 
                s.connect((HOST, BLENDERPORT))
                s.send(b"")
                return True
        except socket.error:
            return False
        

    def start_server(self):
        global server_running
        global threaded_socket
        global thread_checker
        if server_running:
            return
        
        if self.is_socket_launched():
            ui_utils.message_popup(
                ui_utils.PopUpLevel.CRITICAL,
                title="Bridge",
                message=("Bridge is already launched on another Blender instance!")
            )
            return 
        
        try:
            threaded_socket = ThreadedSocket(self.importer)
            threaded_socket.start()

            thread_checker = ThreadChecker()
            thread_checker.start()
            server_running = True
        except Exception as e:
            print(
                "MaxBridge Plugin Error starting blender plugin (socketMonitor). Error: ",
                str(e),
            )
            return {"FAILED"}


class MAXBRIDGE_OT_stop_max_bridge(bpy.types.Operator):

    bl_idname = "maxbridge.stopserver"
    bl_label = "Stop 3dsMax Bridge"

    def execute(self, context):

        if len(bpy.app.handlers.load_post) > 0:
            # remove handler
            if is_handler_enabled():
                bpy.app.handlers.load_post.remove(load_plugin)

        # stop server and thread next
        global thread_checker
        if thread_checker:
            thread_checker.stop()
            thread_checker = None
        global threaded_socket
        if threaded_socket:
            threaded_socket.stop()
            threaded_socket = None
        global server_running
        server_running = False
        return {"FINISHED"}

def unregister():
    MAXBRIDGE_OT_stop_max_bridge.execute(None, None)
