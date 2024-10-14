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
        exceptionType, exceptionObject, exceptionTraceback = sys.exc_info()
        file = exceptionTraceback.tb_frame.f_code.co_filename
        line = exceptionTraceback.tb_lineno
        logging.error("")
        logging.error(
            f"Exception occurred: {repr(exceptionObject)} of type {exceptionType} in {file} line #{line}"
        )
        logging.error("sendCommand() failed: " + " ".join(command))
        return None, None, None
    else:
        out, err = proc.communicate()
        stdout = out.decode().strip()
        stderr = err.decode().strip()
        return stdout, stderr, proc.returncode


def cleanupErrorMessage(errorMessage: str) -> str:
    """
    cleanup error message

    :param errorMessage: error message to cleanup
    :return: cleaned up error message
    """
    # remove specific strings
    errorMessage = errorMessage.replace(
        'timeout waiting for Tailscale service to enter a Running state; check health with "tailscale status"',
        "",
    )

    return errorMessage


def cleanupHostname(hostname: str) -> str:
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


def checkDeviceNetwork(device: str) -> str:
    """
    Check if a device is up and return the network

    :param dev: device to check
    :return: extracted network or empty string
    """
    # Check if the device is up
    stdout, stderr, exitCode = sendCommand([f"ip link show {device}"], shell=True)

    if exitCode == 0:
        if "state UP" in stdout:
            # get network
            stdout, stderr, exitCode = sendCommand(
                [f"ip route show dev {device}"], shell=True
            )

            if exitCode == 0:
                # extract network
                network = re.search(r"([0-9.]+/[0-9]{1,2})", stdout)

                if network is not None:
                    logging.info(f'Device "{device}" route found: {network.group(1)}')
                    return network.group(1)
                else:
                    logging.warning(
                        f'Device "{device}" could not extract network: {stdout}'
                    )
            else:
                logging.warning(f'Device "{device}" error: {stderr}')
        else:
            logging.info(f'Device "{device}" is DOWN')
    else:
        # device does not exist
        # logging.info(stderr)
        pass

    return ""


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
systemNameObject = None
systemNameCurrent = ""
systemNamePrevious = ""
autoUpdateDisabled = False


def mainLoop():
    """
    Runs every second and checks the status of the tailscale link and checks for GUI commands
    """
    global DbusSettings, DbusService
    global stateCurrent, statePrevious
    global systemNameCurrent, systemNamePrevious
    global autoUpdateDisabled

    backendRunning = None
    tailscaleEnabled = False

    loginInfo = ""

    # check if the system name object is set
    if systemNameObject is not None:
        # get the current system name
        systemNameCurrent = systemNameObject.GetValue()

    # check if the system name has changed
    if systemNameCurrent != systemNamePrevious:
        logging.info(
            f'System name has changed from "{systemNamePrevious}" to "{systemNameCurrent}"'
        )

        # check if the previous system name or the sytem hostname was set as the hostname
        # this is to make sure, that a custom set hostname is not overwritten
        if (
            cleanupHostname(systemNamePrevious) == DbusSettings["MachineName"]
            or gethostname() == DbusSettings["MachineName"]
        ):
            # update the hostname
            logging.info(
                f'Changing machine name from "{DbusSettings["MachineName"]}" to "{cleanupHostname(systemNameCurrent)}"'
            )
            DbusSettings["MachineName"] = cleanupHostname(systemNameCurrent)

        # set the current system name as the previous
        systemNamePrevious = systemNameCurrent

    # check if hostname is empty
    if DbusSettings["MachineName"] == "":
        # if there is a system name, set it as the hostname
        if systemNameCurrent != "":
            DbusSettings["MachineName"] = cleanupHostname(systemNameCurrent)
            logging.info(
                f'System name is "{systemNameCurrent}", using is as machine name "{DbusSettings["MachineName"]}"'
            )
        else:
            DbusSettings["MachineName"] = gethostname()
            logging.info(
                f'System name is empty, using system machine name "{DbusSettings["MachineName"]}"'
            )

    # check if backend is running
    stdout, stderr, exitCode = sendCommand(["svstat", "/service/tailscale"])
    if stdout is None:
        logging.warning("tailscale not in services")
        backendRunning = None
    elif stderr is None or "does not exist" in stderr:
        logging.warning("tailscale not in services")
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
        logging.info("starting tailscale")
        stdout, stderr, exitCode = sendCommand(["svc", "-u", "/service/tailscale"])

        if exitCode != 0:
            logging.error("starting tailscale failed " + str(exitCode))
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

        logging.info("stopping tailscale")
        stdout, stderr, exitCode = sendCommand(["svc", "-d", "/service/tailscale"])

        if exitCode != 0:
            logging.error("stopping tailscale failed " + str(exitCode))
            logging.error(stderr)

        backendRunning = False
    # *** this will be managed by the Venus OS plattform in future | end ***

    if backendRunning:
        # disable auto update once
        if not autoUpdateDisabled:
            # disable updates
            logging.info("disabling auto update")
            stdout, stderr, exitCode = sendCommand(
                ["/usr/bin/tailscale", "set", "--auto-update=false"]
            )

            if exitCode != 0:
                logging.error("disabling auto update failed " + str(exitCode))
                logging.error(stderr)

            autoUpdateDisabled = True

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

                        if hostname != DbusSettings["MachineName"]:
                            logging.info(
                                f'Machine name changed from "{DbusSettings["MachineName"]}" to'
                                + f' "{hostname}" from status message'
                            )
                            DbusSettings["MachineName"] = hostname
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

            if (
                stateCurrent == STATE_STOPPED
                or stateCurrent == STATE_LOGGED_OUT
                or stateCurrent == STATE_NO_STATE
            ) and statePrevious != STATE_WAIT_FOR_RESPONSE:
                # create command line arguments for tailscale up, this allows a dynamic configuration
                commandLineArgs = []

                # add timeout
                commandLineArgs.append("--timeout=0.5s")

                # set routes to advertise
                # https://tailscale.com/kb/1019/subnets

                # create a list of routes to advertise
                advertiseRoutes = []

                if DbusSettings["AccessLocalEthernet"] == 1:
                    # check if network is available and add to advertise routes
                    network = checkDeviceNetwork("eth0")

                    if network != "":
                        advertiseRoutes.append(network)

                if DbusSettings["AccessLocalWifi"] == 1:
                    # define possible devices
                    devices = ["wifi0", "wlan0", "ap0"]

                    for device in devices:
                        # check if network is available and add to advertise routes
                        network = checkDeviceNetwork(device)

                        if network != "":
                            advertiseRoutes.append(network)

                if DbusSettings["CustomNetworks"] != "":
                    # remove unallowed characters
                    DbusSettings["CustomNetworks"] = re.sub(
                        r"[^0-9./,]", "", DbusSettings["CustomNetworks"]
                    )
                    advertiseRoutes.extend(DbusSettings["CustomNetworks"].split(","))

                if len(advertiseRoutes) > 0:
                    # remove duplicates
                    advertiseRoutes = list(set(advertiseRoutes))

                    # add to command line arguments
                    commandLineArgs.append(
                        "--advertise-routes=" + ",".join(advertiseRoutes)
                    )

                # set hostname
                if DbusSettings["MachineName"] != "":
                    # cleanup hostname
                    DbusSettings["MachineName"] = cleanupHostname(
                        DbusSettings["MachineName"]
                    )

                    commandLineArgs.append("--hostname=" + DbusSettings["MachineName"])

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

                    commandLineArgs.append(
                        "--login-server=https://" + DbusSettings["CustomServerUrl"]
                    )

                # check if accept-dns is not set in the custom arguments
                # accept-dns is disabled by default to prevent writing to root fs since it's read-only
                if "--accept-dns" not in DbusSettings["CustomArguments"]:
                    commandLineArgs.append("--accept-dns=false")

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
                    len(advertiseRoutes) > 0
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
                    len(advertiseRoutes) == 0
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
                    DbusSettings["CustomArguments"] = re.sub(
                        r"[^a-zA-Z0-9-_=+:., ]", "", DbusSettings["CustomArguments"]
                    )

                    # split on one or multiple space
                    commandLineArgs.extend(
                        re.split(r"\s+", DbusSettings["CustomArguments"])
                    )

            if (
                stateCurrent == STATE_STOPPED
                and statePrevious != STATE_WAIT_FOR_RESPONSE
            ):
                # combine command line arguments
                commandLineArgs = [
                    "/usr/bin/tailscale",
                    "up",
                    "--reset",
                ] + commandLineArgs

                logging.info(f"executing {' '.join(commandLineArgs)}")
                stdout, stderr, exitCode = sendCommand(commandLineArgs)

                if exitCode != 0:
                    logging.error("tailscale up failed " + str(exitCode))
                    logging.error(stderr)
                    DbusService["/ErrorMessage"] = cleanupErrorMessage(stderr)
                else:
                    stateCurrent = STATE_WAIT_FOR_RESPONSE

            elif (
                stateCurrent == STATE_LOGGED_OUT
                and statePrevious != STATE_WAIT_FOR_RESPONSE
            ):
                # combine command line arguments
                commandLineArgs = [
                    "/usr/bin/tailscale",
                    "login",
                ] + commandLineArgs

                logging.info(f"executing {' '.join(commandLineArgs)}")
                stdout, stderr, exitCode = sendCommand(commandLineArgs)

                if exitCode != 0:
                    logging.error("tailscale login failed " + str(exitCode))
                    logging.error(stderr)
                    DbusService["/ErrorMessage"] = cleanupErrorMessage(stderr)
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

    statePrevious = stateCurrent

    return True


def main():
    global DbusSettings, DbusService
    global systemNameObject

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
        "AccessLocalEthernet": [
            "/Settings/Services/Tailscale/AccessLocalEthernet",
            0,
            0,
            1,
        ],
        "AccessLocalWifi": ["/Settings/Services/Tailscale/AccessLocalWifi", 0, 0, 1],
        "CustomArguments": ["/Settings/Services/Tailscale/CustomArguments", "", 0, 0],
        "CustomNetworks": ["/Settings/Services/Tailscale/CustomNetworks", "", 0, 0],
        "CustomServerUrl": ["/Settings/Services/Tailscale/CustomServerUrl", "", 0, 0],
        "Enabled": ["/Settings/Services/Tailscale/Enabled", 0, 0, 1],
        "MachineName": ["/Settings/Services/Tailscale/MachineName", "", 0, 0],
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
    systemNameObject = dbusSystemBus.get_object(
        "com.victronenergy.settings", "/Settings/SystemSetup/SystemName"
    )

    # call the main loop - every 1 second
    # this section of code loops until mainloop quits
    GLib.timeout_add(1000, mainLoop)
    mainloop = GLib.MainLoop()
    mainloop.run()

    logging.critical("tailscale-control exiting")


main()
