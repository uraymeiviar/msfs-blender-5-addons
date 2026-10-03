"""
This module is identical in 3dsMax Plugin and Blender Addon.
"""
import socket

def get_ip_address():
    """
    LOCALHOST is super slow use ip instead.
    """
    hostname = socket.gethostname()
    ip_address = socket.gethostbyname(hostname)
    return ip_address

HOST = get_ip_address()
MAXPORT = 5601
BLENDERPORT=5600
