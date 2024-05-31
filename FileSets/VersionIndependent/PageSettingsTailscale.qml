import QtQuick 1.1
import com.victron.velib 1.0
import "utils.js" as Utils

MbPage {
	title: qsTr("Tailscale (remote VPN access)")

	property string servicePrefix: "com.victronenergy.tailscaleGX"
	property string settingsPrefix: "com.victronenergy.settings"

	VBusItem {
		id: commandItem;
		bind: Utils.path(servicePrefix, "/GuiCommand")
	}
	VBusItem {
		id: errorMessageItem;
		bind: Utils.path(servicePrefix, "/ErrorMessage")
	}
	VBusItem {
		id: ipV4Item;
		bind: Utils.path(servicePrefix, "/IPv4")
	}
	VBusItem {
		id: ipV6Item;
		bind: Utils.path(servicePrefix, "/IPv6")
	}
	VBusItem {
		id: loginItem;
		bind: Utils.path(servicePrefix, "/LoginLink")
	}
	VBusItem {
		id: stateItem;
		bind: Utils.path(servicePrefix, "/State")
	}

	VBusItem {
		id: enabledItem;
		bind: Utils.path(settingsPrefix, "/Settings/Services/Tailscale/Enabled")
	}
	VBusItem {
		id: hostNameItem;
		bind: Utils.path(settingsPrefix, "/Settings/Services/Tailscale/Hostname")
	}

	property int connectState: stateItem.valid ? stateItem.value : 0
	property string errorMessage: errorMessageItem.valid && errorMessageItem.value !== "" && isEnabled ? "<br><br>ERROR: " + errorMessageItem.value : ""
	property string hostName: hostNameItem.valid ? hostNameItem.value : ""
	property string ipV4: ipV4Item.valid ? ipV4Item.value : ""
	property string ipV6: ipV6Item.valid ? ipV6Item.value : ""
	property string loginLink: loginItem.valid ? loginItem.value : ""

	property bool isRunning: stateItem.valid
	property bool isEnabled: switchTailscaleEnabled.checked
	property bool isEnabledAndRunning: isEnabled && isRunning
	property bool isConnected: connectState == 100 && isEnabledAndRunning

	function getState () {
		var returnValue;

		if ( ! isRunning )
			returnValue = "Tailscale control not running"
		else if ( ! isEnabledAndRunning )
			returnValue = "Service not enabled"
		else if ( isConnected )
			returnValue = "Connection successful"
		else if ( connectState == 0 )
			return ""
		else if ( connectState == 1 )
			returnValue = "Starting..."
		else if ( connectState == 2 || connectState == 3)
			returnValue = "Tailscale starting..."
		else if ( connectState == 4)
			returnValue = "This GX device is logged out of Tailscale"
		else if ( connectState == 5)
			returnValue = "Waiting for a response from Tailscale..."
		else if ( connectState == 6)
			returnValue = "Connect this GX device to your Tailscale account by opening this link:<br><br>" + loginLink
		else
			returnValue =  "Unknown state: " + connectState

		return ( qsTr ( "<b>Current state:</b> " + returnValue + (connectState != 6 ? errorMessage : "" ) ) )
	}

    model: VisibleItemModel {
		MbSwitch {
			id: switchTailscaleEnabled
			name: qsTr("Enable")
			bind: Utils.path( settingsPrefix, "/Settings/Services/Tailscale/Enabled")
			writeAccessLevel: User.AccessInstaller
			enabled: isRunning
		}
		MbItemText {
			text: qsTr("Enables a secure remote access via a VPN mesh network. A free account at Tailscale is required.")
			wrapMode: Text.WordWrap
			horizontalAlignment: Text.AlignLeft
			show: ! isEnabled
		}

		MbItemText {
			text: getState ()
			wrapMode: Text.WordWrap
			horizontalAlignment: Text.AlignLeft
		}

		MbItem {
			height: 170
			show: loginLink !== "" && isEnabled && connectState == 6

			Image {
				// NOTE: To discuss, if this is OK or if it's better to use the QtQrCode library
				// has to be http link since https does not work
				source: loginLink !== "" ? "http://api.qrserver.com/v1/create-qr-code/?size=150x150&data=" + loginLink : ""

				width: 150
				height: 150
				anchors.horizontalCenter: parent.horizontalCenter
				anchors.verticalCenter: parent.verticalCenter
			}
		}

		MbItemValue {
			description: qsTr("IPv4")
			show: item.valid && item.value !== "" && isConnected
			item.bind: Utils.path( servicePrefix, "/IPv4")
		}

		MbItemValue {
			description: qsTr("IPv6")
			show: item.valid && item.value !== "" && isConnected
			item.bind: Utils.path( servicePrefix, "/IPv6")
		}

		MbOK {
			id: logoutButton
			description: qsTr("Logout from Tailscale account")
			value: qsTr ("Logout")
			onClicked: commandItem.setValue ('logout')

			writeAccessLevel: User.AccessInstaller
			show: isConnected
		}

		MbItemText {
			text: qsTr("Advanced options (can only be modified when not connected)<br>For more details see https://tailscale.com/kb/1241/tailscale-up")
			wrapMode: Text.WordWrap
			horizontalAlignment: Text.AlignLeft
			showAccessLevel: User.AccessInstaller
		}

		MbSwitch {
			name: qsTr("Accept routes")
			bind: Utils.path( settingsPrefix, "/Settings/Services/Tailscale/AcceptRoutes")
			showAccessLevel: User.AccessInstaller
			enabled: ! (enabledItem.valid && enabledItem.value == 1)
		}
		MbItemText {
			text: qsTr("|- Accept subnet routes that other nodes advertise.")
			wrapMode: Text.WordWrap
			horizontalAlignment: Text.AlignLeft
		}

		MbSwitch {
			name: qsTr("Advertise exit node")
			bind: Utils.path( settingsPrefix, "/Settings/Services/Tailscale/AdvertiseExitNode")
			showAccessLevel: User.AccessInstaller
			enabled: ! (enabledItem.valid && enabledItem.value == 1)
		}
		MbItemText {
			text: qsTr("|- Offer to be an exit node for outbound internet traffic from the Tailscale network.")
			wrapMode: Text.WordWrap
			horizontalAlignment: Text.AlignLeft
		}

		MbEditBox {
			description: qsTr("Advertise routes")
			readonly: enabledItem.valid && enabledItem.value == 1
			item.bind: Utils.path( settingsPrefix, "/Settings/Services/Tailscale/AdvertiseRoutes")
			maximumLength: 255
			enableSpaceBar: false
		}
		MbItemText {
			text: qsTr("|- Expose physical subnet routes to your entire Tailscale network.<br><br><b>NOTE:</b> If you haven't enabled \"autoApprovers\" in the Tailscale admin console, then you need to manually approve the route in the Tailscale admin console. See https://tailscale.com/kb/1019/subnets -> Enable subnet routes from the admin console")
			wrapMode: Text.WordWrap
			horizontalAlignment: Text.AlignLeft
		}

		MbEditBox {
			description: qsTr("Exit node (IP or name)")
			readonly: enabledItem.valid && enabledItem.value == 1
			item.bind: Utils.path( settingsPrefix, "/Settings/Services/Tailscale/ExitNode")
			maximumLength: 255
			enableSpaceBar: false
		}
		MbItemText {
			text: qsTr("|- Provide a Tailscale IP or machine name to use as an exit node.")
			wrapMode: Text.WordWrap
			horizontalAlignment: Text.AlignLeft
		}

		MbEditBox {
			description: qsTr("Hostname")
			readonly: enabledItem.valid && enabledItem.value == 1
			item.bind: Utils.path( settingsPrefix, "/Settings/Services/Tailscale/Hostname")
			maximumLength: 255
			enableSpaceBar: false
		}

		MbEditBox {
			description: qsTr("Custom server URL (Headscale)")
			readonly: enabledItem.valid && enabledItem.value == 1
			item.bind: Utils.path( settingsPrefix, "/Settings/Services/Tailscale/CustomServerUrl")
			maximumLength: 255
			enableSpaceBar: false
		}

		MbEditBox {
			description: qsTr("Custom Tailscale up arguments")
			readonly: enabledItem.valid && enabledItem.value == 1
			item.bind: Utils.path( settingsPrefix, "/Settings/Services/Tailscale/CustomArguments")
			maximumLength: 255
			enableSpaceBar: false
		}
		MbItemText {
			text: qsTr("|- Add custom arguments to the 'tailscale up' command.")
			wrapMode: Text.WordWrap
			horizontalAlignment: Text.AlignLeft
		}
	}
}
