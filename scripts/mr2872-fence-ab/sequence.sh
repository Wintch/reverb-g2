#!/bin/bash
# sequence.sh -- ABBA sequence of run-one.sh over several synthetic loads (docs/141).
# MODE 2 = old per-frame temporary fence, MODE 1 = MR !2872 persistent fences (XRT_TEST_NO_TIMELINE knob).
# Results labels are listed in /tmp/ab-seq.list; /tmp/ab-seq.done appears at the end.
LOADS="${LOADS:-5 7}"; SECS="${SECS:-75}"
J=${RUNTIME_JSON:-$HOME/vr/monado-fence/build/openxr_monado-dev.json}
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
rm -f /tmp/ab-seq.done /tmp/ab-seq.list
for LOAD in $LOADS; do
  for MODE in 2 1 1 2; do
    L="T-L${LOAD}-M${MODE}-$(date +%H%M%S)"
    XRT_TEST_NO_TIMELINE=$MODE HELLO_XR_GPU_LOAD=$LOAD "$HERE/run-one.sh" "$L" "$J" "$SECS"
    echo "$L" >> /tmp/ab-seq.list
    sleep 6
  done
done
touch /tmp/ab-seq.done
