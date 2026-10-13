# review-session

The wearer-session kit used on 2026-10-13 to check the docs/147 fixes on the rig (`docs/147` §10).
The scripts are copied to `~/vr/review-session/` on the lab box and run from there.

- `make-test-clips.sh`: writes two 360 clips to `~/vr/media/review/` with the frame number and
  time burned in. A has a 15 s tone on a 40 s video; B has a tone over its whole 30 s.
- `player-up.sh` / `player-down.sh`: Monado in 3dof plus the player on those clips. Keys come from
  the `keys` FIFO through a `script` pty. `play360.sh` replaces a non-tty stdin with
  `sleep infinity`, so keys need a pty.
- `player-protocol.sh`: guided steps with spoken prompts in the headset (pause, seek while paused,
  frame steps, play past the audio end, recenter, next). Clip A runs out during step 5, so start
  it nearer the beginning of A or lengthen the clip before reusing it.
- `aircar-up.sh <label> <neck_mm>` / `aircar-down.sh`: Aircar through `vr-launcher.py` in 6dof with
  only `SLAM_PRED_NECK_ARM_MM` overridden. Ambient env wins over the launcher's title profile.
- `vrpath.sh review|restore`: points OpenVR's first runtime at `~/vr/xrizer-review`, or restores
  the backup.

Both up scripts power the host Bluetooth adapter off and set `VR_BT_CTRL_CHECK=0`, so asleep
host-bonded controllers cannot stop the launch. `player-down.sh` powers the adapter back on;
`aircar-down.sh` does not, so run `bluetoothctl power on` after the last variant. Never run any of
them past Steam's "kick the other session" prompt (CLAUDE.md).
