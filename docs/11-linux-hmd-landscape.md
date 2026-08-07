# 11 — Landscape: Is It NVIDIA-Only? Is It G2-Only?

**RESOLVED (2026-08-06, afternoon): this entire document is superseded.** The question
driving all the analysis below — "do we need an AMD/Intel GPU to know whether this is
NVIDIA's fault?" — no longer applies: the bug was the NVKMS bpc clamp (`patches/nvidia/0004`),
confirmed and fixed on this same Ampere GPU, without touching any other hardware. The
conclusion that "testing with AMD is the most valuable experiment available" (further below)
**was never carried out and wasn't needed**. The survey is left as-is, as a record of the
investigation — see `docs/19-nvidia-bug-5923212-followup.md` and
`docs/21-project-retrospective.md` for the actual current status.

Survey from 2026-08-04. The question was whether the 90Hz failure is specific to NVIDIA,
to the Reverb G2, or to something bigger. The answer changes who we write to.

## The biggest reframe: NVIDIA has THREE distinct failure signatures

This isn't an isolated bug of ours. On Linux, with NVIDIA, three distinct failures show up
depending on the panel — each with its own internal bug number, all three open:

| headset | symptom | NVIDIA bug |
|---|---|---|
| **WMR / Reverb G1 and G2** | **black panel / HP logo, never locks** | **5923212** |
| Bigscreen Beyond | DSC corruption, "fuzzy static" | 4834531 |
| Valve Index / Vive / Vive Pro | modeset happens, but judder and latency | 5372097 |

And the same family shows up **with no VR involved at all**: a Feb-2026 thread reports the
problem on an ordinary desktop monitor (LG C5 OLED) at 144Hz with VRR.

**Takeaway:** the underlying problem looks like "NVIDIA + Linux + high refresh" in
general, and the G2 simply exposes it in the most severe form — a fully blanked screen
instead of artifacts or judder. That makes our case **the best repro in the family**, not
a niche complaint.

## Is It NVIDIA-Only? We Don't Know, and We Should Say So

**There is not a single human report, with physical verification, of a Reverb G2 at 90Hz
on Linux with ANY GPU** — not NVIDIA, not AMD, not Intel.

- The LVRA wiki says Intel Arc / i915 works "OK" with the G2, but **doesn't specify Hz**.
  It could be 60, same as us.
- On AMD with the G2: **total blind spot**. Nobody has reported it working or failing.

That's *absence of evidence*, not evidence in favor of AMD/Intel. When we write it up,
the correct phrasing is "nobody has reported it," never "it works on AMD."

**But there is solid indirect evidence that amdgpu doesn't forbid high refresh in
direct-mode:** the Valve Index reaches a clean 90 and 120Hz on AMD (RX 7900 XTX), and the
Bigscreen Beyond reaches 90Hz on AMD with community kernel patches. Neither is WMR — the G2
has its own activation sequence that those don't — so it doesn't close the question. But it
does make clear that the Linux stack **can** do high refresh in direct mode.

That's why testing with a borrowed AMD card remains the most valuable experiment
available.

## The Oculus / DK2 Precedent: Weaker Than Expected

The **DK2 did reach its native 75Hz on Linux** (consistent human reports from 2015). But
it's structurally different from the G2 along four axes, and that's why it doesn't serve as
a precedent:

1. **DK2 and CV1 are HDMI, not DisplayPort** (investigated 2026-08-05). This is the most
   important of the four axes, more than the other three combined: HDMI is fixed-clock TMDS,
   with no AUX channel or negotiated link training — it never goes through the kind of
   problem we have (DPCD/bpc/lane-count negotiation). The G2 doesn't have that output: the
   ANX7530 is a native DisplayPort bridge. The Oculus family **avoided** this problem instead
   of solving it.
2. X11 **extended mode**, not direct-mode or a DRM lease.
3. Panel with no WMR-style activation sequence — any GPU that throws a modeline at it
   treats it like just another monitor.
4. Proprietary NVIDIA ~340–352.x on Kepler/Maxwell: **a full generation before** the bug
   we're chasing (Turing/Ampere/Blackwell) — and before the GSP split. Back then mode
   validation lived in the host driver, patchable (hence why
   `Option "ModeValidation" "AllowNonEdidModes"` existed in xorg.conf, see below). With
   595-open that logic migrated into closed GSP firmware — the same wall `docs/13` already
   documented.

Also, those sources describe the setup as "works," without rigorous physical verification.

**CV1 (90Hz) and Rift S (80Hz)** — the two with an activation architecture closest to
WMR — also don't have the problem: CV1 is also HDMI 1.3, and the only "odd" thing is that it
doesn't send a hotplug until a USB command enables it (resolved at the HDMI/HPD layer, not in
DP timing). Neither has a single clean, verified report of native refresh on Linux, **nor of
failing either**. Silence in both directions. Linux support for the whole post-DK2 family is
100% community-driven: Oculus paused its Linux SDK in May 2015 and never picked it back up.

**HTC Vive / Vive Pro:** the original Vive (2016) is also HDMI. DisplayPort only shows up
starting with the Vive Pro (2018), and for the Vive Pro 2 (2021) HTC worked with AMD/NVIDIA
to support **DSC** — no documented case of real MST (independent per-eye streams) was found
in any HMD of this generation, neither Rift nor Vive. The ANX7530's "horizontal line
splitting" feature (see `docs/19`) looks like a generic chip capability, with no precedent of
being used to unlock refresh — it remains a low-priority hypothesis.

**Honest conclusion: the Oculus family doesn't provide a precedent for NVIDIA+Linux
achieving high refresh on an HMD with real DisplayPort negotiation.** The 2014-2018 pattern
was to avoid the problem (HDMI) rather than solve it, and the only trick from that era that
would still apply today (`AllowNonEdidModes`, bypassing mode validation against the EDID)
points to a layer that, under 595-open, is no longer patchable because it lives in closed GSP
firmware. Still, it's free to try — costs nothing and might surprise us.

## HMD Landscape on Linux Today

| HMD | max confirmed refresh | GPU | software |
|---|---|---|---|
| Reverb G1/G2 (WMR) | clean 60Hz; **90Hz fails** | NVIDIA Turing/Ampere/Blackwell | Monado |
| Reverb G1/G2 (WMR) | "OK", **Hz unspecified** | Intel i915 | Monado |
| Reverb G1/G2 (WMR) | **no data** | AMD | — |
| Valve Index / Vive / Vive Pro | **clean 90 and 120Hz** (144 fails, also on Windows) | AMD RX 7900 XTX | SteamVR-Linux |
| Valve Index / Vive / Vive Pro | modeset happens, but judder | NVIDIA | Monado / SteamVR |
| Bigscreen Beyond | clean 90Hz (with kernel patch) | AMD | Monado |
| Bigscreen Beyond | DSC corruption | NVIDIA | Monado |
| Oculus DK2 | clean 75Hz (extended X11, 2015 driver) | NVIDIA Kepler/Maxwell | — |
| Oculus CV1 / Rift S | unconfirmed in either direction | — | OpenHMD / Monado |
| Pimax P2 (4K/5K/8K) | no Hz data; EDID must be patched by hand | NVIDIA | Monado |
| Somnium VR1 | not supported | — | — |

**The only clean case of high refresh on an HMD under Linux is with AMD.**

## Where to Publish, in Order

1. **NVIDIA thread 337744** — `forums.developer.nvidia.com/t/337744`. Has active staff
   (bug 5923212 confirmed) and **one of their questions still unanswered**: whether there's
   an earlier driver version where this didn't happen. **Reply there, don't open a new
   thread.** There's no official template; the convention is to prefix `[Bug Report]` and
   structure it in sections.
   Note: we only tested **595.71.05**. The 590–610 range comes from the thread, not from our
   own measurements — don't attribute it to us.
2. **Monado** — `gitlab.freedesktop.org/monado/monado`. **Must check BY HAND** whether a
   "black screen at 90Hz" issue already exists before opening one: gitlab.freedesktop.org
   sits behind Anubis (anti-bot) and the survey couldn't read it. It's the only active
   project worth joining: Project-VR is a personal diary with no community, `wumbo_mr` is
   archived, and OpenHMD only has detection/firmware issues for the G2.
3. **LVRA / Linux VR Adventures** — wiki + Matrix `#linux-vr-adventures:matrix.org` +
   Discord. It's the right audience: it brings together people from Monado, SteamVR-Linux,
   and WMR/Vive/Index hardware. Its wiki today documents the limit ("60Hz-only on Nvidia")
   **with no technical cause** — that's where our bandwidth measurement and physical
   verification fill a real gap.

**And a contribution of our own with no published precedent:** the physical verification
methodology. Nobody has documented that Vulkan/OpenXR reports success and 90 fps over a black
panel, nor the protocol to avoid that false positive. It's worth publishing in any of the
three venues.

## What We Couldn't Determine

- **gitlab.freedesktop.org sits behind Anubis**: the Monado, AMD (`drm/amd`), and Intel
  (`drm/i915`, `drm/xe`) trackers are blocked. What little of Monado we did read came through
  an indirect proxy — medium confidence, not high.
- Whether a Monado issue for "G2 black screen at 90Hz" already exists. **Neither confirmed
  nor ruled out.**
- Whether Intel i915 reaches 90Hz with the G2 or only 60.
- Whether the Bigscreen Beyond runs clean today on NVIDIA 580+-open (the wiki says
  "requires," with no later human report).
- Whether the Rift S reaches its verified native 80Hz.
