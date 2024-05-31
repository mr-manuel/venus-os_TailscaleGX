#!/bin/bash

# uninstallation without SetupHelper

# stop services
svc -d /service/TailscaleGX-backend
svc -d /service/TailscaleGX-control


# remove services
rm /service/TailscaleGX-backend
rm /service/TailscaleGX-control

rm /opt/victronenergy/service/TailscaleGX-backend
rm /opt/victronenergy/service/TailscaleGX-control


# check if file exists, if yes uninstall GUIv1 mod
if [ -f "/opt/victronenergy/gui/qml/PageSettingsServices.qml.orig" ]; then
    echo "Uninstall GUIv1 mod..."

    rm /opt/victronenergy/gui/qml/PageSettingsServices.qml
    rm /opt/victronenergy/gui/qml/PageSettingsTailscale.qml
    mv /opt/victronenergy/gui/qml/PageSettingsServices.qml.orig /opt/victronenergy/gui/qml/PageSettingsServices.qml

    # restart gui service
    svc -d /service/gui
    sleep 5
    svc -u /service/gui
fi
