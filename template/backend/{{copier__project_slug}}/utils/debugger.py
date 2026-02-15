import logging
import os

logger = logging.getLogger(__name__)


def pycharm_debugger():
    logger.info("Pycharm pydevd connecting...")
    import pydevd_pycharm

    host_ip = os.getenv("DOCKER_GATEWAY_IP")
    debug_port = int(os.getenv("DEBUGGER_PORT", default=6400))
    try:
        pydevd_pycharm.settrace(
            host_ip, port=debug_port, stdoutToServer=True, stderrToServer=True, suspend=False
        )
    except ConnectionRefusedError:
        msg = "Debugger connection failed. Check IDE debugger is running and try again. Continuing without debugger."
        logger.error(msg.upper())


def vscode_debugger():
    logger.info("Debugpy connecting...")
    import debugpy
    debug_port = int(os.getenv("DEBUGGER_PORT", default=5678))
    debugpy.listen(("0.0.0.0", debug_port))  # nosec B104
