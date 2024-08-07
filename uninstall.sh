#!/bin/bash

# uninstallation without SetupHelper

# stop services
if [ -d "/service/tailscale-backend" ]; then
    echo "Stop service tailscale-backend..."
    svc -d /service/tailscale-backend
    rm -rf /service/tailscale-backend
    rm -rf /opt/victronenergy/service/tailscale-backend
fi
if [ -d "/service/tailscale-control" ]; then
    echo "Stop service tailscale-control..."
    svc -d /service/tailscale-control
    rm -rf /service/tailscale-control
    rm -rf /opt/victronenergy/service/tailscale-control
fi

if [ -d "/service/TailscaleGX-backend" ]; then
    echo "Stop service TailscaleGX-backend..."
    svc -d /service/TailscaleGX-backend
    rm -rf /service/TailscaleGX-backend
    rm -rf /opt/victronenergy/service/TailscaleGX-backend
fi
if [ -d "/service/TailscaleGX-control" ]; then
    echo "Stop service TailscaleGX-control..."
    svc -d /service/TailscaleGX-control
    rm -rf /service/TailscaleGX-control
    rm -rf /opt/victronenergy/service/TailscaleGX-backend
fi

if [ -d "/opt/victronenergy/tailscale" ]; then
    rm -rf /opt/victronenergy/tailscale
fi


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
