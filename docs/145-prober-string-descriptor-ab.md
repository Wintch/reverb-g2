# 145 — Pre-publish tests of the prober string-descriptor fix (2026-10-11)

Fix under test: `6eedc6cf8` "d/wmr, d/hdk: Treat a positive string descriptor length as success"
(branch `prober-string-descriptor-length` on Wintch/monado, on upstream `main` `13b5c134b`).
Regression it fixes: `b0b1d8b1b` ("drivers: fix dead stores", Simon Zeni, !2985) checks
`xrt_prober_get_string_descriptor() != 0`, but the function returns the string length, so every
successful lookup counts as a failure. Found on 2026-10-10 (docs/143); opened as MR !3036 on 2026-10-11. MR text: `notify-drafts/04`
in the everyday checkout (outside this repo).

Rule followed: test before upstreaming (wait overnight, re-review, re-run the evidence on the
exact commit). Everything below was measured on the exact two commits, nothing on a derived branch.

## 1. Static re-review

- Upstream `main` still `13b5c134b` (0 new commits since the fix was written).
- No open upstream MR (!3000..!3035) touches either line; the fix merges cleanly with our open
  MRs !2967/2968/2969/2971/3004/3020.
- Callers of `xrt_prober_get_string_descriptor()` on `main`: only `wmr_prober.c`
  `wmr_create_bt_controller()` and `hdk_prober.c` `hdk_found()` use `!= 0`; every other caller uses
  `<= 0` or `< 0`. The fix covers all of them.
- Return paths: libusb returns `libusb_get_string_descriptor_ascii()`'s length (`p_libusb.c`),
  the Bluetooth path the `snprintf` length (`p_prober.c`).
- The HDK hunk came from wallbraker's !2985 review suggestion (2026-09-20, `hdk_prober.c:42`),
  so the MR cc's @bl4ckb0ne (author) and @wallbraker.
- `clang-format` 23.1.3 with Monado's `.clang-format`: no change on either line.

## 2. HDK, emulated (everyday box, no HDK hardware exists here)

`scripts/prober-ab/hdk-gadget.sh` (root) builds a virtual OSVR HDK with `dummy_hcd` + a configfs
gadget: VID:PID 1532:0b00, product "OSVR HDK 2", CDC ACM on interfaces 0/1, HID on interface 2
(the one `hdk_found()` opens), 32-byte vendor reports fed at 100 Hz (version 3, identity quaternion).
The xr-hardware udev rule (`70-xrhardware.rules`) gives the user access without changes.
`monado-cli test` from a minimal HDK-only build of each commit (`scripts/prober-ab/run-ab.sh`):

| Build | Result |
|---|---|
| `13b5c134b` | `ERROR [hdk_found] xrt_prober_get_string_descriptor failed: 10`; head = Simulated HMD |
| `6eedc6cf8` | `Found at least the tracker of some HDK (OSVR HDK 2)`; head = `OSVR HDK-family Device` |

10 = strlen("OSVR HDK 2"). Both arms also log 9x `p_dev_get_usb_dev ... same address but different
vendor and product` for the Logitech Unifying receiver 046d:c534 and its 4023/4091 children:
pre-existing prober noise on the everyday box, unrelated.

## 3. WMR on the real G2 (iashur, desk, no wearer)

Builds: one worktree `~/vr/monado-prober`, `RelWithDebInfo`, `scripts/prober-ab/build-service.sh`; both
`monado-service` binaries 0 warnings (sha256 main `b4745b8af0f4895c…`, fix `9321509d2c371d54…`).
Legs run with `scripts/hare-ware-ab/ab-run.sh` (`up 1 ctrl`, WMR_SLAM=0), controllers on the host
UB500 Plus (`AB_TRANSPORT=bt`). Kernel 6.12.111, NVIDIA 595.71.05, BlueZ 5.82.

| Leg | Build | Controllers | Result | Log base (`~/vr/logs/`) |
|---|---|---|---|---|
| A | main | on (host BT) | `ERROR [wmr_create_bt_controller] Failed to get WMR Bluetooth controller string descriptor` -> `XRT_ERROR_DEVICE_CREATION_FAILED`, 3/3 launcher attempts | `ab-PA2-main-bt-20261011-092511` (and `ab-PA-main-bt-20261011-091913`, same 3/3) |
| B | fix | on (host BT) | `Using builder wmr`, both `HP Reverb G2 Left/Right Controller` created (fw blocks + 32-LED calibration read), 4320x2160@90, ran 60 s, clean SIGTERM | `ab-PB2-fix-bt-20261011-092320` (status=ok) |
| C | fix | off | headset only, 4320x2160@90, ran 45 s, no errors | `ab-PC-fix-noctrl-20261011-093753` |
| D | main | off | same as C (control: main without host-BT controllers is fine) | `ab-PD-main-noctrl-20261011-093912` |

C and D are labelled `void` by ab-run.sh only because its tracking criteria need controllers.
The only warning in B/C/D is Vulkan's `Duplicate extension VK_KHR_get_surface_capabilities2`.

## 4. Side findings

- **Comm truncation trap (our tooling).** The first B leg (`ab-PB-fix-bt-20261011-092106`) was
  reported as "found 0 monado-service": the binaries were named `monado-service-main/-fix`, the
  kernel truncates comm to 15 chars (`monado-service-`), and every `pgrep -x` / `/proc/*/comm`
  check missed them. Four orphans (3 from leg A, 1 from B, the latter holding the DRM lease) were
  killed by PID. Fix: variants live in `~/vr/monado-prober-bin/{main,fix}/monado-service`.
- **Upstream `main` does not exit after a failed system init.** In leg A each failed
  `monado-service` (`ipc_server_main_common ... XRT_ERROR_DEVICE_CREATION_FAILED`) stayed alive
  for minutes until killed (the launcher's SIGKILL in the second run). Not investigated; separate
  from this fix.

## Not covered

- Real OSVR HDK hardware (emulation only covers the prober path, not the tracker).
- WMR controllers tunnelled through the headset: ours stay bonded to the UB500 by decision, and
  that path never calls `wmr_create_bt_controller()`.
