# Next step

State as of 2026-08-05, late. Written from the everyday system with the lab SSD mounted
read-write at `/mnt/lab`, right before rebooting into the lab OS to resume physically.

Same physical machine, two separate Debian 13 installs on separate disks (see
`docs/17-publishing.md` history / the repo's own notes) — the headset does not need to be
unplugged to switch between them, just reboot and pick the lab SSD at the boot menu, log in
as `iam`.

## Two independent tracks right now

1. **The vblank experiment** (`docs/16-lab-vblank.md`) — needs the lab OS booted natively.
   Blocked on an open question, see below.
2. **Monado upstreaming** (`docs/18-monado-upstreaming.md`) — needs nothing from the lab
   machine at all. Blocked on a GitLab account-verification issue on the everyday system's
   side. Do not waste lab time on this.

---

## Track 1 — vblank experiment: what to do first

**Before running PREFLIGHT, read the "PENDIENTE" block near the top of
`docs/16-lab-vblank.md`.** While documenting this session I found and fixed a real error in
that doc: it claimed the EDID-override loading mechanism was "already proven in this lab".
It is not. The 6 bpc bug was closed with a *driver source patch* (0004), which sidestepped
ever needing NVIDIA to accept a fake EDID — so that claim was simply wrong, and following it
would have wasted lab time discovering there is no confirmed way to load the modified EDID.

**So the actual first task on the lab machine is resolving that**, trying in this order
(full detail now in `docs/16`, background in `docs/13`):

1. `/sys/kernel/debug/dri/*/DP-1/edid_override` (debugfs) — cheapest to try. Unconfirmed
   whether NVKMS's closed logic reads EDID through the generic DRM helper (would see this)
   or its own AUX channel (would not). Writing the file does not trigger hotplug — disconnect
   and reconnect the connector after.
2. `nvidia_modeset.config_file` — NVKMS's own mechanism, parameter exists and is compiled in,
   but the dpy-name syntax is undocumented. Discover it with `nvidia_modeset.debug=1` and
   reading dmesg as root during a real modeset.
3. Patching the EDID the headset itself reports over the cable, if there's an injection point
   between the Analogix bridge and the host — unexplored.

If none of the three works, the experiment is inconclusive by this route and needs a
different injection strategy before the factorial itself means anything.

### Once loading works: PREFLIGHT (5 checks, `docs/16`)

1. `grep -o '[0-9]\+\.[0-9]\+\.[0-9]\+' /proc/driver/nvidia/version` → must say `595.71.05`
2. `modinfo nvidia | grep -i license` → must include "Dual MIT/GPL"
3. `./scripts/verify-bpc.sh` → patch present
4. `lsusb | grep -E '04b4:6506|0bda:4c15|03f0:0580|04b4:6504|045e:0659' | wc -l` → must be 5
5. `dmesg | grep 'Notify Attach Begin' | tail -1` → must say `24 bpp`, not `18`

If any of the five fails, stop — measuring on the wrong driver gives a result that looks
good and points at the wrong thing.

### Then the experiment itself

Order: **CTRL → B → A**. If B works, that's the answer and A is just confirmation.
Verification is physical — put the headset on and look; the API reports 90.0 fps success
even with a black panel. For each mode: does the backlight come on, is there color or just
white/flicker, does `dmesg`'s `Notify Attach Begin` line say `24 bpp`, and the HID status
byte 18 (`scripts/decode-status.sh`).

The read-the-result table and the refresh-sweep follow-up are both in `docs/16`.

---

## Track 2 — Monado upstreaming: status

Four MR branches are ready (rebased on Monado `main` `735e29e4e`, adversarially reviewed,
three real defects found and fixed, zero warnings, DCO-signed, no AI co-author trailer per
the standing decision below). They live in the **everyday system's** clone
`~/Documents/linux_vr_base/monado`, refs `wmr-hid-resilience`, `wmr-controller-input-fixes`,
`wmr-camera-stream-toggle`, `steamvr-drv-origin-rpath`. Same content as
`patches/monado/0001–0010` in this repo.

**Blocked on GitLab account verification.** freedesktop.org's GitLab restricts new accounts
(anti-spam): they can't fork or create projects until an admin approves a request.
Filed as **issue #3736**
(`https://gitlab.freedesktop.org/freedesktop/freedesktop/-/work_items/3736`), open, no fixed
SLA. Check for a notification email, or ask to have it checked.

**Once approved:**
1. Add an SSH key to the GitLab account (can generate one in advance, same pattern as the
   lab machine's deploy key).
2. Fork `monado/monado`.
3. Push the four branches from `~/Documents/linux_vr_base/monado` to the fork.
4. Open four MRs against `main`. Titles and bodies are ready to paste, in
   `docs/18-monado-upstreaming.md`.
5. After each MR gets a number, add its `doc/changes/.../mr.<N>.md` changelog fragment as a
   final commit (path convention explained in docs/18).

---

## Pendiente adicional (2026-08-05): perfil de power de la GPU

Hipótesis del usuario, todavía sin correr: en Windows siempre se recomienda forzar el panel
de NVIDIA a **"Prefer Maximum Performance"** para VR — dejarlo en el default ("Adaptive",
reloj dinámico) puede causar problemas. En Linux el 595-open también arranca en PowerMizer
adaptativo por default. Si el firmware GSP cerrado que decide el enganche a 90Hz (ver
`docs/13-bug-6bpc.md`) es sensible al estado de reloj en el momento del modeset, un
downclock en el momento equivocado podría explicar por qué el panel no llega a sincronizar.

No se investigó todavía. Cuando se retome: revisar con `nvidia-smi -q -d PERFORMANCE` o
`nvidia-settings` el P-state real durante el intento de modeset a 90Hz, y probar forzando
máximo rendimiento (`nvidia-settings -a '[gpu:0]/GPUPowerMizerMode=1'` o el mecanismo
equivalente en el 595-open) antes de correr el experimento del vblank o en paralelo con él.

---

## Standing convention decided this session

**No `Co-Authored-By: Claude` trailer on commits, and no repo-level AI disclaimer either.**
The `Signed-off-by` already certifies the content for publication; a tool-attribution note
adds nothing on top of that. Applies going forward to both this repo and the Monado series
(already applied there — the 10 patches and the reverb-g2 history were both rewritten to
drop it, and reverb-g2's rewritten history is already force-pushed to GitHub).

## Repo state

- Renamed `reverb-g2-linux` → **`reverb-g2`** (README explains why: the headset has no
  supported platform left on any OS, not just Linux). Working directory here is already the
  renamed one; GitHub remote is `Wintch/reverb-g2` (private).
- `main` @ `301eaee`, matches GitHub, gate (`scripts/check-publishable.py`) passes clean.
- FCC PDFs dropped from the tree (linked to fccid.io instead); Oasis driver attribution fixed
  (it's Matthieu Bucchianeri's, not HP's); HP Omnicept noted as a related test target in
  `docs/10-resources.md` (same WMR display path per Monado's prober — a 90 Hz result there
  would show whether this is G2-wide or unit-specific) but not being pursued (no hardware).
