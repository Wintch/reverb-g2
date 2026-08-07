#!/bin/bash
# get360.sh - download a 360 video from YouTube and leave it ready for the hello_xr player.
#
#   ./get360.sh <URL>                  best equirectangular format, up to 8K
#   ./get360.sh -l <URL>               just list what is available, download nothing
#   ./get360.sh -s 0:00-0:30 <URL>     only that section (needs ffmpeg, which we have)
#   ./get360.sh -m 2160 <URL>          cap the height (2160 = 4K, 4320 = 8K)
#   ./get360.sh -k <URL>               keep the original download as well as the converted file
#   ./get360.sh -n <URL>               normal (non-VR) client - see below
#
# VR STREAMS. For 360/VR180 videos YouTube keeps the real immersive streams behind the
# `android_vr` player client and serves everyone else a flat, monoscopic, lower-resolution
# rendering of the same video. Same URL, completely different content - and nothing in the
# output says so. Compare on one VR180 title:
#
#   default client:    3136x1764  60fps  mono, flat        (max)
#   android_vr client: 7680x4096  60fps  stereo side-by-side, "mesh"
#
# So this script asks for android_vr FIRST and only falls back to the normal client if that
# comes up empty (-n forces the normal client). The catch: android_vr does not accept cookies,
# so age-restricted videos need -n, and then you only get the flat version. In the format
# listing, "s" instead of "p" in the note column (2160s60 vs 2160p60) means stereo.
#
# Why this script exists - three things have to be right or YouTube hands back nothing but
# storyboard thumbnails, and the error messages do not make the cause obvious:
#
#   1. A JavaScript runtime. YouTube obfuscates stream URLs behind an "n challenge" that
#      yt-dlp has to execute JS to solve. Only deno is enabled by default (node is supported
#      but must be named explicitly, and in practice it still failed here). deno lives in
#      ~/.local/bin, so PATH is set below.
#   2. The EJS challenge solver scripts: `pipx inject yt-dlp yt-dlp-ejs`. The runtime alone
#      is not enough.
#   3. Cookies, for age-restricted videos: --cookies-from-browser chrome.
#
# Symptom when any of these is missing: "Only images are available for download".
#
# The conversion at the end is not cosmetic. The player's upload path wants 8-bit NV12, and
# NVDEC on this card does not accept what YouTube usually serves for 8K (AV1 10-bit), so it
# silently falls back to libdav1d on the CPU. Measured on the real 8K sample: 10 fps as
# downloaded (37ms/frame in the bit-depth conversion alone) versus 17 fps once converted to
# 8-bit HEVC. HDR is tone-mapped to SDR at the same time - the headset has no HDR path.

set -u

OUTDIR="$HOME/Documents/linux_vr_base/photo360"
export PATH="$HOME/.local/bin:$PATH"
YTDLP="$HOME/.local/bin/yt-dlp"
BROWSER=chrome

LIST=0
SECTION=""
MAXH=4320
KEEP=0
NOVR=0

while getopts "ls:m:knh" opt; do
	case "$opt" in
		l) LIST=1 ;;
		s) SECTION="$OPTARG" ;;
		m) MAXH="$OPTARG" ;;
		k) KEEP=1 ;;
		n) NOVR=1 ;;
		h|*) sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
	esac
done
shift $((OPTIND - 1))

if [ $# -lt 1 ]; then
	echo "usage: $0 [-l] [-s START-END] [-m MAX_HEIGHT] [-k] [-n] <URL>" >&2
	exit 1
fi
URL="$1"

# The two clients are mutually exclusive: android_vr unlocks the stereo/high-res streams but
# refuses cookies, the normal client takes cookies but only ever sees the flat version.
if [ "$NOVR" = "1" ]; then
	CLIENT_ARGS=(--cookies-from-browser "$BROWSER")
	CLIENT_NAME="normal (with cookies, flat version only)"
else
	CLIENT_ARGS=(--extractor-args "youtube:player_client=android_vr")
	CLIENT_NAME="android_vr (real VR streams, no cookies)"
fi

command -v deno >/dev/null || {
	echo "deno is not on PATH. Without a JS runtime, YouTube returns only storyboards." >&2
	echo "Get it with:" >&2
	echo "  curl -fsSL -o /tmp/deno.zip https://github.com/denoland/deno/releases/latest/download/deno-x86_64-unknown-linux-gnu.zip" >&2
	echo "  unzip -o /tmp/deno.zip -d ~/.local/bin && chmod +x ~/.local/bin/deno" >&2
	exit 1
}
"$YTDLP" --version >/dev/null 2>&1 || { echo "cannot find yt-dlp at $YTDLP" >&2; exit 1; }

mkdir -p "$OUTDIR"

if [ "$LIST" = "1" ]; then
	echo "Client: $CLIENT_NAME"
	echo "(in the last column, '2160s60' = stereo, '2160p60' = flat/mono)"
	"$YTDLP" "${CLIENT_ARGS[@]}" -F "$URL" 2>&1 | grep -viE "^\[debug\]|Extracting cookies|Extracted [0-9]"
	exit 0
fi

AVAIL_KB=$(df -Pk "$OUTDIR" | awk 'NR==2{print $4}')
if [ "$AVAIL_KB" -lt 3145728 ]; then
	echo "Warning: less than 3 GB free in $OUTDIR. A full 8K download may not fit." >&2
fi

SECTION_ARGS=()
[ -n "$SECTION" ] && SECTION_ARGS=(--download-sections "*${SECTION}")

echo "Downloading (up to ${MAXH}p) - client $CLIENT_NAME"
SRC_TMPL="$OUTDIR/%(title).60s [%(id)s].src.%(ext)s"
# Progress goes to stderr so that stdout carries ONLY the downloaded file's path - this runs
# inside $(...) and anything else it prints ends up concatenated into the filename.
download() {
	"$YTDLP" "$@" \
		-f "bv*[height<=${MAXH}]/bv*" \
		"${SECTION_ARGS[@]}" \
		-o "$SRC_TMPL" \
		--print after_move:filepath \
		"$URL" 2>&1 | grep -viE "^\[debug\]|Extracting cookies|Extracted [0-9]" | tee /tmp/get360.$$.log >&2
	grep -E "^${OUTDIR}/" /tmp/get360.$$.log | tail -1
}

SRC=$(download "${CLIENT_ARGS[@]}")
if { [ -z "$SRC" ] || [ ! -f "$SRC" ]; } && [ "$NOVR" = "0" ]; then
	# android_vr came up empty - typically an age-restricted video, which it cannot open
	# because it refuses cookies. Retry with the cookie-capable client, accepting the flat
	# version rather than failing outright.
	echo "The VR client returned nothing; retrying with the normal client (flat version only)..." >&2
	SRC=$(download --cookies-from-browser "$BROWSER")
fi
rm -f /tmp/get360.$$.log
if [ -z "$SRC" ] || [ ! -f "$SRC" ]; then
	echo "Nothing was downloaded. If it says 'Only images are available', check the three points in the header." >&2
	exit 1
fi

# One ffprobe call per field. A single call with a comma-separated -show_entries list prints
# the values in ffprobe's own field order, NOT the order they were asked for, so positional
# `read` silently assigns them to the wrong variables - which is how this ended up doing a
# software AV1 decode at the fallback bitrate.
probe() { ffprobe -v error -select_streams v:0 -show_entries "stream=$1" -of default=nw=1:nk=1 "$SRC" | head -1; }
W=$(probe width)
H=$(probe height)
CODEC=$(probe codec_name)
PIXFMT=$(probe pix_fmt)
TRC=$(probe color_transfer)
FPS=$(ffprobe -v error -select_streams v:0 -show_entries stream=avg_frame_rate -of default=nw=1:nk=1 "$SRC" | head -1)
[ "$TRC" = "unknown" ] && TRC=""
case "$W" in ''|*[!0-9]*) echo "ffprobe did not return a usable width for '$SRC'" >&2; exit 1 ;; esac
echo "Source: ${W}x${H} $CODEC $PIXFMT ${TRC:-sdr} @ ${FPS} fps"

# Anything 8-bit that NVDEC can decode is left exactly as it is - the player picks a
# hardware-capable decoder itself and gets the NV12 surface straight into GPU memory. That
# includes AV1 (measured: 8K60 AV1 decodes at the full 59 fps on this card), so YouTube's own
# 8K VR streams need no re-encode at all. Only an HDR transfer is still worth mapping down,
# since the headset has no HDR path.
NEEDS_CONV=1
case "$CODEC:$PIXFMT" in
	h264:yuv420p|hevc:yuv420p|av1:yuv420p|vp9:yuv420p)
		case "${TRC:-bt709}" in
			arib-std-b67|smpte2084) NEEDS_CONV=1 ;;
			*) NEEDS_CONV=0 ;;
		esac
		;;
esac

if [ "$NEEDS_CONV" = "0" ]; then
	FINAL="${SRC%.src.*}.mp4"
	mv -n "$SRC" "$FINAL" && echo "Done (no conversion needed): $FINAL"
	exit 0
fi

FINAL="${SRC%.src.*}.mp4"
echo "Converting to 8-bit SDR HEVC (this takes a while: ~20 min for a 50s 8K clip)..."

# Tone-map only when the source actually carries an HDR transfer. HLG (arib-std-b67) is
# watchable as-is on an SDR display by design, but mapping it properly still looks better.
TONEMAP=""
case "${TRC:-}" in
	arib-std-b67|smpte2084)
		TONEMAP="zscale=t=${TRC}:m=bt2020nc:p=bt2020:r=tv,zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,"
		;;
esac

# Decode on the GPU when the source codec has a CUVID decoder; the tone-map chain runs on the
# CPU either way and is the slow part. When we do decode on the GPU the frames have to come
# back down before the CPU filters can touch them, and the download format has to match the
# source bit depth - asking for p010 from an 8-bit stream (or vice versa) fails the graph.
HWIN=()
DL=""
case "$CODEC" in
	av1|hevc|h264|vp9)
		if ffmpeg -hide_banner -decoders 2>/dev/null | grep -q "${CODEC}_cuvid"; then
			HWIN=(-hwaccel cuda -hwaccel_output_format cuda -c:v "${CODEC}_cuvid")
			case "$PIXFMT" in
				*10le|*10be|p010*) DL="hwdownload,format=p010le," ;;
				*) DL="hwdownload,format=nv12," ;;
			esac
		fi
		;;
esac

# Rough bitrate ladder - 8K equirect needs a lot to not smear in the headset.
if [ "$W" -ge 7000 ]; then BR=100M; elif [ "$W" -ge 3500 ]; then BR=45M; else BR=20M; fi

if ffmpeg -y -hide_banner -loglevel warning "${HWIN[@]}" -i "$SRC" \
	-vf "${DL}${TONEMAP}format=yuv420p" \
	-c:v hevc_nvenc -preset p5 -b:v "$BR" -rc vbr "$FINAL"; then
	:
else
	echo "Failed with GPU decoding, retrying everything in software..."
	ffmpeg -y -hide_banner -loglevel warning -i "$SRC" \
		-vf "${TONEMAP}format=yuv420p" \
		-c:v hevc_nvenc -preset p5 -b:v "$BR" -rc vbr "$FINAL" || exit 1
fi

[ "$KEEP" = "1" ] || rm -f "$SRC"
echo "Done: $FINAL"
ffprobe -v error -show_entries stream=width,height,codec_name,pix_fmt -show_entries format=duration \
	-of default=nw=1 "$FINAL"
echo
echo "To watch it:"
echo "  HELLO_XR_VIDEO360='$FINAL' ./jack-in.sh 3dof   # if the stack isn't up yet"
echo "  sleep 180 | XR_RUNTIME_JSON=\$HOME/Documents/linux_vr_base/monado/build/openxr_monado-dev.json \\"
echo "    IPC_IGNORE_VERSION=1 HELLO_XR_VIDEO360='$FINAL' \\"
echo "    \$HOME/Documents/linux_vr_base/OpenXR-SDK-Source/build/src/tests/hello_xr/hello_xr --graphics Vulkan2"
