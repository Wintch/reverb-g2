# 78 — RAM-vs-cache decision checklist for tonight's 3 demo titles

**Scope**: operational checklist only, not a research essay. Answers, per title, whether
to prewarm Aircar (1073390), Dreams of Dali (591360), Hellblade: Senua's Sacrifice VR
Edition (747350) with `vr-prewarm.sh`'s `cache` or `ram` mode tonight — by measuring, not
by assuming. The project's own record already proved "RAM is always faster" false
(`vr-prewarm.sh`'s header: Aircar's load got faster under `ram` mode, Quake II RTX's
load got 2-3x **slower** under it, same rig, same script). Nothing below overrides that:
every title gets its own A/B before it gets a default.

## 0. One correction to the brief before the checklist

The task framing assumed none of the 3 titles have been RAM-mode tested. That's true for
**Dreams of Dali and Hellblade**, but **not for Aircar** — it already has a real
measurement (`vr-prewarm.sh` header + `NEXT-STEP.md` 2026-08-24/T246 follow-up): `ram`
mode's load-transition window hit 51 fps vs `cache` mode's 24 fps dip, and reached steady
90 fps one whole 2s window sooner. Tonight's Aircar job is **confirm-and-reuse**, not a
first test — no need to re-litigate it, a single spot-check is enough.

## 1. Storage facts on this rig, checked live just now (2026-08-26)

| Path | Filesystem | Device | Used / Total | Free |
|---|---|---|---|---|
| `/` (Aircar lives here) | ext4 (LVM) | `/dev/mapper/iashur--vg-root` | 148G/207G (76%) | 49G |
| `/mnt/win5` (Dali + Hellblade live here) | NTFS | `/dev/nvme0n1p5` | 498G/788G (64%) | 291G |
| `/mnt/videos` | NTFS | `/dev/nvme0n1p4` | 378G/586G (65%) | 209G |
| `/mnt/vrtmp` (ram-mode's tmpfs staging area) | tmpfs (RAM) | — | 8.2M/20G | 20G |

**`/mnt/win5` and `/mnt/videos` are two partitions of the SAME physical drive** — the
Kingston `SNVS2000G` (NV1-family, DRAM-less QLC) flagged in `docs/74` for two firsthand
silent-corruption incidents and a measured SLC-cache-exhaustion cliff (~350→~20MB/s on a
sustained copy). Both Dali and Hellblade's Steam library sits on this drive.

## 2. Kingston fill-risk — explicit check, not skipped

- **`ram` mode does NOT add fill risk by itself.** It reads FROM the Kingston drive and
  writes TO `/mnt/vrtmp` (tmpfs, i.e. RAM) — a one-way copy off the flaky drive, not onto
  it. Tonight's ram-mode tests cannot push `win5`/`videos` closer to full.
- **The real risk tonight is only if something else writes heavily to that same physical
  drive during the session** — a fresh install/reinstall/download of Dali, Hellblade, or
  anything else onto `win5` or `videos`. Both partitions currently have healthy headroom
  (291G and 209G free respectively, well over the 10-20% floor `docs/74` sets) — there is
  no live risk right now, but re-check `df -h /mnt/win5 /mnt/videos` before and after any
  install step tonight, not just before the RAM/cache tests.
- **`--restore` writes back to the Kingston drive** (moves the SSD backup back into
  place) but never grows it past its original size — the swap is symmetric. Still, always
  run `--restore` before ending the session (step 5) so nothing is left mid-swap.
- Per `docs/74`: don't trust a plain size/existence check after any copy involving this
  drive. If a reinstall is needed tonight, verify with `rsync -av --checksum` or a
  `sha256sum` manifest, not just `du -sh`.

## 3. Per-title table

| | Aircar (1073390) | Dreams of Dali (591360) | Hellblade (747350) |
|---|---|---|---|
| **(a) RAM-tested before?** | **Yes** (T246 + 2026-08-25 swap/restore round-trip) — `ram` helped load | **No** — no record anywhere | **No** — no record anywhere, and **structurally can't be** without a deliberate script change (see below) |
| **(b) Install size** | 852 MB (`SizeOnDisk` 892,980,026 B) | 1.4 GB (`SizeOnDisk` 1,477,508,504 B) | 24 GB (`SizeOnDisk` 24,747,009,205 B) |
| **(b) Drive / library** | `/home/iam/.steam/debian-installation/steamapps/common/Aircar` → root ext4 (`iashur-vg-root`), **not** the Kingston drive | `/mnt/win5/SteamLibrary/steamapps/common/DreamsOfDali` → Kingston `SNVS2000G` (`nvme0n1p5`) | `/mnt/win5/SteamLibrary/steamapps/common/Hellblade Senua's Sacrifice - VR` → same Kingston drive |
| **ram-mode eligible?** | Yes (852M ≪ 16G cap) | Yes (1.4G ≪ 16G cap) | **No — 24G > `vr-prewarm.sh`'s hardcoded 16G `RAM_SIZE_LIMIT_BYTES`.** `--mode ram` refuses outright, doesn't even check tmpfs free space. Don't raise the cap tonight to force it through — that's a deliberate maintainer decision (it was raised once before, 2026-08-25, on purpose, after the 32G RAM upgrade), not a demo-night workaround. |

Note on Aircar: a **stale, older copy** of the manifest+dir also sits at
`/mnt/win5/SteamLibrary/steamapps/common/Aircar` (mtime 2026-08-13, vs. the active one's
2026-08-24) — it is **not** in that library's `apps` list in `libraryfolders.vdf`, so
Steam and `vr-prewarm.sh` both resolve to the correct, active, root-partition copy
automatically (its numeric-appid resolution checks the base `steamapps` dir first). No
action needed, just don't manually point anything at the win5 copy by hand.

## 4. Exact commands

### Aircar — confirm-and-reuse (already has a `bench-launcher.py` target)

```bash
cd /home/iam/Documents/reverb-g2/scripts

# cache arm (bench-launcher's default prewarm)
python3 bench-launcher.py aircar --tracking 6dof

# ram arm
python3 bench-launcher.py aircar --tracking 6dof --prewarm-ram
```
Both already log an `app-fps.sh`-style delivered-frame rate; a single spot-check pair is
enough given the existing T246 result — don't spend tonight's time re-deriving it from
scratch.

### Dreams of Dali and Hellblade — no `bench-launcher.py` target for either, so drive
`vr-prewarm.sh` + `jack-in-wayland.sh` + Steam + `app-fps.sh` by hand. **Both are
first-look titles for this rig's automation — expect to need a human wearing the headset
to get past any intro/menu**, the same pattern Cyberpilot and Hellblade's own first
attempt (T243-night) already established for new titles.

```bash
cd /home/iam/Documents/reverb-g2/scripts
APPID=591360   # or 747350 for Hellblade

# 0. sanity: nothing already swapped from a previous session
./vr-prewarm.sh --status

# 1. ARM A — cache mode
./vr-prewarm.sh $APPID --dry-run          # confirm the plan first
./vr-prewarm.sh $APPID                    # cache mode is the default
export U_PACING_APP_LOG=debug             # app-fps.sh needs this on the SERVICE
./jack-in-wayland.sh up 1 3dof            # match tonight's real tracking mode, not just 3dof
steam -applaunch $APPID
# human puts the headset on, gets past any splash/menu
./app-fps.sh 2 10 ~/vr/jack-in-wayland.log   # 2s windows x10, from launch
./jack-in-wayland.sh down

# 2. ARM B — ram mode (SKIP for Hellblade: refused, see table above; run the dry-run
#    anyway to see the refusal message and confirm the cap, then stop there)
./vr-prewarm.sh $APPID --mode ram --dry-run
./vr-prewarm.sh $APPID --mode ram
export U_PACING_APP_LOG=debug
./jack-in-wayland.sh up 1 3dof
steam -applaunch $APPID
./app-fps.sh 2 10 ~/vr/jack-in-wayland.log
./jack-in-wayland.sh down
./vr-prewarm.sh $APPID --restore          # put it back on the Kingston drive, always
```

For Hellblade specifically, step 2 becomes just:
```bash
./vr-prewarm.sh 747350 --mode ram --dry-run
# expected: "'Hellblade...' is 24G -- over the 16G ram-mode safety limit. Refusing."
```
then stop — there is no ram arm to measure for this title tonight, only cache-vs-baseline.

## 5. What to actually measure (per the Aircar precedent — not "turn RAM mode on and move on")

For each arm, capture **both** of these, not fps alone (Quake II RTX's regression was
invisible in steady-state fps and only showed up in total launch time):

1. **`app-fps.sh`'s early 2s windows** — the load-transition dip and how many windows it
   takes to reach the title's own known steady ceiling (Aircar: 90 fps; Hellblade's first
   look already measured a **45 fps** ceiling, not 90 — compare against each title's own
   number from `docs/23`, don't assume 90 across the board; Dali has no prior ceiling on
   record, so its first cache-mode run establishes the baseline the ram-mode run gets
   compared against).
2. **Wall-clock from `steam -applaunch` to the first `Delivered frame` / `BEGIN_SESSION`
   line** in `~/vr/jack-in-wayland.log` — the thing that caught Quake II RTX's regression
   even though its steady fps was identical either way.

**Decision rule**: keep `ram` mode as the default launch prewarm for a title only if its
ram-arm numbers are clearly better on *both* measures (or clearly better on one with no
regression on the other) than the cache arm, reproduced at least once. If either measure
is worse under `ram` (Quake II RTX's shape) or the two arms are within noise of each
other, default that title to `cache` mode instead — a "maybe" is not a reason to pay
`ram` mode's extra rsync-and-symlink complexity for nothing.

## 6. Close-out, every session

```bash
./vr-prewarm.sh --status        # confirm nothing left ram-swapped
df -h /mnt/win5 /mnt/videos     # confirm the Kingston drive's free space didn't move
```
If `--status` shows an active swap for a title you're done testing, `--restore` it before
moving to the next title or ending the session — don't leave a demo title running off
tmpfs into tonight's actual audience-facing run unless that arm is the one you deliberately
decided to keep.
