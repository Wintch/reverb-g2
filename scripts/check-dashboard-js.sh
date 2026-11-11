#!/bin/bash
# Syntax-check the JavaScript the status dashboard ACTUALLY SERVES.
#
# Why this exists: PAGE in status-dashboard.py is a non-raw Python """...""" string with
# inline JS in it. A `\"` written inside it is eaten by Python's own parser and reaches the
# browser as a bare `"`, which is a syntax error that kills the entire <script> block -- the
# page then renders as a static skeleton with no values and no visible error. This has
# happened twice (2026-08-27 and 2026-09-06, both in the I18N tables).
#
# Checking the .py source text does NOT catch it: a regex over the source preserves the
# backslash that Python is about to remove. Only the served bytes tell the truth, which is
# what this script checks.
#
# Usage:  scripts/check-dashboard-js.sh [url]     (default http://127.0.0.1:8765/)
# Exit:   0 = the served JS parses, 1 = it does not, 2 = could not check.

set -u
URL="${1:-http://127.0.0.1:8765/}"
TMP=$(mktemp -d) || exit 2
trap 'rm -rf "$TMP"' EXIT

command -v node >/dev/null 2>&1 || { echo "check-dashboard-js: node not installed, cannot check"; exit 2; }

if ! curl -fsS -m 15 "$URL" -o "$TMP/page.html"; then
	echo "check-dashboard-js: could not fetch $URL (is status-dashboard.service running?)"
	exit 2
fi

python3 - "$TMP" <<'PY' || exit 2
import re, sys, os
d = sys.argv[1]
html = open(os.path.join(d, "page.html"), encoding="utf-8").read()
blocks = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S)
if not blocks:
    print("check-dashboard-js: no inline <script> found in the served page")
    sys.exit(2)
for i, b in enumerate(blocks):
    open(os.path.join(d, f"block_{i}.js"), "w", encoding="utf-8").write(b)
print(f"check-dashboard-js: {len(blocks)} inline script block(s), {len(html)} bytes of HTML")
PY

rc=0
for js in "$TMP"/block_*.js; do
	if ! node --check "$js" 2>"$TMP/err"; then
		echo "check-dashboard-js: FAIL -- the served JavaScript does not parse:"
		sed -n '1,12p' "$TMP/err" | sed 's/^/    /'
		echo "    (look for a single-escaped \\\" inside PAGE in scripts/status-dashboard.py --"
		echo "     it must be \\\\\" so that Python emits \\\" to the browser)"
		rc=1
	fi
done

[ "$rc" = 0 ] && echo "check-dashboard-js: OK -- served JavaScript parses cleanly"
exit "$rc"
