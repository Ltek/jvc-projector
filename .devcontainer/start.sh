#!/bin/sh
mkdir -p /config/custom_components
ln -sf /workspace/custom_components/jvc_projector_ha /config/custom_components/jvc_projector_ha
nohup hass -c /config > /tmp/hass.log 2>&1 &
exec sleep infinity
