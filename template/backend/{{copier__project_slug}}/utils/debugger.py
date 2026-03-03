import logging
import os
import socket
import struct


logger = logging.getLogger(__name__)

def get_gateway_ip():
    with open("/proc/net/route") as f:
        for line in f.readlines()[1:]:
            p = line.split()
            if p and p[1] == "00000000":
                return socket.inet_ntoa(struct.pack("<L", int(p[2], 16)))


def pycharm_debugger():
    logger.info("Pycharm pydevd connecting...")
    import pydevd_pycharm
    logger.info("attempting to get host_ip")
    host_ip = get_gateway_ip()
    logger.info(f"{host_ip=}")
    debug_port = int(os.getenv("DEBUGGER_PORT", default=6400))
    try:
        pydevd_pycharm.settrace(host_ip, port=debug_port, suspend=False)
    except ConnectionRefusedError:
        msg = "Debugger connection failed. Check IDE debugger is running and try again. Continuing without debugger."
        logger.error(msg.upper())


def vscode_debugger():
    logger.info("Debugpy connecting...")
    import debugpy
    debug_port = int(os.getenv("DEBUGGER_PORT", default=5678))
    debugpy.listen(("0.0.0.0", debug_port))  # nosec B104
