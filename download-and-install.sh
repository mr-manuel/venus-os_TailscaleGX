#!/bin/bash

wget -O /tmp/venus-os_TailscaleGX.zip https://github.com/mr-manuel/venus-os_TailscaleGX/archive/refs/heads/main.zip
unzip /tmp/venus-os_TailscaleGX.zip -d /tmp > /dev/null
rm -rf /data/venus-os_TailscaleGX 2>/dev/null
mv /tmp/venus-os_TailscaleGX-main /data/venus-os_TailscaleGX

bash /data/venus-os_TailscaleGX/install.sh
