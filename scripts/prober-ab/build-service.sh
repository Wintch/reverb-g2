#!/bin/bash
# build-service.sh - build upstream main and the prober fix (docs/145) from one worktree
# (~/vr/monado-prober) and keep each monado-service in its own dir: the binary MUST keep the
# name monado-service (comm is truncated to 15 chars; launchers match it with pgrep -x).
set -euo pipefail
W=~/vr/monado-prober; B=$W/build; OUT=~/vr/monado-prober-bin
cmake -S $W -B $B -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo > $OUT/cmake.log 2>&1
for v in main:13b5c134b16c86ff3e3be52e8fa6dc720a8247e0 fix:6eedc6cf87a7a34c64309d3eb69c70f34ca00db6; do
	n=${v%%:*}; sha=${v#*:}
	git -C $W checkout -q --detach $sha
	nice ninja -C $B monado-service > $OUT/build-$n.log 2>&1
	mkdir -p $OUT/$n; cp $B/src/xrt/targets/service/monado-service $OUT/$n/monado-service
	echo "$n $sha $(sha256sum $OUT/$n/monado-service | cut -c1-16) warnings=$(grep -c 'warning:' $OUT/build-$n.log || true)" >> $OUT/builds.txt
done
