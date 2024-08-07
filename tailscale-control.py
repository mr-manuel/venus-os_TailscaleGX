#!/usr/bin/env python
#
# On startup the dbus settings and service are created
# 	tailscale-control then passes to mainLoop which gets scheduled once per second:
# 		starts / stops the tailscale-backend based on com.victronenergy.settings/Settings/Services/Tailscale/Enabled
# 		scans status from tailscale link
# 		provides status and prompting to the GUI during this process
# 			in the end providing the user the IP address they must use
# 			to connect to the GX device.
#

from gi.repository import GLib
import dbus
import logging
import sys
import os
import subprocess
import re
from socket import gethostname

# Victron packages
sys.path.insert(1, os.path.join(os.path.dirname(__file__), "./ext/velib_python"))
from vedbus import VeDbusService  # noqa: E402
from settingsdevice import SettingsDevice  # noqa: E402


def sendCommand(command: list = None, shell: bool = False):
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


def cleanup_whitespace(text: str) -> str:
    """
    cleanup whitespace in a string

    :param text: string to cleanup
    :return: cleaned up string
    """
    # Replace multiple spaces with a single space
    text = re.sub(r"\s+", " ", text)
    # Replace multiple new lines with a single new line
    text = re.sub(r"\n+", "\n", text)
    return text.strip()


def cleanup_hostname(hostname: str) -> str:
    """
    cleanup hostname

    :param hostname: hostname to cleanup
    :return: cleaned up hostname
    """
    # replace some characters
    hostname = hostname.replace("\\", "-")

    # remove any character that is not a letter, digit, or hyphen
    hostname = re.sub("[^a-zA-Z0-9-]", "", hostname)

    # remove leading and trailing hyphens
    hostname = hostname.strip("-")

    # convert to lowercase
    hostname = hostname.lower()
    return hostname


tsControlCmd = "/usr/bin/tailscale"


# static variables for main and mainLoop
DbusSettings = None
DbusService = None


UNKNOWN_STATE = 0
BACKEND_STARTING = 1
NOT_RUNNING = 2
STOPPED = 3
LOGGED_OUT = 4
WAIT_FOR_RESPONSE = 5
CONNECT_WAIT = 6
CONNECTED = 100

global previousState
global state
global systemnameObject
global systemnameCurrent
global systemnamePrevious
global ipV4

previousState = UNKNOWN_STATE
state = UNKNOWN_STATE
systemnameObject = None
systemnameCurrent = ""
systemnamePrevious = ""
ipV4 = ""
ipForewardEnabled = None


def mainLoop():
    global DbusSettings
    global DbusService
    global previousState
    global state
    global systemnameCurrent
    global systemnamePrevious
    global ipV4
    global ipForewardEnabled

    # startTime = time.time()

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

        # check if  the previous system name or the sytem hostname was set as the hostname
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

    # see if backend is running
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

    # start backend
    if tailscaleEnabled and backendRunning is False:
        logging.info("starting tailscale-backend")
        _, _, exitCode = sendCommand(["svc", "-u", "/service/tailscale-backend"])
        if exitCode != 0:
            logging.error("start TailscaleGX failed " + str(exitCode))
        state = BACKEND_STARTING
    # stop backend
    elif not tailscaleEnabled and backendRunning is True:

        # execute tailscale down before stopping backend
        # else config changes won't be applied
        # execute command
        _, stderr, exitCode = sendCommand([tsControlCmd, "down"])

        if exitCode != 0:
            logging.error("tailscale down failed " + str(exitCode))
            logging.error(stderr)
        else:
            logging.info(f"executed: {tsControlCmd} down")

        logging.info("stopping tailscale-backend")
        _, _, exitCode = sendCommand(["svc", "-d", "/service/tailscale-backend"])
        if exitCode != 0:
            logging.error("stop TailscaleGX failed " + str(exitCode))
        backendRunning = False

    if backendRunning:

        # check for GUI commands and act on them
        guiCommand = DbusService["/GuiCommand"]
        if guiCommand != "":
            # acknowledge receipt of command so another can be sent
            DbusService["/GuiCommand"] = ""
            if guiCommand == "logout":
                logging.info("logout command received")
                # logout takes time and can't specify a timeout so provide feedback first
                DbusService["/State"] = WAIT_FOR_RESPONSE
                _, stderr, exitCode = sendCommand([tsControlCmd, "logout"])
                if exitCode != 0:
                    logging.error("tailscale logout failed " + str(exitCode))
                    logging.error(stderr)
                else:
                    state = WAIT_FOR_RESPONSE
            else:
                logging.warning("invalid command received " + guiCommand)

        # get current status from tailscale and update state
        stdout, stderr, exitCode = sendCommand([tsControlCmd, "status"])
        # don't update state if we don't get a response
        if stdout is None or stderr is None:
            pass
        elif "Failed to connect" in stderr:
            state = NOT_RUNNING
        elif "Tailscale is stopped" in stdout:
            state = STOPPED
        elif "Log in at" in stdout:
            state = CONNECT_WAIT
            lines = stdout.splitlines()
            loginInfo = lines[1].replace("Log in at: ", "")
        elif "Logged out" in stdout:
            # can get back to this condition while loggin in
            # so wait for another condition to update state
            if previousState != WAIT_FOR_RESPONSE:
                state = LOGGED_OUT
        elif exitCode == 0:
            state = CONNECTED
            # extract this host's name from status message
            # this allows to show the hostname, if it was changed in the Tailscale admin panel
            if ipV4 != "":
                for line in stdout.splitlines():
                    if ipV4 in line:
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

        # create command line arguments for tailscale up, this allows a dynamic configuration
        command_line_args = []

        # set routes to advertise
        # https://tailscale.com/kb/1019/subnets
        if DbusSettings["AdvertiseRoutes"] != "":
            command_line_args.append(
                "--advertise-routes="
                + re.sub(
                    r"[^0-9./,]", "", DbusSettings["AdvertiseRoutes"]
                )  # cleanup string and maintain only allowed characters
            )

        # set ip forewarding once
        if DbusSettings["AdvertiseRoutes"] != "" and ipForewardEnabled is not True:
            # execute command
            _, stderr, exitCode = sendCommand(
                [
                    "sysctl net.ipv4.ip_forward=1",
                    "&&",
                    "sysctl net.ipv6.conf.all.forwarding=1",
                ],
                shell=True,
            )
            result = exitCode == 0
            if exitCode != 0:
                logging.warning(f"#1 _: {_} - stderr: {stderr} - exitCode: {exitCode}")

            if result:
                logging.info("ip forewarding enabled")
                ipForewardEnabled = True

        # remove ip forewarding once
        elif DbusSettings["AdvertiseRoutes"] == "" and ipForewardEnabled is not False:
            # execute command
            _, stderr, exitCode = sendCommand(
                [
                    "sysctl net.ipv4.ip_forward=0",
                    "&&",
                    "sysctl net.ipv6.conf.all.forwarding=0",
                ],
                shell=True,
            )
            result = result and exitCode == 0
            if exitCode != 0:
                logging.warning(f"#6 _: {_} - stderr: {stderr} - exitCode: {exitCode}")

            if result:
                logging.info("ip forewarding disabled")
                ipForewardEnabled = False

        # set hostname
        if DbusSettings["Hostname"] != "":
            command_line_args.append("--hostname=" + DbusSettings["Hostname"])

        # set custom server url, for example to use headscale
        if DbusSettings["CustomServerUrl"] != "":
            command_line_args.append(
                "--login-server=" + DbusSettings["CustomServerUrl"]
            )

        # add custom arguments
        if DbusSettings["CustomArguments"] != "":
            command_line_args.append(DbusSettings["CustomArguments"])

        # make changes necessary to bring connection up
        # 	up will fully connect if login had succeeded
        # 	or ask for login if not
        # 	next get syatus pass will indicate that
        # call is made with a short timeout so we can monitor status
        # 	but need to defer future tailscale commands until
        # 	tailscale has processed the first one
        # 	ALMOST any state change will signal the wait is over
        # 	(status not included)
        if state != previousState:

            if state == STOPPED and previousState != WAIT_FOR_RESPONSE:

                # combine command line arguments
                command_line_args = [
                    tsControlCmd,
                    "up",
                    "--reset",
                    "--accept-dns=false",  # disable DNS and prevent writing to root fs since it's read-only
                    "--timeout=0.3s",
                ] + command_line_args

                logging.info(f"command line args: {' '.join(command_line_args)}")

                # execute command
                _, stderr, exitCode = sendCommand(command_line_args)

                if exitCode != 0:
                    logging.error("tailscale up failed " + str(exitCode))
                    logging.error(stderr)
                    DbusService["/ErrorMessage"] = cleanup_whitespace(stderr)
                else:
                    logging.info(f"executed: {' '.join(command_line_args)}")
                    DbusService["/ErrorMessage"] = ""
                    state = WAIT_FOR_RESPONSE

            elif state == LOGGED_OUT and previousState != WAIT_FOR_RESPONSE:

                if DbusSettings["Hostname"] == "":
                    logging.info("logging in to tailscale without host name")
                    # execute command
                    _, stderr, exitCode = sendCommand(
                        [tsControlCmd, "login", "--timeout=0.3s"],
                    )
                else:
                    logging.info(
                        "logging in to tailscale with host name:"
                        + DbusSettings["Hostname"]
                    )
                    # execute command
                    _, stderr, exitCode = sendCommand(
                        [
                            tsControlCmd,
                            "login",
                            "--timeout=0.3s",
                            "--hostname=" + DbusSettings["Hostname"],
                        ]
                    )

                if exitCode != 0:
                    logging.error("tailscale login failed " + str(exitCode))
                    logging.error(stderr)
                    DbusService["/ErrorMessage"] = cleanup_whitespace(stderr)
                else:
                    DbusService["/ErrorMessage"] = ""
                    state = WAIT_FOR_RESPONSE

        # show IP addresses only if connected
        if state == CONNECTED:
            if previousState != CONNECTED:
                logging.info("connection successful")

            stdout, stderr, exitCode = sendCommand([tsControlCmd, "ip"])

            if exitCode != 0:
                logging.error("tailscale ip failed " + str(exitCode))
                logging.error(stderr)

            if stdout is not None and stdout != "":
                ipV4, ipV6 = stdout.splitlines()
                DbusService["/IPv4"] = ipV4
                DbusService["/IPv6"] = ipV6
            else:
                DbusService["/IPv4"] = "?"
                DbusService["/IPv6"] = "?"
        else:
            DbusService["/IPv4"] = ""
            DbusService["/IPv6"] = ""

    else:
        state = NOT_RUNNING

    # update dbus values regardless of state of the link
    DbusService["/State"] = state
    DbusService["/LoginLink"] = loginInfo

    previousState = state
    # TODO: enable for testing
    # endTime = time.time()
    # print ("main loop time %3.1f mS" % ( (endTime - startTime) * 1000 ))
    return True


def main():
    global DbusSettings
    global DbusService
    global systemnameObject

    # get installed binary version
    try:
        # get the version by asking the tailscale binary
        stdout, stderr, exitCode = sendCommand([tsControlCmd, "version"])

        if exitCode != 0:
            raise Exception("tailscale version command failed")

        installedVersion = stdout.splitlines()[0]

    except Exception:
        installedVersion = "unknown"

    # set logging level to include info level entries
    logging.basicConfig(level=logging.INFO)

    logging.info(f"Tailscale binary version {installedVersion}")

    # Have a mainloop, so we can send/receive asynchronous calls to and from dbus
    from dbus.mainloop.glib import DBusGMainLoop

    DBusGMainLoop(set_as_default=True)

    dbusSystemBus = dbus.SystemBus()
    dbusSettingsPath = "com.victronenergy.settings"

    settingsList = {
        "Enabled": ["/Settings/Services/Tailscale/Enabled", 0, 0, 1],
        "AdvertiseRoutes": ["/Settings/Services/Tailscale/AdvertiseRoutes", "", 0, 255],
        "Hostname": ["/Settings/Services/Tailscale/Hostname", "", 0, 255],
        "CustomServerUrl": ["/Settings/Services/Tailscale/CustomServerUrl", "", 0, 255],
        "CustomArguments": ["/Settings/Services/Tailscale/CustomArguments", "", 0, 255],
    }
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

    # add mandatory paths
    DbusService.add_mandatory_paths(
        processname="Tailscale (remote VPN access)",
        processversion=1.0,
        connection="none",
        deviceinstance=0,
        productid=1,
        productname="Tailscale (remote VPN access)",
        firmwareversion=1,
        hardwareversion=0,
        connected=1,
    )

    # add custom paths
    DbusService.add_path("/ErrorMessage", "")
    DbusService.add_path("/State", "")
    DbusService.add_path("/IPv4", "")
    DbusService.add_path("/IPv6", "")
    DbusService.add_path("/LoginLink", "")

    DbusService.add_path("/GuiCommand", "", writeable=True)

    # register VeDbusService after all paths where added
    DbusService.register()

    # set system name object
    systemnameObject = dbusSystemBus.get_object(
        dbusSettingsPath, "/Settings/SystemSetup/SystemName"
    )

    # call the main loop - every 1 second
    # this section of code loops until mainloop quits
    GLib.timeout_add(1000, mainLoop)
    mainloop = GLib.MainLoop()
    mainloop.run()

    logging.critical("tailscale-control exiting")


main()
