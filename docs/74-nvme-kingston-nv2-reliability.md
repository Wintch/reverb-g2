# 74 — Kingston NV1/NV2-family NVMe reliability research (data-storage drive, NOT the G2)

**Scope note, read first:** this document is about a general-purpose data-storage NVMe
drive in the same physical machine as the Reverb G2 lab — it has nothing to do with the
headset, Monado, or 90Hz. It lives in this repo because this repo is where the machine's
hardware findings get written down, and because one of its mounts (`/mnt/videos`) is the
active DaVinci Resolve media-storage path referenced from `resolve-linux/PERFORMANCE.md`.
Don't confuse this with any HMD/USB/DP finding elsewhere in `docs/`.

## The drive, and what's on it

- **Model as reported by this system**: `Kingston SNVS2000G`
- **Firmware**: `S8442105`
- Holds three NTFS partitions: `/mnt/win3`, `/mnt/win5`, `/mnt/videos` — game libraries and
  video-editing media storage. `/mnt/videos` is the Media Storage path for the DaVinci
  Resolve setup documented in the separate `resolve-linux` repo.

### Important correction found during this research: the model number says NV1, not NV2

The task that produced this document described the drive as "the Kingston NV2 series, 2TB
variant." **That label does not match Kingston's own part-numbering convention**, and this
is worth flagging plainly rather than quietly going along with the framing, per this
project's own standing rule about correcting course when evidence disagrees.

Cross-checked against Kingston's part-number decoder and multiple retail listings:

- Kingston's **NV1** line uses the part-number prefix **`SNVS`** (e.g. `SNVS/250G`,
  `SNVS/1000G`, `SNVS/2000G` — the 2TB NV1 is listed on Amazon as "Kingston NV1 2TB ...
  SNVS-2000G").
- Kingston's **NV2** line uses the prefix **`SNV2S`** (e.g. `SNV2S/250G`, `SNV2S/2000G` —
  the 2TB NV2 shows up on eBay as "Kingston NV2 2TB M.2 NVMe Internal SSD (SNV2S/2000G)").
- The firmware revision `S8442105` also turned up independently as a documented **NV1
  (`SNVS`)** firmware release, not an NV2 one.

Both facts point the same direction: **this drive's own model number and firmware string
identify it as a Kingston NV1 2TB (`SNVS2000G`), not an NV2.** This document was
researched with that correction in mind — the sections below cover NV1-specific findings
where available, and separately cover the NV2 controversy (which is real, well-documented,
and worth knowing) because the two drives are frequently confused with each other even in
retail listings and reviews, share the same DRAM-less philosophy, and because it's possible
the physical drive could still turn out to be an NV2 if the reported model string is
somehow a mislabel — that has not been independently re-verified on this machine as part of
this research pass (would need `nvme id-ctrl` / `smartctl -a` output, which this task did
not run). **Treat "NV1" as the best-evidence identification, not a 100%-certain one.**

## The user's firsthand incident history

The user (owner of this machine) reports, from direct personal experience:

1. **He has personally experienced silent data corruption on this exact drive before**, and
   separately, **on another drive too** (a different unit — this is not a one-off he's
   generalizing from a single bad experience, he's seen the failure mode at least twice on
   two different pieces of hardware).
2. Silent means: **no error was thrown at the time**, and the corruption was only
   discovered later when the data itself came out wrong.
3. His own standing belief, stated plainly: **"if it fills up, it can corrupt data."**
4. During a large sustained copy today (~185GB), throughput dropped from **~350MB/s to
   ~20MB/s** partway through the transfer — consistent with SLC-cache exhaustion on a
   DRAM-less QLC drive: once the fast pseudo-SLC write cache fills, the drive falls back to
   writing directly to native QLC NAND, which is much slower.

None of this is independently re-measured in this document — it's recorded as the user's
own direct experience, which per this project's methodology carries real weight (see
`CLAUDE.md`, "measurements matter more than opinions," and the project's own history of
silent-corruption-shaped false positives elsewhere in the hardware stack).

## Research findings

### 1. General design: DRAM-less, QLC, Host Memory Buffer

Both the NV1 and NV2 are budget drives built the same way: **no onboard DRAM cache**, and
**QLC (4-bit-per-cell) NAND** in most sold units (Kingston's own materials and reviewers
independently confirm QLC for the mainstream capacities of both lines). Being DRAM-less
means the drive relies on **HMB (Host Memory Buffer)** — the controller borrows a small
slice of the *host's* system RAM over the NVMe protocol to hold its flash-translation-layer
mapping table, instead of having dedicated onboard DRAM for it. This is normal, standard,
and not itself a defect — plenty of budget drives from every vendor do this — but it does
have real consequences: it makes the drive's effective performance and its FTL bookkeeping
speed dependent on the host exposing HMB correctly and on how much RAM the host is willing
to lend, and it puts the FTL metadata itself in the same at-risk category as any other data
if that memory or the write path is disturbed mid-update (unlike a drive with a dedicated,
often power-loss-protected, onboard DRAM+capacitor pairing).

QLC's tradeoffs versus TLC (used in most non-budget drives): lower endurance per cell (more
voltage states per cell = narrower noise margins = shorter useful life and worse data
retention over time), and once the drive's fast pseudo-SLC write cache is exhausted, a
larger relative speed cliff down to native (quarter-speed-class) NAND write speed.

Sources:
- [Kingston NV2 1 TB M.2 NVMe SSD Review — TechPowerUp](https://www.techpowerup.com/review/kingston-nv2-1-tb-m-2-nvme-ssd/)
- [Kingston NV2 SSD Review: Cheap But Risky — Tom's Hardware](https://www.tomshardware.com/reviews/kingston-nv2-ssd)
- [PSA: Kingston NV1 SSD Comes with a Hardware Spec Lottery — TechPowerUp](https://www.techpowerup.com/290339/psa-kingston-nv1-ssd-comes-with-a-hardware-spec-lottery-tlc-or-qlc-smi-or-phison)

### 2. The "component-swap" controversies — real, and there are TWO of them, on two different drives

**NV1 (this drive's actual family, best evidence)**: launched March 2021. Kingston shipped
units with **either** a Silicon Motion SM2263XT **or** a Phison PS5013-E13T controller, and
**either** TLC **or** QLC NAND, all under the same SKU, with no way for a buyer to know
which combination they'd get. TechPowerUp's verdict at the time: *"The component-swap
business is terrible for the end-user because there's no way to know what product you have
purchased... that's not how people are convinced they should trust a company with their
important data."* Reviewers measured the 1TB NV1's endurance at only **240 TBW**, worse
than the already-criticized Crucial P2 (300 TBW), and ServeTheHome concluded the low
endurance "does not inspire confidence in the long-term reliability of this drive."

**NV2 (the adjacent, later, more widely-discussed controversy — 2023)**: Kingston shipped
the NV2 with **at least four different controllers** depending on production batch (variants
of Silicon Motion SM2267XT/SM2269XT and Phison E21T-family silicon have all been reported
in NV2 units), again under one unchanged model number. One NV2 variant (the Phison **E21T**
controller) **shares its controller silicon** with a family of M.2-2230 drives (Sabrent
Rocket 2230, Corsair MP600 Mini) in which PCPartPicker discovered, in **July 2023**, a
**reproducible permanent data-loss bug**: data written without any reported error became
permanently unreadable, specifically at PCIe 4.0 link speeds, specifically on **1TB, 2230
form-factor** drives. Phison acknowledged the issue; Corsair and other vendors shipped fixed
firmware (e.g. Corsair `ELFMB0.7`, Inland `EFLBM0.7`) that PCPartPicker validated as
resolving it.

**What does NOT hold up**: PCPartPicker explicitly did **not** reproduce that specific bug
on 2280-form-factor drives like the NV2 — so while the NV2 uses closely related controller
silicon and the story is often summarized online as "Kingston NV2 had a data-loss bug," the
precise, confirmed bug was on a different form factor and (per available public info)
capacity than the mainstream 2TB NV2. Treat "the NV2 had the exact same PCPartPicker bug"
as **overstated** — the honest state of the evidence is "adjacent silicon family, bug
confirmed on a different physical drive, not confirmed on the NV2 itself."

Sources:
- [PSA: Kingston NV1 SSD Comes with a Hardware Spec Lottery — TechPowerUp](https://www.techpowerup.com/290339/psa-kingston-nv1-ssd-comes-with-a-hardware-spec-lottery-tlc-or-qlc-smi-or-phison)
- [Kingston NV1 1 TB Review — Value & Conclusion — TechPowerUp](https://www.techpowerup.com/review/kingston-nv1-1-tb/17.html)
- [Kingston NV1 1TB NVMe SSD Review — ServeTheHome](https://www.servethehome.com/kingston-nv1-1tb-nvme-ssd-review/)
- [Is the Kingston NV2 really that bad? — PCPartPicker forums](https://pcpartpicker.com/forums/topic/445796-is-the-kingston-nv2-really-that-bad)
- [Reproducible permanent data loss on Phison E21T-based 1TB M.2-2230 SSDs — PCPartPicker forums](https://pcpartpicker.com/forums/topic/429279-reproducible-permanent-data-loss-on-phison-e21t-based-1-tb-m2-2230-ssds)
- [Kingston NV2 SSD Review: Cheap But Risky — Tom's Hardware](https://www.tomshardware.com/reviews/kingston-nv2-ssd)

### 3. Direct corruption reports for this drive family — thin, real, but not "widely documented"

**Honest calibration up front**: there is no large, authoritative, vendor-acknowledged
corruption advisory specific to NV1 or NV2 (unlike the specific, acknowledged, fixed
PCPartPicker/Phison E21T bug above, which *is* well-documented but on different hardware).
What exists is a smaller set of **credible individual reports**, which is a different and
weaker evidentiary category — recorded here honestly as such, not inflated.

- **A direct, detailed report matching this project's own symptom shape**: a user on
  EEVblog's forum reports a **Kingston NV2 1TB**, used as an external USB backup/transfer
  drive, **silently lost its contents twice** after being disconnected/unpowered for 3-6
  months at a time. On reconnection the drive reported as partially full by capacity but
  contained **no accessible files** — Windows `chkdsk` reported the drive as 100% free, with
  **no error messages, no filesystem corruption warnings, nothing** — just files that were
  "simply gone." The drive remained fully writable afterward and data could be re-copied
  successfully. No definitive root cause was established in the thread; candidates raised
  by forum members included QLC's known-poor unpowered data retention, the specific
  external-enclosure controller (RTL9210) rather than the SSD itself, and the SSD firmware
  silently "repairing" its own filesystem-adjacent metadata without telling the user. **This
  is anecdotal, single-user, unconfirmed — but it is a real, silent, no-error corruption
  report on this exact drive family, independent of the user's own two incidents.**
- **A Tom's Hardware forum thread** ("Is my Kingston NV2 Dying?") describes a 2TB NV2 used
  as a secondary game drive whose usage jumped erratically and which threw disk-usage
  anomalies during transfers/updates after ~7 months — read as **possible early failure**,
  not confirmed as corruption specifically, and not resolved with a root cause in the
  visible thread content. Weak evidence, noted for completeness.
- A general-forum mention of **SFC (System File Checker) finding corrupted, unrepairable
  files** on some NV2 drives, and a broader pattern of complaints "affecting multiple NVMe
  brands including Lexar, Kingston, and Samsung," which suggests at least part of the wider
  online corruption narrative around budget NVMe drives is not brand- or model-specific at
  all — worth keeping in mind before pinning every complaint on Kingston specifically.

**Verdict on this section, stated plainly**: no widely-documented, vendor-acknowledged
corruption advisory for NV1/NV2 as a class was found. What was found is a handful of
credible anecdotal reports of exactly the failure shape the user describes (silent, no
error thrown, discovered later) — thin evidence in volume, but directionally consistent
with the user's own two firsthand incidents and with this drive class's inherent design
weaknesses (QLC retention, DRAM-less FTL metadata handling, HMB dependence). Don't
overstate it as "this model is documented to corrupt data" — the honest framing is "this
model's design is more exposed to silent corruption than a mainstream TLC+DRAM drive, and
there are real (if sparse) field reports of exactly that happening on it."

Sources:
- [Kingston NV2 PCIe 4.0 NVMe M.2 lost its contents twice — EEVblog forum](https://www.eevblog.com/forum/general-computing/kingston-nv2-pcie-4-0-nvme-m-2-lost-its-contents-twice/)
- [Is my Kingston NV2 Dying? — Tom's Hardware forum](https://forums.tomshardware.com/threads/is-my-kingston-nv2-dying.3827371/)

### 4. Firmware history

The firmware on this specific drive, `S8442105`, independently surfaced in research as a
documented **NV1 (`SNVS`)** firmware release — consistent with the model-number correction
in the section above, and additional (weak but consistent) evidence that this is genuinely
an NV1, not an NV2. No detailed, dated release-note text could be retrieved directly (the
Kingston support pages and the third-party manuals-mirror site both returned HTTP 403 to
automated fetches during this research), so **this document cannot confirm whether a newer
firmware exists, or what specifically `S8442105` fixes relative to older/newer revisions.**

**Practical, honest recommendation given that gap**: don't take this document's word for
firmware currency either way. Check directly via **Kingston SSD Manager (KSM)**
(`kingston.com/ssdmanager` — Kingston's own tool for SMART health and firmware updates on
their consumer SSDs) the next time this drive is examined, and update this section with
whatever KSM actually reports (current version, whether an update is offered, and its
release notes) rather than relying on secondhand search results.

Sources:
- [Kingston® SSD Manager — SSD health and firmware application](https://www.kingston.com/en/support/technical/ssdmanager)
- [SSD Firmware Update — Kingston Technology](https://www.kingston.com/en/support/technical/ksm-firmware-update)

### 5. General SSD engineering: why running near-full increases corruption/reliability risk

This part is general NAND/SSD engineering knowledge, **not specific to this model** — kept
separate on purpose so it isn't mistaken for a Kingston-specific finding.

- SSDs need free physical NAND blocks to perform **garbage collection** (consolidating
  still-valid data out of partially-stale blocks so the stale portion can be erased and
  reused) and **wear leveling**. When the drive is nearly full, the controller has very
  little slack to do this work in the background/idle; garbage collection increasingly has
  to run **in-line with incoming writes**, which is when performance falls off a cliff *and*
  when the controller's bookkeeping is under the most time pressure.
- This is measured by **write amplification** (WA) — the ratio of actual NAND writes
  (including internal data-shuffling from garbage collection) to the writes the host asked
  for. A drive with plenty of free space keeps WA low; a nearly-full drive under sustained
  write load pushes WA up, which both accelerates wear and increases the number of
  in-flight, not-yet-fully-committed internal operations at any given moment.
- **Over-provisioning** (reserving a slice of raw NAND capacity that never appears in the
  drive's advertised usable size, specifically to give garbage collection room to work) is
  the standard mitigation manufacturers build in — but a DRAM-less, HMB-dependent, QLC
  budget drive has less margin in every one of these dimensions (mapping-table cache size,
  spare-area ratio, per-cell endurance) than a mainstream TLC+DRAM drive, so the same
  near-full condition costs it more.
- None of this is a proof that near-full capacity *causes* silent corruption specifically
  on this drive — it's the general mechanism by which manufacturers across the industry
  justify the standard "keep 10-20% free" guidance, and it's a plausible contributing factor
  consistent with the user's own stated belief and this drive's specific design weaknesses
  (thin FTL-metadata margin, QLC retention, no capacitor-backed power-loss protection on a
  budget drive of this class).

Sources:
- [Understanding SSD endurance: Garbage Collection to TRIM explained — ATP Inc.](https://www.atpinc.com/blog/trim-garbage-collection-ssd-endurance-wai-waf)
- [Garbage Collection in Industrial SSDs: What You Need to Know — ADATA Industrial](https://industrial.adata.com/en/edm/garbage-collection-in-industrial-ssd)
- [Garbage Collection Techniques in Solid-State Drives (SSDs) — ACM Computing Surveys](https://dl.acm.org/doi/10.1145/3816041)

## Practical implication / standing rule

Given (a) the user's own two firsthand silent-corruption incidents, (b) this drive's
DRAM-less + QLC + HMB design being inherently thinner-margined than a mainstream drive,
(c) real if sparse field reports of exactly this failure shape on the NV1/NV2 family, and
(d) the observed SLC-cache-exhaustion throughput cliff (~350→~20MB/s) on a large sustained
copy today:

1. **Never let any partition on this drive approach full.** Keep meaningful headroom
   (industry-standard guidance is roughly 10-20% free at minimum; treat that as a floor, not
   a target, given this drive's specific weaknesses).
2. **A plain file-size match after a copy does NOT rule out silent corruption.** Every
   incident described above — the user's own and the EEVblog report — passed a naive
   "does the file exist and is it the right size" check right up until the content itself
   was examined. For anything valuable moved on or off this drive, prefer an actual
   checksum verification pass:
   - `rsync -av --checksum SRC/ DST/` (forces a full content checksum comparison instead of
     trusting size+mtime), or
   - a `sha256sum` manifest taken before the copy and re-verified against the copy
     afterward.
3. Treat this drive as **not trustworthy as the sole copy of anything irreplaceable** —
   consistent with the general QLC/DRAM-less risk profile and this specific unit's own
   incident history, independent of whether it turns out to be the NV1 or the NV2 once
   verified with `nvme id-ctrl`/`smartctl`.
