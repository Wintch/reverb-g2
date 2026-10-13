#!/bin/bash
set -u
D=~/vr/media/review; mkdir -p "$D"; cd "$D"
SRC=/mnt/videos/bench/insta4k_sdr.mp4
mk() { # name ss dur tone_hz tone_dur label
  ffmpeg -v error -y -ss "$2" -t "$3" -i "$SRC" -f lavfi -t "$5" -i "sine=frequency=$4:sample_rate=48000" \
    -filter_complex "[0:v]drawtext=fontsize=150:fontcolor=yellow:box=1:boxcolor=black@0.7:x=(w-tw)/2:y=(h-th)/2:text='$6 %{n} %{pts\:hms}'[v]" \
    -map "[v]" -map 1:a -c:v h264_nvenc -b:v 30M -c:a aac "$1"
}
mk a-tone15s.mp4 0 40 440 15 A
mk b-tone30s.mp4 10 30 880 30 B
for f in *.mp4; do echo "$f: $(ffprobe -v error -show_entries stream=codec_type,duration,r_frame_rate -of csv=p=0 "$f" | tr '\n' ' ')"; done
