#!/bin/bash

# installation without SetupHelper

# make files executable
echo ""
echo "Make files executable..."
chmod +x /data/venus-os_TailscaleGX/*.sh
chmod +x /data/venus-os_TailscaleGX/*.py
chmod +x /data/venus-os_TailscaleGX/tailscale*
chmod +x /data/venus-os_TailscaleGX/services/*/run
chmod +x /data/venus-os_TailscaleGX/services/*/log/run
chmod +x /data/venus-os_TailscaleGX/FileSets/venus-platform


# make system writable
echo "Make filesystem writable..."
bash /opt/victronenergy/swupdate-scripts/remount-rw.sh
echo ""


# try to expand system partition
echo "Try to expand system partition..."
bash /opt/victronenergy/swupdate-scripts/resize2fs.sh


# cleanup old script folder
if [ -d "/opt/victronenergy/tailscale" ]; then
    echo "Remove old \"/opt/victronenergy/tailscale\" folder..."
    rm -rf /opt/victronenergy/tailscale
fi


# cleanup old dbus entries
echo "Remove old dbus entries..."
dbus -y com.victronenergy.settings /Settings RemoveSettings '%[ \
    "Services/Tailscale/AcceptRoutes", \
    "Services/Tailscale/AdvertiseExitNode", \
    "Services/Tailscale/AdvertiseRoutes", \
    "Services/Tailscale/ExitNode", \
    "Services/Tailscale/Hostname", \
    "Services/Tailscale/Maschinename" \
]' > /dev/null
echo ""


# cleanup old service copies
if [ -L "/service/tailscale-backend" ]; then
    echo "Remove old \"/service/tailscale-backend\" folder..."
    svc -d /service/tailscale-backend
    rm -rf /service/tailscale-backend
fi
if [ -L "/service/tailscale-control" ]; then
    echo "Remove old \"/service/tailscale-control\" folder..."
    svc -d /service/tailscale-control
    rm -rf /service/tailscale-control
fi
if [ -d "/opt/victronenergy/service/tailscale-backend" ]; then
    echo "Remove old \"/opt/victronenergy/service/tailscale-backend\" folder..."
    rm -rf /opt/victronenergy/service/tailscale-backend
fi
if [ -d "/opt/victronenergy/service/tailscale-control" ]; then
    echo "Remove old \"/opt/victronenergy/service/tailscale-control\" folder..."
    rm -rf /opt/victronenergy/service/tailscale-control
fi

# cleanup old service copies with old name | start
if [ -L "/service/TailscaleGX-backend" ]; then
    echo "Remove old \"/service/TailscaleGX-backend\" folder..."
    svc -d /service/TailscaleGX-backend
    rm -rf /service/TailscaleGX-backend
fi
if [ -L "/service/TailscaleGX-control" ]; then
    echo "Remove old \"/service/TailscaleGX-control\" folder..."
    svc -d /service/TailscaleGX-control
    rm -rf /service/TailscaleGX-control
fi
if [ -d "/data/log/TailscaleGX-backend" ]; then
    echo "Remove old \"/data/log/TailscaleGX-backend\" folder..."
    rm -rf /data/log/TailscaleGX-backend
fi
if [ -d "/data/log/TailscaleGX-control" ]; then
    echo "Remove old \"/data/log/TailscaleGX-control\" folder..."
    rm -rf /data/log/TailscaleGX-control
fi
if [ -L "/opt/victronenergy/service/TailscaleGX-backend" ]; then
    echo "Remove old \"/opt/victronenergy/service/TailscaleGX-backend\" symbolic link..."
    rm /opt/victronenergy/service/TailscaleGX-backend
fi
if [ -L "/opt/victronenergy/service/TailscaleGX-control" ]; then
    echo "Remove old \"/opt/victronenergy/service/TailscaleGX-control\" symbolic link..."
    rm /opt/victronenergy/service/TailscaleGX-control
fi
echo ""
# cleanup old service copies with old name | end

# copy files as it will be when integrated into Venus OS | start
echo "Copy files and creating symlinks..."
cp -f /data/venus-os_TailscaleGX/tailscale.combined /usr/bin/tailscale.combined
if [ -e "/usr/bin/tailscale" ] && [ ! -L "/usr/bin/tailscale" ]; then
    rm /usr/bin/tailscale
    ln -s /usr/bin/tailscale.combined /usr/bin/tailscale
fi
if [ -e "/usr/bin/tailscaled" ] && [ ! -L "/usr/bin/tailscaled" ]; then
    rm /usr/bin/tailscaled
    ln -s /usr/bin/tailscale.combined /usr/bin/tailscaled
fi

if [ ! -d "/opt/victronenergy/tailscale" ]; then
    echo "Create \"/opt/victronenergy/tailscale\" folder..."
    mkdir /opt/victronenergy/tailscale
fi
cp -f /data/venus-os_TailscaleGX/tailscale-control.py /opt/victronenergy/tailscale/tailscale-control.py
cp -rf /data/venus-os_TailscaleGX/ext /opt/victronenergy/tailscale/ext

# copy files in order that the initscript copies the service at startup
# https://github.com/victronenergy/meta-victronenergy/commit/7c45ff619fc0121da4d071e8c1158a43d9014281
cp -rf /data/venus-os_TailscaleGX/services/tailscale-backend /opt/victronenergy/service/tailscale-backend
cp -rf /data/venus-os_TailscaleGX/services/tailscale-control /opt/victronenergy/service/tailscale-control

# check if /opt/victronenergy/venus-platform/venus-platform was already modified
if [ ! -L "/opt/victronenergy/venus-platform/venus-platform" ]; then
    echo "Backup venus-platform and create symlink..."
    mv /opt/victronenergy/venus-platform/venus-platform /opt/victronenergy/venus-platform/venus-platform.bak
    if [ ! -L "/opt/victronenergy/venus-platform/venus-platform" ]; then
        ln -s /data/venus-os_TailscaleGX/FileSets/venus-platform /opt/victronenergy/venus-platform/venus-platform
    fi
fi

svc -t /service/venus-platform

# create needed dbus paths
echo "Copy settings file to create dbus settings paths in startup..."
cp -f /data/venus-os_TailscaleGX/FileSets/settings.d/tailscale /etc/venus/settings.d/tailscale

echo "Create dbus settings paths now..."
dbus -y com.victronenergy.settings /Settings AddSetting Services/Tailscale AccessLocalEthernet 0 i 0 1 > /dev/null
dbus -y com.victronenergy.settings /Settings AddSetting Services/Tailscale AccessLocalWifi 0 i 0 1 > /dev/null
dbus -y com.victronenergy.settings /Settings AddSetting Services/Tailscale CustomArguments "" s 0 0 > /dev/null
dbus -y com.victronenergy.settings /Settings AddSetting Services/Tailscale CustomNetworks "" s 0 0 > /dev/null
dbus -y com.victronenergy.settings /Settings AddSetting Services/Tailscale CustomServerUrl "" s 0 0 > /dev/null
dbus -y com.victronenergy.settings /Settings AddSetting Services/Tailscale Enabled 0 i 0 1 > /dev/null
dbus -y com.victronenergy.settings /Settings AddSetting Services/Tailscale MachineName "" s 0 0 > /dev/null
echo ""

# copy datalist.py for VRM logging
echo "Copy datalist.py for VRM logging..."
if [ ! -f "/opt/victronenergy/vrmlogger/datalist.py.bak" ]; then
    echo "Backup datalist.py..."
    cp /opt/victronenergy/vrmlogger/datalist.py /opt/victronenergy/vrmlogger/datalist.py.bak
fi
cp -f /data/venus-os_TailscaleGX/FileSets/datalist.py /opt/victronenergy/vrmlogger/datalist.py
# copy files as it will be when integrated into Venus OS | end



# create symlink in /service in order to start the service without reboot
if [ ! -L "/service/tailscale-backend" ]; then
    echo "Install tailscale-backend service..."
    ln -s /data/venus-os_TailscaleGX/services/tailscale-backend /service/tailscale-backend
else
    echo "Restart tailscale-backend service..."
    svc -t /service/tailscale-backend
fi

# create symlink in /service in order to start the service without reboot
if [ ! -L "/service/tailscale-control" ]; then
    echo "Install tailscale-control service..."
    ln -s /data/venus-os_TailscaleGX/services/tailscale-control /service/tailscale-control
else
    echo "Restart tailscale-control service..."
    svc -t /service/tailscale-control
fi
echo ""


# DISABLED since there are some changes which bricks the GUIv1 when installing on the wrong Venus OS version
# # check if file exists, if not install GUIv1 mod
# # can be removed after merging https://github.com/victronenergy/gui/pull/23
# if [ ! -f "/opt/victronenergy/gui/qml/PageSettingsServices.qml.orig" ]; then
#     echo "Install GUIv1 mod..."
#
#     mv /opt/victronenergy/gui/qml/PageSettingsServices.qml /opt/victronenergy/gui/qml/PageSettingsServices.qml.orig
#     cp /data/venus-os_TailscaleGX/FileSets/PatchSource/PageSettingsServices.qml /opt/victronenergy/gui/qml/PageSettingsServices.qml
#     cp /data/venus-os_TailscaleGX/FileSets/VersionIndependent/PageSettingsTailscale.qml /opt/victronenergy/gui/qml/PageSettingsTailscale.qml
#
# else
#     echo "Update GUIv1 mod..."
#
#     cp -f /data/venus-os_TailscaleGX/FileSets/PatchSource/PageSettingsServices.qml /opt/victronenergy/gui/qml/PageSettingsServices.qml
#     cp -f /data/venus-os_TailscaleGX/FileSets/VersionIndependent/PageSettingsTailscale.qml /opt/victronenergy/gui/qml/PageSettingsTailscale.qml
#
# fi
#
#
#
# # check if /service/gui exists
# if [ -L "/service/gui" ]; then
#     # nanopi, raspberrypi
#     servicePath="/service/gui"
# else
#     # cerbo gx
#     servicePath="/service/start-gui"
# fi
#
# # stop gui
# svc -d $servicePath
# # sleep 1 sec
# sleep 1
# # start gui
# svc -u $servicePath


# can be removed after merging https://github.com/victronenergy/gui-v2/pull/1393
# unzip venus-webassembly.zip to /tmp
echo "Unzip GUIv2 Tailscale..."
unzip -o /data/venus-os_TailscaleGX/FileSets/venus-webassembly.zip -d /tmp > /dev/null

# move gui v2 files and rename folder
echo "Move GUIv2 Tailscale files..."
if [ -d "/var/www/venus/gui-beta" ]; then
    rm -rf /var/www/venus/gui-beta
fi
mv /tmp/wasm /var/www/venus/gui-beta

# create missing files for VRM portal check
echo "GZip WASM build..."
cd /var/www/venus/gui-beta
gzip -k venus-gui-v2.wasm
echo "Create SHA256 checksum..."
sha256sum /var/www/venus/gui-beta/venus-gui-v2.wasm > /var/www/venus/gui-beta/venus-gui-v2.wasm.sha256

echo ""
echo ""
echo "Install completed. Visit http://venusos.local/gui-beta and navigate to Settings -> Services -> Tailscale to test."
echo "If the Tailscale menu is not visible in the GUIv2 opened via the beta VRM portal, then restart the GX device once."
echo ""
