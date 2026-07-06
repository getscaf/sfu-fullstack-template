import logging
import os

logger = logging.getLogger(__name__)


def pycharm_debugger():
    logger.info("Pycharm pydevd connecting...")
    import pydevd_pycharm

    host_ip = os.getenv("DOCKER_GATEWAY_IP")
    try:
        pydevd_pycharm.settrace(
            host_ip, port=6400, stdoutToServer=True, stderrToServer=True, suspend=False
        )
    except ConnectionRefusedError:
        msg = "Debugger connection failed. Check IDE debugger is running and try again. Continuing without debugger."
        logger.error(msg.upper())


def vscode_debugger():
    logger.info("VSCode debugpy starting...")
    import debugpy

    # debugpy.listen() may only be called once per process; breakpoint() can fire
    # multiple times, and runserver's reloader runs request code in the RUN_MAIN
    # worker. Guard against re-listen; wait for the IDE to attach before pausing.
    if not debugpy.is_client_connected():
        try:
            debugpy.listen(("0.0.0.0", 5678))
            logger.info(
                "debugpy listening on 0.0.0.0:5678 - waiting for VSCode to attach..."
            )
        except RuntimeError:
            logger.info("debugpy already listening; waiting for client.")
        debugpy.wait_for_client()
        logger.info("VSCode debugger attached.")

    debugpy.breakpoint()
