#!/bin/bash

# installation without SetupHelper

# make files executable

echo "Make files executable..."
chmod +x /data/venus-os_TailscaleGX/*.sh
chmod +x /data/venus-os_TailscaleGX/*.py
chmod +x /data/venus-os_TailscaleGX/tailscale*
chmod +x /data/venus-os_TailscaleGX/services/*/run
chmod +x /data/venus-os_TailscaleGX/services/*/log/run


# try to expand system partition
bash /opt/victronenergy/swupdate-scripts/resize2fs.sh


# cleanup typo
if [ -d "/services" ]; then
    echo "Remove old \"/services\" folder..."
    rm -rf /services
fi

# cleanup old version
if [ -d "/data/TailscaleGX" ]; then
    echo "Remove old \"/data/TailscaleGX\" folder..."
    rm -rf /data/TailscaleGX
fi

# cleanup old service copies
if [ -d "/service/TailscaleGX-backend" ]; then
    echo "Remove old \"/service/TailscaleGX-backend\" folder..."
    rm -rf /service/TailscaleGX-backend
fi
if [ -d "/service/TailscaleGX-control" ]; then
    echo "Remove old \"/service/TailscaleGX-control\" folder..."
    rm -rf /service/TailscaleGX-control
fi


# make system writable
echo "Make filesystem writable..."
bash /opt/victronenergy/swupdate-scripts/remount-rw.sh


if [ ! -L "/opt/victronenergy/service/TailscaleGX-backend" ]; then
    # create symlink in order that the initscript copies the service at startup
    # https://github.com/victronenergy/meta-victronenergy/commit/7c45ff619fc0121da4d071e8c1158a43d9014281
    ln -s /data/venus-os_TailscaleGX/services/TailscaleGX-backend /opt/victronenergy/service/TailscaleGX-backend
fi

if [ ! -L "/opt/victronenergy/service/TailscaleGX-control" ]; then
    # create symlink in order that the initscript copies the service at startup
    # https://github.com/victronenergy/meta-victronenergy/commit/7c45ff619fc0121da4d071e8c1158a43d9014281
    ln -s /data/venus-os_TailscaleGX/services/TailscaleGX-control /opt/victronenergy/service/TailscaleGX-control
fi

# recreate services link
if [ ! -L "/service/TailscaleGX-backend" ]; then
    echo "Install TailscaleGX-backend service..."
    # create symlink in /service in order to start the service without reboot
    ln -s /data/venus-os_TailscaleGX/services/TailscaleGX-backend /service/TailscaleGX-backend
else
    echo "Restart TailscaleGX-backend service..."
    svc -t /service/TailscaleGX-backend
fi

# check if service exists
if [ ! -L "/service/TailscaleGX-control" ]; then
    echo "Install TailscaleGX-control service..."
    # create symlink in /service in order to start the service without reboot
    ln -s /data/venus-os_TailscaleGX/services/TailscaleGX-control /service/TailscaleGX-control
else
    echo "Restart TailscaleGX-control service..."
    svc -t /service/TailscaleGX-control
fi


# check if file exists, if not install GUIv1 mod
if [ ! -f "/opt/victronenergy/gui/qml/PageSettingsServices.qml.orig" ]; then
    echo "Install GUIv1 mod..."

    mv /opt/victronenergy/gui/qml/PageSettingsServices.qml /opt/victronenergy/gui/qml/PageSettingsServices.qml.orig
    cp /data/venus-os_TailscaleGX/FileSets/PatchSource/PageSettingsServices.qml /opt/victronenergy/gui/qml/PageSettingsServices.qml
    cp /data/venus-os_TailscaleGX/FileSets/VersionIndependent/PageSettingsTailscale.qml /opt/victronenergy/gui/qml/PageSettingsTailscale.qml

else
    echo "Update GUIv1 mod..."

    cp -f /data/venus-os_TailscaleGX/FileSets/PatchSource/PageSettingsServices.qml /opt/victronenergy/gui/qml/PageSettingsServices.qml
    cp -f /data/venus-os_TailscaleGX/FileSets/VersionIndependent/PageSettingsTailscale.qml /opt/victronenergy/gui/qml/PageSettingsTailscale.qml

fi


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
echo "Install completed. Visit http://venusos.local/gui-beta and navigate to Settings -> Services -> Tailscale to test."
echo "To make GUIv2 with Tailscale available in the VRM portal reboot your GX device once."
echo ""
