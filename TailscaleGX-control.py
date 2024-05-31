#!/usr/bin/env python
#
# 	TailscaleGX-control.py
# 	Kevin Windrem
#
# This program controls remote access to a Victron Energy
# It is based on tailscale which is based on WireGauard.
#
# This runs as a daemon tools service at /service/TailscaleGx-control
#
# ssh and html (others TBD) connections can be made via
# 	the IP address(s) supplied by the tailscale broker.
#
# Persistent storage for TailscaleGX is stored in dbus Settings:
#
# 	com.victronenergy.Settings parameters:
# 		/Settings/TailscaleGX/Enabled
# 			controls wheter remote access is enabled or disabled
#
# Operational parameters are provided by:
# 	com.victronenergy.tailscaleGX
# 		/State
# 		/IPv4		IP v4 remote access IP address
# 		/IPv6		as above for IP v6
# 		/Hostname	as above but as a host name
# 		/LoginLink	temorary URL for connecting to tailscale
# 						for initiating a connection
# 		/GuiCommand	GUI writes string here to request an action:
# 			logout
#
# together, the above settings and dbus service provide the condiut to the GUI
#
# On startup the dbus settings and service are created
# 	control then passes to mainLoop which gets scheduled once per second:
# 		starts / stops the TailscaleGX-backend based on /Enabled
# 		scans status from tailscale link
# 		TBD
# 		TBD
# 		TBD
# 		provides status and prompting to the GUI during this process
# 			in the end providing the user the IP address they must use
# 			to connect to the GX device.
#

# import platform
# import argparse
import logging
import sys
import subprocess

# import threading
import os

# import shutil
import dbus  # type: ignore

# import time
import re

PythonVersion = sys.version_info


# import queue
from gi.repository import GLib  # type: ignore # noqa: E402

# use an established Victron service to maintain compatiblity
sys.path.insert(
    1, os.path.join("/opt/victronenergy/dbus-systemcalc-py", "ext", "velib_python")
)
from vedbus import VeDbusService  # noqa: E402
from settingsdevice import SettingsDevice  # noqa: E402


# sends a unix command
# 	eg sendCommand ( [ 'svc', '-u' , serviceName ] )
#
# stdout, stderr and the exit code are returned as a list to the caller


def sendCommand(command: list = None, shell: bool = False):
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


tsControlCmd = "/data/venus-os_TailscaleGX/tailscale"


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
global systemnameObj
global systemname
global hostname
global ipV4

previousState = UNKNOWN_STATE
state = UNKNOWN_STATE
systemnameObj = None
systemname = None
hostname = None
ipV4 = ""
ipForewardEnabled = None


def mainLoop():
    global DbusSettings
    global DbusService
    global previousState
    global state
    global systemname
    global hostname
    global ipV4
    global ipForewardEnabled

    # startTime = time.time()

    backendRunning = None
    tailscaleEnabled = False
    thisHostname = None

    loginInfo = ""

    if systemnameObj is None:
        systemname = None
        hostname = None
    else:
        name = systemnameObj.GetValue()
        if name != systemname:
            systemname = name
            if name is None or name == "":
                hostname = None
                logging.warning("no system name so no host name")
            else:
                # allow only letters, numbers and '-'
                name = re.sub("[^a-zA-Z0-9-]", "", name)
                name = name.replace("\\", "-")
                # host name must start with a letter or number
                name = name.strip(" -").lower()
                hostname = name
                logging.info("system name changed to " + systemname)
                logging.info(
                    "new host name " + hostname + " will be used on NEXT login"
                )

    # see if backend is running
    stdout, stderr, exitCode = sendCommand(["svstat", "/service/TailscaleGX-backend"])
    if stdout is None:
        logging.warning("TailscaleGX-backend not in services")
        backendRunning = None
    elif stderr is None or "does not exist" in stderr:
        logging.warning("TailscaleGX-backend not in services")
        backendRunning = None
    elif stdout is not None and ": up" in stdout:
        backendRunning = True
    else:
        backendRunning = False

    tailscaleEnabled = DbusSettings["Enabled"] == 1

    # start backend
    if tailscaleEnabled and backendRunning is False:
        logging.info("starting TailscaleGX-backend")
        _, _, exitCode = sendCommand(["svc", "-u", "/service/TailscaleGX-backend"])
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

        logging.info("stopping TailscaleGX-backend")
        _, _, exitCode = sendCommand(["svc", "-d", "/service/TailscaleGX-backend"])
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
            if ipV4 != "":
                for line in stdout.splitlines():
                    if ipV4 in line:
                        thisHostname = line.split()[1]

        # don't update state if we don't recognize the response
        else:
            pass

        # create command line arguments for tailscale up, this allows a dynamic configuration
        command_line_args = []

        if DbusSettings["AcceptRoutes"] == 1:
            command_line_args.append("--accept-routes")

        if DbusSettings["AdvertiseExitNode"] == 1:
            command_line_args.append("--advertise-exit-node")

        # https://tailscale.com/kb/1019/subnets
        if DbusSettings["AdvertiseRoutes"] != "":
            command_line_args.append(
                "--advertise-routes=" + DbusSettings["AdvertiseRoutes"]
            )

        # set ip forewarding once
        if DbusSettings["AdvertiseRoutes"] != "" and ipForewardEnabled is not True:
            # execute command
            # add entry to /etc/sysctl.conf, if it does not exist
            _, stderr, exitCode = sendCommand(
                [
                    'grep -qxF "net.ipv4.ip_forward = 1" /etc/sysctl.conf'
                    + "||"
                    + 'echo "net.ipv4.ip_forward = 1" >> /etc/sysctl.conf',
                ],
                shell=True,
            )
            result = exitCode == 0
            if exitCode != 0:
                logging.warning(f"#1 _: {_} - stderr: {stderr} - exitCode: {exitCode}")

            # execute command
            # add entry to /etc/sysctl.conf, if it does not exist
            _, stderr, exitCode = sendCommand(
                [
                    'grep -qxF "net.ipv6.conf.all.forwarding = 1" /etc/sysctl.conf'
                    + "||"
                    + 'echo "net.ipv6.conf.all.forwarding = 1" >> /etc/sysctl.conf',
                ],
                shell=True,
            )
            result = result and exitCode == 0
            if exitCode != 0:
                logging.warning(f"#2 _: {_} - stderr: {stderr} - exitCode: {exitCode}")

            # execute command
            # load the new configuration
            _, stderr, exitCode = sendCommand(
                ["sysctl -p /etc/sysctl.conf"], shell=True
            )
            result = result and exitCode == 0
            if exitCode != 0:
                logging.warning(f"#3 _: {_} - stderr: {stderr} - exitCode: {exitCode}")

            if result:
                logging.info("ip forewarding enabled")
                ipForewardEnabled = True

        # remove ip forewarding once
        elif DbusSettings["AdvertiseRoutes"] == "" and ipForewardEnabled is not False:

            # execute command
            # remove entry from /etc/sysctl.conf, if it exists
            _, stderr, exitCode = sendCommand(
                [
                    'sed -i "/net.ipv4.ip_forward = 1/d" /etc/sysctl.conf',
                ],
                shell=True,
            )
            result = exitCode == 0
            if exitCode != 0:
                logging.warning(f"#4 _: {_} - stderr: {stderr} - exitCode: {exitCode}")

            # execute command
            # remove entry from /etc/sysctl.conf, if it exists
            _, stderr, exitCode = sendCommand(
                [
                    'sed -i "/net.ipv6.conf.all.forwarding = 1/d" /etc/sysctl.conf',
                ],
                shell=True,
            )
            result = result and exitCode == 0
            if exitCode != 0:
                logging.warning(f"#5 _: {_} - stderr: {stderr} - exitCode: {exitCode}")

            # execute command
            # load the new configuration
            _, stderr, exitCode = sendCommand(
                ["sysctl -p /etc/sysctl.conf"], shell=True
            )
            result = result and exitCode == 0
            if exitCode != 0:
                logging.warning(f"#6 _: {_} - stderr: {stderr} - exitCode: {exitCode}")

            if result:
                logging.info("ip forewarding disabled")
                ipForewardEnabled = False

        if DbusSettings["ExitNode"] != "":
            command_line_args.append(
                "--exit-node=" + DbusSettings["ExitNode"],
                "--exit-node-allow-lan-access",
            )

        # if DbusSettings["Hostname"] != "":
        #     systemname = DbusSettings["Hostname"]
        #     hostname = DbusSettings["Hostname"]

        # if hostname is not None and hostname != "":
        #     command_line_args.append("--hostname=" + hostname)

        if DbusSettings["CustomServerUrl"] != "":
            command_line_args.append(
                "--login-server=" + DbusSettings["CustomServerUrl"]
            )

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

                if systemname is None or systemname == "":
                    logging.info("starting tailscale without host name")
                else:
                    logging.info("starting tailscale with host name:" + hostname)

                # combine command line arguments
                command_line_args = [
                    tsControlCmd,
                    "up",
                    "--reset",
                    # "--timeout=0.1s",
                    "--timeout=5s",
                ] + command_line_args

                # execute command
                _, stderr, exitCode = sendCommand(command_line_args)

                if exitCode != 0:
                    logging.error("tailscale up failed " + str(exitCode))
                    logging.error(stderr)
                    DbusService["/ErrorMessage"] = stderr
                else:
                    logging.info(f"executed: {' '.join(command_line_args)}")
                    DbusService["/ErrorMessage"] = ""
                    state = WAIT_FOR_RESPONSE

            elif state == LOGGED_OUT and previousState != WAIT_FOR_RESPONSE:

                if systemname is None or systemname == "":
                    logging.info("logging in to tailscale without host name")
                    # execute command
                    _, stderr, exitCode = sendCommand(
                        [tsControlCmd, "login", "--timeout=0.1s"],
                    )
                else:
                    logging.info("logging in to tailscale with host name:" + hostname)
                    # execute command
                    _, stderr, exitCode = sendCommand(
                        [
                            tsControlCmd,
                            "login",
                            "--timeout=0.1s",
                            "--hostname=" + hostname,
                        ]
                    )

                if exitCode != 0:
                    logging.error("tailscale login failed " + str(exitCode))
                    logging.error(stderr)
                    DbusService["/ErrorMessage"] = stderr
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
            DbusSettings["Hostname"] = thisHostname
        else:
            DbusService["/IPv4"] = ""
            DbusService["/IPv6"] = ""
            DbusSettings["Hostname"] = ""  # don't clear hostname

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
    global systemnameObj

    # fetch installed version
    installedVersionFile = "/etc/venus/installedVersion-TailscaleGX-control"
    try:
        versionFile = open(installedVersionFile, "r")
    except Exception:
        installedVersion = ""
    else:
        installedVersion = versionFile.readline().strip()
        versionFile.close()
        # if file is empty, an unknown version is installed
        if installedVersion == "":
            installedVersion = "unknown"

    # set logging level to include info level entries
    logging.basicConfig(format="%(levelname)s:%(message)s", level=logging.INFO)

    logging.info("")
    logging.info(">>>> TailscaleGX-control" + installedVersion + " starting")

    # Have a mainloop, so we can send/receive asynchronous calls to and from dbus
    from dbus.mainloop.glib import DBusGMainLoop  # type: ignore

    DBusGMainLoop(set_as_default=True)
    global PythonVersion
    if PythonVersion < (3, 0):
        GLib.threads_init()

    theBus = dbus.SystemBus()
    dbusSettingsPath = "com.victronenergy.settings"

    settingsList = {
        "Enabled": ["/Settings/Services/Tailscale/Enabled", 0, 0, 1],
        "AcceptRoutes": ["/Settings/Services/Tailscale/AcceptRoutes", 0, 0, 1],
        "AdvertiseExitNode": [
            "/Settings/Services/Tailscale/AdvertiseExitNode",
            0,
            0,
            1,
        ],
        "AdvertiseRoutes": ["/Settings/Services/Tailscale/AdvertiseRoutes", "", 0, 255],
        "ExitNode": ["/Settings/Services/Tailscale/ExitNode", "", 0, 255],
        "Hostname": ["/Settings/Services/Tailscale/Hostname", "", 0, 255],
        "CustomServerUrl": ["/Settings/Services/Tailscale/CustomServerUrl", "", 0, 255],
        "CustomArguments": ["/Settings/Services/Tailscale/CustomArguments", "", 0, 255],
    }
    DbusSettings = SettingsDevice(
        bus=theBus, supportedSettings=settingsList, timeout=30, eventCallback=None
    )

    # TODO: Host name not read from settings on startup

    DbusService = VeDbusService("com.victronenergy.tailscaleGX", bus=dbus.SystemBus())
    DbusService.add_mandatory_paths(
        processname="TailscaleGX-control",
        processversion=1.0,
        connection="none",
        deviceinstance=0,
        productid=1,
        productname="TailscaleGX-control",
        firmwareversion=1,
        hardwareversion=0,
        connected=1,
    )

    DbusService.add_path("/ErrorMessage", "")
    DbusService.add_path("/State", "")
    DbusService.add_path("/IPv4", "")
    DbusService.add_path("/IPv6", "")
    DbusService.add_path("/LoginLink", "")

    DbusService.add_path("/GuiCommand", "", writeable=True)

    systemnameObj = theBus.get_object(
        dbusSettingsPath, "/Settings/SystemSetup/SystemName"
    )

    # call the main loop - every 1 second
    # this section of code loops until mainloop quits
    GLib.timeout_add(1000, mainLoop)
    mainloop = GLib.MainLoop()
    mainloop.run()

    logging.critical("TailscaleGX-control exiting")


main()
