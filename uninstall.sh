#!/bin/bash

# uninstallation without SetupHelper

# stop services
echo ""
if [ -d "/service/tailscale-backend" ]; then
    echo "Stop and remove service tailscale-backend..."
    svc -d /service/tailscale-backend
    rm -rf /service/tailscale-backend
    rm -rf /opt/victronenergy/service/tailscale-backend
fi
if [ -d "/service/tailscale-control" ]; then
    echo "Stop and remove service tailscale-control..."
    svc -d /service/tailscale-control
    rm -rf /service/tailscale-control
    rm -rf /opt/victronenergy/service/tailscale-control
fi

if [ -d "/service/TailscaleGX-backend" ]; then
    echo "Stop and remove service TailscaleGX-backend..."
    svc -d /service/TailscaleGX-backend
    rm -rf /service/TailscaleGX-backend
    rm -rf /opt/victronenergy/service/TailscaleGX-backend
fi
if [ -d "/service/TailscaleGX-control" ]; then
    echo "Stop and remove service TailscaleGX-control..."
    svc -d /service/TailscaleGX-control
    rm -rf /service/TailscaleGX-control
    rm -rf /opt/victronenergy/service/TailscaleGX-backend
fi
echo ""

# cleanup script and config folders
if [ -d "/opt/victronenergy/tailscale" ]; then
    echo "Remove \"/opt/victronenergy/tailscale\" folder..."
    rm -rf /opt/victronenergy/tailscale
fi

if [ -d "/data/conf/tailscale" ]; then
    echo "Remove \"/data/conf/tailscale\" folder..."
    rm -rf /data/conf/tailscale
fi
echo ""

# cleanup binaries
if [ -L "/usr/bin/tailscale" ]; then
    echo "Remove \"/usr/bin/tailscale\" symbolic link..."
    rm /usr/bin/tailscale
fi
if [ -L "/usr/bin/tailscaled" ]; then
    echo "Remove \"/usr/bin/tailscaled\" symbolic link..."
    rm /usr/bin/tailscaled
fi
if [ -f "/usr/bin/tailscale.combined" ]; then
    echo "Remove \"/usr/bin/tailscale.combined\" file..."
    rm /usr/bin/tailscale.combined
fi
echo ""

# cleanup other created directories and files
if [ -d "/var/lib/tailscale" ]; then
    echo "Remove \"/var/lib/tailscale\" folder..."
    rm -rf /var/lib/tailscale
fi

if [ -d "/run/tailscale" ]; then
    echo "Remove \"/run/tailscale\" folder..."
    rm -rf /run/tailscale
fi

if [ -d "/data/log/tailscale-backend" ]; then
    echo "Remove \"/data/log/tailscale-backend\" folder..."
    rm -rf /data/log/tailscale-backend
fi

if [ -d "/data/log/tailscale-control" ]; then
    echo "Remove \"/data/log/tailscale-control\" folder..."
    rm -rf /data/log/tailscale-control
fi


# restore original files
if [ -f "/opt/victronenergy/venus-platform/venus-platform.bak" ]; then
    echo "Restore venus-platform..."
    rm /opt/victronenergy/venus-platform/venus-platform
    mv /opt/victronenergy/venus-platform/venus-platform.bak /opt/victronenergy/venus-platform/venus-platform
fi
if [ -f "/opt/victronenergy/vrmlogger/datalist.py.bak" ]; then
    echo "Restore datalist.py..."
    rm /opt/victronenergy/vrmlogger/datalist.py
    mv /opt/victronenergy/vrmlogger/datalist.py.bak /opt/victronenergy/vrmlogger/datalist.py
fi
echo ""

# remove dbus paths
if [ -f /etc/venus/settings.d/tailscale ]; then
    echo "Remove dbus settings file..."
    rm /etc/venus/settings.d/tailscale
fi

echo "Remove dbus paths..."
dbus -y com.victronenergy.settings /Settings RemoveSettings '%[ \
    "Services/Tailscale/AccessLocalEthernet", \
    "Services/Tailscale/AccessLocalWifi", \
    "Services/Tailscale/AdvertiseRoutes", \
    "Services/Tailscale/CustomArguments", \
    "Services/Tailscale/CustomNetworks", \
    "Services/Tailscale/CustomServerUrl", \
    "Services/Tailscale/Enabled", \
    "Services/Tailscale/Hostname", \
    "Services/Tailscale/Machinename", \
    "Services/Tailscale/MachineName" \
]' > /dev/null
echo ""


# check if file exists, if yes uninstall GUIv1 mod
if [ -f "/opt/victronenergy/gui/qml/PageSettingsServices.qml.orig" ]; then
    echo "Uninstall GUIv1 mod..."

    rm /opt/victronenergy/gui/qml/PageSettingsServices.qml
    rm /opt/victronenergy/gui/qml/PageSettingsTailscale.qml
    mv /opt/victronenergy/gui/qml/PageSettingsServices.qml.orig /opt/victronenergy/gui/qml/PageSettingsServices.qml

    # check if /service/gui exists
    if [ -d "/service/gui" ]; then
        # nanopi, raspberrypi
        servicePath="/service/gui"
    else
        # cerbo gx
        servicePath="/service/start-gui"
    fi

    # stop gui
    svc -d $servicePath
    # sleep 1 sec
    sleep 1
    # start gui
    svc -u $servicePath
fi
