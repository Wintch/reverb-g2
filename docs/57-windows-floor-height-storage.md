# WMR Floor/Height/Room-Setup Calibration — Read-Only Registry & Filesystem Audit (2026-08-18)

Agent audit of `/mnt/win` (Windows disk, ro) for how Windows persisted the G2's floor/seated/standing calibration. Full agent output preserved below (verbatim key sections).

## Headline findings

1. **This install cannot show native WMR's schema**: Windows 11 build 10.0.26100.9156 (24H2) — Microsoft REMOVED Windows Mixed Reality in 24H2. Mixed Reality Portal is inert leftover; the G2 runs via the third-party **Oasis SteamVR driver** (`driver_oasis.dll`). This explains every empty registry result.
2. `HKCU\Software\Microsoft\Windows\CurrentVersion\Holographic`: exists, **0 subkeys 0 values** (stub, last modified 2026-01-04 = Windows reset date). `HKLM\...\Holographic`: **absent entirely**. Portal's UWP `settings.dat`: placeholder, never written. `LocalState/`: empty.
3. **The real spatial store**: `Users/mrproper/AppData/Local/WindowsHolographicDevices/SpatialStore/HoloLensSensors/{00000000-4321-...}/HeTDb.edb` — 144MB ESE database, actively written (last 2026-08-16 17:47). Schema: 9 generic `DataTable_1_N` tables with `PoseLinksBlob` columns = **spatial-anchor pose graph** (SLAM keyframes). `GlobalPropertiesTable` row: `"1:MostRecentKeyFrames"` → opaque blob. **No Floor/Height scalar anywhere in the schema** — floor is implicit in the pose graph.
4. **The single most useful find — SteamVR chaperone** (`Program Files (x86)/Steam/config/chaperone_info.vrchap`, JSON, the ACTIVE calibration for this rig):
   - `universes[0].play_area = [1.0, 1.0]` m (minimal pro-forma boundary)
   - `collision_bounds`: floor-relative quads, Y ∈ [0, 2.43] (2.43 = SteamVR default wall height, NOT user height)
   - `seated.translation = [-0.182, -0.005, 0.058]` m, `seated.yaw = -0.570` rad (≈ -32.7°)
   - `standing.translation = [-0.543, **1.2128**, -0.157]` m, `standing.yaw = -0.811` rad (≈ -46.4°)
   - `time = "Sun Aug 16 09:11:17 2026"` (last Room Setup run)
   - **`standing.translation.y = 1.2128 m` is the closest thing to a "floor offset" on the entire install** — a derived origin offset computed during Room Setup, not a stored user-height scalar.
5. `steamvr.vrsettings` → `driver_oasis.root_anchor_guid = {92B5EBB4-EF7C-48ED-836F-33C663939DB7}` links chaperone to the anchor DB; `root_anchor_origin_* = 0,0,0` (identity); `driver_holographic.enable = false`.
6. **Explicit "user height in meters": NOT FOUND anywhere** — not in registry, not in the spatial store schema, not in SteamVR config. Windows-family runtimes model height as a derived floor-relative origin offset, with seated and standing as INDEPENDENT named reference poses.

## Schema recommendation (mirror for Linux per-profile config)

```json
{
  "schema_version": 1,
  "profile_id": "<user/profile key>",
  "device": { "model": "HP Reverb G2", "serial": "<opaque id>" },
  "calibration": {
    "last_run_utc": "...",
    "seated":   { "origin_translation_m": [0,0,0], "origin_yaw_rad": 0.0 },
    "standing": { "origin_translation_m": [0,0,0], "origin_yaw_rad": 0.0, "floor_offset_m": 0.0 },
    "boundary": { "play_area_m": [0,0], "polygon_m": [], "wall_height_m": 2.43 }
  },
  "anchor_ref": "<opaque, optional>"
}
```

Design points: (1) seated/standing independent named poses, not one shared floor height; (2) boundary = floor-relative polygon + cosmetic wall height; (3) `floor_offset_m` is the only real "height" concept, derived not stored; (4) timestamp + version — blobs are regenerated whole per Room Setup, not patched.

## Open questions (need live boot / out of scope offline)

1. Native pre-24H2 WMR schema (whether an explicit FloorHeight/UserHeight DWORD ever existed) — unknowable from this disk; would need an older Windows install or archival docs.
2. Whether `standing.y = 1.2128` tracks actual user height vs. arbitrary tracking-init point — confirm by re-running Room Setup live while measuring eye height, then diff `chaperone_info.vrchap`.
3. Why `ProgramData\WindowsHolographicDevices` appeared 2026-08-13→16 but stayed empty (ProcMon on a live SteamVR/Oasis launch).
4. `PoseLinksBlob` binary format — deliberately not attempted (proprietary, low reward).
5. SteamVR 2.16.7 sourced from docs/31 (2026-08-13), not re-verified.

## Method notes (for reuse)

- No hivex/chntpw installed, no passwordless sudo. Workarounds: **regipy 6.3.0** in a venv (pure-Python hive parser, no root) for NTUSER.DAT/SYSTEM/targeted SOFTWARE lookups; **libesedb-utils** fetched via `apt-get download` + `dpkg-deb -x` into a local dir with `LD_LIBRARY_PATH` for the ESE database.
- Full recursive walk of the 111MB SOFTWARE hive is too slow in pure Python — use targeted `hive.get_key(path)` lookups instead.
- Per docs/26: never use raw `strings` for registry value extraction (false negatives) — real parsers only.
