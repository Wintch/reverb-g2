#!/bin/bash
# run-ab.sh - run `monado-cli test` from two minimal HDK-only builds (monado-cli-main = upstream
# main, monado-cli-fix = the prober fix, both copied next to this script) against whatever is on
# the bus, normally the emulated HDK from hdk-gadget.sh. See docs/145.
cd "$(dirname "$0")"
for v in main fix; do
	XRT_LOG=debug HDK_LOG=debug timeout 20 ./monado-cli-$v test > test-$v.log 2>&1
	echo "== $v (rc=$?)"
	grep -E 'hdk|HDK|string_descriptor|Using builder|head:' test-$v.log | sed 's/^/   /'
done
