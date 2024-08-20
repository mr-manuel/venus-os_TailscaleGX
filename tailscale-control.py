#!/usr/bin/env python
#
# On startup the dbus settings and service are created
#   tailscale-control then passes to mainLoop which runs once per second:
# 	  starts / stops the tailscale-backend based on com.victronenergy.settings/Settings/Services/Tailscale/Enabled
# 	  scans status from tailscale link
# 	  provides status and prompting to the GUI during this process
# 	    in the end providing the user the IP address they must use
# 	    to connect to the GX device.


import logging
import os
import re
import subprocess
import sys
from socket import gethostname

import dbus
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

# Victron packages
sys.path.insert(1, os.path.join(os.path.dirname(__file__), "ext/velib_python"))
from vedbus import VeDbusService  # noqa: E402
from settingsdevice import SettingsDevice  # noqa: E402

# TEMPORARY SOLUTION | start
# Until QR code is generated in the GUI
sys.path.insert(1, os.path.join(os.path.dirname(__file__), "ext"))
import qrcode  # noqa: E402
import io  # noqa: E402
import base64  # noqa: E402

# TEMPORARY SOLUTION | end


def sendCommand(command: list = None, shell: bool = False) -> tuple:
    """
    # sends a unix command
    # e.g. sendCommand ( [ 'svc', '-u' , serviceName ] )
    #
    # :param command: list of command and arguments
    # :param shell: boolean, if True the command is executed in a shell
    # :return: stdout, stderr, exit code
    """
    if command is None:
        logging.error("sendCommand(): no command specified")
        return None, None, None

    try:
        proc = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=shell
        )
    except Exception:
        exception_type, exception_object, exception_traceback = sys.exc_info()
        file = exception_traceback.tb_frame.f_code.co_filename
        line = exception_traceback.tb_lineno
        logging.error("")
        logging.error(
            f"Exception occurred: {repr(exception_object)} of type {exception_type} in {file} line #{line}"
        )
        logging.error("sendCommand() failed: " + " ".join(command))
        return None, None, None
    else:
        out, err = proc.communicate()
        stdout = out.decode().strip()
        stderr = err.decode().strip()
        return stdout, stderr, proc.returncode


def cleanup_error_message(error_message: str) -> str:
    """
    cleanup error message

    :param error_message: error message to cleanup
    :return: cleaned up error message
    """
    # remove specific strings
    error_message = error_message.replace(
        'timeout waiting for Tailscale service to enter a Running state; check health with "tailscale status"',
        "",
    )

    return error_message


def cleanup_hostname(hostname: str) -> str:
    """
    cleanup hostname

    :param hostname: hostname to cleanup
    :return: cleaned up hostname
    """
    # replace some characters
    hostname = hostname.replace("\\", "-")

    # convert to lowercase
    hostname = hostname.lower()

    # remove any character that is not a letter, digit, or hyphen
    hostname = re.sub("[^a-z0-9-]", "", hostname)

    # remove leading and trailing hyphens
    hostname = hostname.strip("-")

    return hostname


# static variables for main and mainLoop
DbusSettings = None
DbusService = None

# define states
STATE_INITIALIZING = 0
STATE_BACKEND_STARTING = 1
STATE_BACKEND_STOPPED = 2
STATE_CONNECTION_FAILED = 3
STATE_STOPPED = 4
STATE_LOGGED_OUT = 5
STATE_WAIT_FOR_RESPONSE = 6
STATE_WAIT_FOR_LOGIN = 7
STATE_NO_STATE = 8
STATE_CONNECTION_OK = 100

# define global variables
stateCurrent = STATE_INITIALIZING
statePrevious = STATE_INITIALIZING
systemnameObject = None
systemnameCurrent = ""
systemnamePrevious = ""


def mainLoop():
    """
    Runs every second and checks the status of the tailscale link and checks for GUI commands
    """
    global DbusSettings, DbusService
    global stateCurrent, statePrevious
    global systemnameCurrent, systemnamePrevious

    backendRunning = None
    tailscaleEnabled = False

    loginInfo = ""

    # check if the system name object is set
    if systemnameObject is not None:
        # get the current system name
        systemnameCurrent = systemnameObject.GetValue()

    # check if the system name has changed
    if systemnameCurrent != systemnamePrevious:
        logging.info(
            f'System name has changed from "{systemnamePrevious}" to "{systemnameCurrent}"'
        )

        # check if the previous system name or the sytem hostname was set as the hostname
        # this is to make sure, that a custom set hostname is not overwritten
        if (
            cleanup_hostname(systemnamePrevious) == DbusSettings["Hostname"]
            or gethostname() == DbusSettings["Hostname"]
        ):
            # update the hostname
            logging.info(
                f'Changing hostname from "{DbusSettings["Hostname"]}" to "{cleanup_hostname(systemnameCurrent)}"'
            )
            DbusSettings["Hostname"] = cleanup_hostname(systemnameCurrent)

        # set the current system name as the previous
        systemnamePrevious = systemnameCurrent

    # check if hostname is empty
    if DbusSettings["Hostname"] == "":
        # if there is a system name, set it as the hostname
        if systemnameCurrent != "":
            DbusSettings["Hostname"] = cleanup_hostname(systemnameCurrent)
            logging.info(
                f'System name is "{systemnameCurrent}", using is as hostname "{DbusSettings["Hostname"]}"'
            )
        else:
            DbusSettings["Hostname"] = gethostname()
            logging.info(
                f'System name is empty, using system hostname "{DbusSettings["Hostname"]}"'
            )

    # check if backend is running
    stdout, stderr, exitCode = sendCommand(["svstat", "/service/tailscale-backend"])
    if stdout is None:
        logging.warning("tailscale-backend not in services")
        backendRunning = None
    elif stderr is None or "does not exist" in stderr:
        logging.warning("tailscale-backend not in services")
        backendRunning = None
    elif stdout is not None and ": up" in stdout:
        backendRunning = True
    else:
        backendRunning = False

    tailscaleEnabled = DbusSettings["Enabled"] == 1

    # clear error message if tailscale is disabled
    if not tailscaleEnabled and DbusService["/ErrorMessage"] != "":
        DbusService["/ErrorMessage"] = ""

    # *** this will be managed by the Venus OS plattform in future | start ***
    # see https://github.com/search?q=repo%3Avictronenergy%2Fvenus-platform%20tailscale&type=code

    # start backend, if tailscale was enabled and the backend is not running
    if tailscaleEnabled and backendRunning is False:
        logging.info("starting tailscale-backend")
        stdout, stderr, exitCode = sendCommand(
            ["svc", "-u", "/service/tailscale-backend"]
        )

        if exitCode != 0:
            logging.error("starting tailscale-backend failed " + str(exitCode))
            logging.error(stderr)

        stateCurrent = STATE_BACKEND_STARTING
    # stop backend, if tailscale was disabled and the backend is running
    elif not tailscaleEnabled and backendRunning is True:

        # execute tailscale down before stopping backend
        # else config changes won't be applied
        logging.info("executing /usr/bin/tailscale down")
        stdout, stderr, exitCode = sendCommand(["/usr/bin/tailscale", "down"])

        if exitCode != 0:
            logging.error("executing /usr/bin/tailscale down failed " + str(exitCode))
            logging.error(stderr)

        logging.info("stopping tailscale-backend")
        stdout, stderr, exitCode = sendCommand(
            ["svc", "-d", "/service/tailscale-backend"]
        )

        if exitCode != 0:
            logging.error("stopping tailscale-backend failed " + str(exitCode))
            logging.error(stderr)

        backendRunning = False
    # *** this will be managed by the Venus OS plattform in future | end ***

    if backendRunning:
        # check for GUI commands
        guiCommand = DbusService["/GuiCommand"]

        # check if GUI command is not empty
        if guiCommand != "":
            # acknowledge receipt of command so another can be sent
            DbusService["/GuiCommand"] = ""

            if guiCommand == "logout":
                logging.info("logout command received")
                # logout takes time and can't specify a timeout so provide feedback first
                DbusService["/State"] = STATE_WAIT_FOR_RESPONSE
                stdout, stderr, exitCode = sendCommand(["/usr/bin/tailscale", "logout"])

                if exitCode != 0:
                    logging.error("tailscale logout failed " + str(exitCode))
                    logging.error(stderr)
                else:
                    stateCurrent = STATE_WAIT_FOR_RESPONSE
            else:
                logging.warning("invalid command received " + guiCommand)

        # get current status from tailscale and update state
        stdout, stderr, exitCode = sendCommand(["/usr/bin/tailscale", "status"])

        # don't update state if we don't get a response
        if stdout is None or stderr is None:
            pass
        elif "Failed to connect" in stderr:
            stateCurrent = STATE_CONNECTION_FAILED
        elif "Tailscale is stopped" in stdout:
            stateCurrent = STATE_STOPPED
        elif "Log in at" in stdout:
            stateCurrent = STATE_WAIT_FOR_LOGIN
            lines = stdout.splitlines()
            loginInfo = lines[1].replace("Log in at: ", "")
        elif "Logged out" in stdout:
            # can get back to this condition while loggin in
            # so wait for another condition to update state
            if statePrevious != STATE_WAIT_FOR_RESPONSE:
                stateCurrent = STATE_LOGGED_OUT
        elif "NoState" in stdout:
            # When Tailscale is already logged in, but has no internet connection
            # the state is "unexpected state: NoState"
            # If logged out, the status only shows "Logged out"
            stateCurrent = STATE_NO_STATE
        elif exitCode == 0:
            stateCurrent = STATE_CONNECTION_OK

            # extract this host's name from status message
            # this allows to show the hostname, if it was changed in the Tailscale admin panel
            if DbusService["/IPv4"] != "":
                for line in stdout.splitlines():
                    if DbusService["/IPv4"] in line:
                        hostname = line.split()[1]

                        if hostname != DbusSettings["Hostname"]:
                            logging.info(
                                f'Hostname changed from "{DbusSettings["Hostname"]}" to'
                                + f' "{hostname}" from status message'
                            )
                            DbusSettings["Hostname"] = hostname
        # don't update state if we don't recognize the response
        else:
            pass

        # make changes necessary to bring connection up
        # 	up will fully connect if login had succeeded
        # 	or ask for login if not
        # 	next get status pass will indicate that
        #   call is made with a short timeout so we can monitor status
        # 	but need to defer future tailscale commands until
        # 	tailscale has processed the first one
        # 	ALMOST any state change will signal the wait is over
        # 	(status not included)

        if stateCurrent != statePrevious:
            logging.info(f"state change from {statePrevious} to {stateCurrent}")

            # create command line arguments for tailscale up, this allows a dynamic configuration
            command_line_args = []

            # add timeout
            command_line_args.append("--timeout=0.5s")

            # set routes to advertise
            # https://tailscale.com/kb/1019/subnets
            if DbusSettings["AdvertiseRoutes"] != "":
                # remove unallowed characters
                DbusSettings["AdvertiseRoutes"] = re.sub(
                    r"[^0-9./,]", "", DbusSettings["AdvertiseRoutes"]
                )

                command_line_args.append(
                    "--advertise-routes=" + DbusSettings["AdvertiseRoutes"]
                )

            # set hostname
            if DbusSettings["Hostname"] != "":
                # cleanup hostname
                DbusSettings["Hostname"] = cleanup_hostname(DbusSettings["Hostname"])

                command_line_args.append("--hostname=" + DbusSettings["Hostname"])

            # set custom server url, for example to use headscale
            if DbusSettings["CustomServerUrl"] != "":
                # transform to lowercase
                DbusSettings["CustomServerUrl"] = DbusSettings[
                    "CustomServerUrl"
                ].lower()

                # remove http:// or https:// from URL
                DbusSettings["CustomServerUrl"] = re.sub(
                    r"https?://", "", DbusSettings["CustomServerUrl"]
                )

                # remove invalid characters from domain
                DbusSettings["CustomServerUrl"] = re.sub(
                    r"[^a-z0-9-:.]", "", DbusSettings["CustomServerUrl"]
                )

                command_line_args.append(
                    "--login-server=https://" + DbusSettings["CustomServerUrl"]
                )

            # check if accept-dns is not set in the custom arguments
            # accept-dns is disabled by default to prevent writing to root fs since it's read-only
            if "--accept-dns" not in DbusSettings["CustomArguments"]:
                command_line_args.append("--accept-dns=false")

            # check if subnet routing is enabled
            stdout, stderr, exitCode = sendCommand(
                ["sysctl -n net.ipv4.ip_forward"], shell=True
            )

            if exitCode == 0:
                ipForewardEnabled = stdout == "1"
            else:
                logging.warning(
                    f"#1 stdout: {stdout} - stderr: {stderr} - exitCode: {exitCode}"
                )

            # add ip forwarding if needed
            if (
                DbusSettings["AdvertiseRoutes"] != ""
                or "--advertise-exit-node" in DbusSettings["CustomArguments"]
            ) and ipForewardEnabled is not True:
                # execute command
                stdout, stderr, exitCode = sendCommand(
                    [
                        "sysctl -w net.ipv4.ip_forward=1",
                        "&&",
                        "sysctl -w net.ipv6.conf.all.forwarding=1",
                    ],
                    shell=True,
                )

                if exitCode == 0:
                    logging.info("ip forewarding enabled")
                else:
                    logging.warning(
                        f"#2 stdout: {stdout} - stderr: {stderr} - exitCode: {exitCode}"
                    )
            # remove ip forewarding if not needed
            elif (
                DbusSettings["AdvertiseRoutes"] == ""
                and "--advertise-exit-node" not in DbusSettings["CustomArguments"]
            ) and ipForewardEnabled is not False:
                # execute command
                stdout, stderr, exitCode = sendCommand(
                    [
                        "sysctl -w net.ipv4.ip_forward=0",
                        "&&",
                        "sysctl -w net.ipv6.conf.all.forwarding=0",
                    ],
                    shell=True,
                )

                if exitCode == 0:
                    logging.info("ip forewarding disabled")
                else:
                    logging.warning(
                        f"#3 stdout: {stdout} - stderr: {stderr} - exitCode: {exitCode}"
                    )

            # add custom arguments
            if DbusSettings["CustomArguments"] != "":
                # remove unallowed characters to prevent command injection
                DbusSettings["CustomServerUrl"] = re.sub(
                    r"[^a-zA-Z0-9-_=+:., ]", "", DbusSettings["CustomServerUrl"]
                )

                # split on one or multiple space
                command_line_args.extend(
                    re.split(r"\s+", DbusSettings["CustomArguments"])
                )

            if (
                stateCurrent == STATE_STOPPED
                and statePrevious != STATE_WAIT_FOR_RESPONSE
            ):
                # combine command line arguments
                command_line_args = [
                    "/usr/bin/tailscale",
                    "up",
                    "--reset",
                ] + command_line_args

                logging.info(f"executing {' '.join(command_line_args)}")
                stdout, stderr, exitCode = sendCommand(command_line_args)

                if exitCode != 0:
                    logging.error("tailscale up failed " + str(exitCode))
                    logging.error(stderr)
                    DbusService["/ErrorMessage"] = cleanup_error_message(stderr)
                else:
                    stateCurrent = STATE_WAIT_FOR_RESPONSE

            elif (
                stateCurrent == STATE_LOGGED_OUT
                and statePrevious != STATE_WAIT_FOR_RESPONSE
            ):
                # combine command line arguments
                command_line_args = [
                    "/usr/bin/tailscale",
                    "login",
                ] + command_line_args

                logging.info(f"executing {' '.join(command_line_args)}")
                stdout, stderr, exitCode = sendCommand(command_line_args)

                if exitCode != 0:
                    logging.error("tailscale login failed " + str(exitCode))
                    logging.error(stderr)
                    DbusService["/ErrorMessage"] = cleanup_error_message(stderr)
                else:
                    DbusService["/ErrorMessage"] = ""
                    stateCurrent = STATE_WAIT_FOR_RESPONSE

        # show IP addresses only if connected
        if stateCurrent == STATE_CONNECTION_OK:
            if statePrevious != STATE_CONNECTION_OK:
                logging.info("connection successful")

            stdout, stderr, exitCode = sendCommand(["/usr/bin/tailscale", "ip"])

            if exitCode != 0:
                logging.error("tailscale ip failed " + str(exitCode))
                logging.error(stderr)

            if stdout is not None and stdout != "":
                ipV4, ipV6 = stdout.splitlines()
                DbusService["/IPv4"] = ipV4
                DbusService["/IPv6"] = ipV6
            else:
                DbusService["/IPv4"] = "unknown"
                DbusService["/IPv6"] = "unknown"
        else:
            DbusService["/IPv4"] = ""
            DbusService["/IPv6"] = ""

    else:
        stateCurrent = STATE_BACKEND_STOPPED

    # update dbus values regardless of state of the link
    DbusService["/State"] = stateCurrent
    DbusService["/LoginLink"] = loginInfo

    # TEMPORARY SOLUTION | start
    if loginInfo != "":
        # Until QR code is generated in the GUI
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=5,
            border=0,
        )
        qr.add_data(loginInfo)
        qr.make(fit=True)

        img = qr.make_image(
            fill_color="#000000",
            back_color="#ffffff",
        )
        type(img)  # qrcode.image.pil.PilImage
        # img.save("/var/www/venus/tailscale.png")

        # Transform image to base64
        buffer = io.BytesIO()
        img.save(buffer)
        img_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
        DbusService["/LoginLinkQrCode"] = img_base64
    # TEMPORARY SOLUTION | end

    statePrevious = stateCurrent

    return True


def main():
    global DbusSettings, DbusService
    global systemnameObject

    # set logging level to include info level entries
    logging.basicConfig(level=logging.INFO)

    # get installed binary version
    try:
        # get the version by asking the tailscale binary
        stdout, stderr, exitCode = sendCommand(["/usr/bin/tailscale", "version"])

        if exitCode != 0:
            raise Exception("tailscale version command failed")

        installedVersion = stdout.splitlines()[0]

    except Exception:
        installedVersion = "unknown"

    # log the tailscale binary version
    logging.info(f"Tailscale binary version {installedVersion}")

    # set up dbus main loop to get async calls
    DBusGMainLoop(set_as_default=True)

    # create the settings object
    settingsList = {
        "AdvertiseRoutes": ["/Settings/Services/Tailscale/AdvertiseRoutes", "", 0, 0],
        "CustomArguments": ["/Settings/Services/Tailscale/CustomArguments", "", 0, 0],
        "CustomServerUrl": ["/Settings/Services/Tailscale/CustomServerUrl", "", 0, 0],
        "Enabled": ["/Settings/Services/Tailscale/Enabled", 0, 0, 1],
        "Hostname": ["/Settings/Services/Tailscale/Hostname", "", 0, 0],
    }

    # create the system bus object
    dbusSystemBus = dbus.SystemBus()

    # create the dbus settings object
    DbusSettings = SettingsDevice(
        bus=dbusSystemBus,
        supportedSettings=settingsList,
        timeout=30,
        eventCallback=None,
    )

    # create the dbus service
    DbusService = VeDbusService(
        "com.victronenergy.tailscale", bus=dbus.SystemBus(), register=False
    )

    # add paths
    DbusService.add_path("/ErrorMessage", "")
    DbusService.add_path("/GuiCommand", "", writeable=True)
    DbusService.add_path("/IPv4", "")
    DbusService.add_path("/IPv6", "")
    DbusService.add_path("/LoginLink", "")
    DbusService.add_path("/LoginLinkQrCode", "")
    DbusService.add_path("/ProductName", "Tailscale (remote VPN access)")
    DbusService.add_path("/State", STATE_INITIALIZING)

    # register VeDbusService after all paths where added
    DbusService.register()

    # set system name object
    systemnameObject = dbusSystemBus.get_object(
        "com.victronenergy.settings", "/Settings/SystemSetup/SystemName"
    )

    # call the main loop - every 1 second
    # this section of code loops until mainloop quits
    GLib.timeout_add(1000, mainLoop)
    mainloop = GLib.MainLoop()
    mainloop.run()

    logging.critical("tailscale-control exiting")


main()
