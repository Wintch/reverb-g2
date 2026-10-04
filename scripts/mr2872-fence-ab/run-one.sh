#!/bin/bash
# run-one.sh LABEL RUNTIME_JSON SECONDS -- one hello_xr run against a running monado-service,
# marks the start/end lines of ~/vr/jack-in-wayland.log in /tmp/ab-LABEL-{mark,end} (docs/141).
# Optional env: XRT_TEST_NO_TIMELINE=1|2 (needs the local test knob), HELLO_XR_GPU_LOAD=<0-100>.
cd ~/vr
eval "$(python3 -c "
import sys; sys.path.insert(0,\".\"); import gui_env
e=gui_env.get()
for k in (\"XDG_RUNTIME_DIR\",\"WAYLAND_DISPLAY\",\"DISPLAY\",\"XAUTHORITY\"):
    print(f\"export {k}=\\\"{e[k]}\\\"\") if k in e else None
")"
echo $(wc -l < jack-in-wayland.log) > /tmp/ab-$1-mark
export HELLO_XR_PHOTO360=$HOME/Documents/linux_vr_base/photo360/testgrid.png HELLO_XR_DURATION_S=$3 XR_RUNTIME_JSON=$2 IPC_IGNORE_VERSION=1
sleep $(( $3 + 10 )) | ~/vr/OpenXR-SDK-Source/build/src/tests/hello_xr/hello_xr --graphics Vulkan2 > /tmp/ab-$1-hello.out 2>&1
echo $(wc -l < jack-in-wayland.log) > /tmp/ab-$1-end
touch /tmp/ab-$1.done
