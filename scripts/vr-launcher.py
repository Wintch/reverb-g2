#!/usr/bin/env python3
"""vr-launcher.py -- "our own launcher", the single entry point between the boot
selector's OK verdict and something actually running in the headset.

Brings up Monado first (jack-in-wayland.sh), then routes to whichever option was
picked: the 360/VR180 player, or one of the Steam VR titles confirmed working in
docs/23-game-compatibility.md's "Working" table (GAMES below is that table,
copied by hand -- keep them in sync if a game's status there changes). Aircar
stays the timeout default: user's own verdict was "first game I'd call 99%".
The non-Steam option is an honest stub, not built -- nothing non-Steam has been
identified or tested yet, don't fake a working option.

Prerequisite this script does NOT and CANNOT automate: any Steam VR title's
launch options must already be set once via Steam's own UI (Properties ->
Launch Options) -- docs/23's "Trap: Steam launch options edited on disk don't
exist" already established that editing localconfig.vdf directly while Steam
runs is unreliable/dangerous.

  ./scripts/vr-launcher.py [mode] [3dof|6dof|ctrl]   (passed through to jack-in-wayland.sh)
  ./scripts/vr-launcher.py status                    (which Proton game trees are alive)
  ./scripts/vr-launcher.py stop [appid|all]          (stop them for real, via game-stop.py)

Process-state rule (2026-08-21, T244 close; docs/06, NEXT-STEP): a Steam title killed by its
wrapper keeps running under wineserver, keeps its OpenVR session and keeps rendering -- Dead
Herring VR rendered behind a whole Wolfenstein Cyberpilot test that way (151 "Delivered
frame"/s = two clients, every CPU/GPU number invalid). So this launcher now refuses to be the
second client by accident: it runs `game-stop.py status` BEFORE bringing Monado up and stops
(default) or aborts when a tree is still alive. It also reads the controller role list after
Monado is up and says out loud when a hand is `<none>` (a controller powered on AFTER
monado-service never registers -- docs/23 "Start the controllers BEFORE Monado"). Neither check
restarts the service on its own: chaining monado-service restarts is a known USB2-fault trigger.
"""
import os
import re
import select
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VR = HERE.parent
if (Path.home() / "vr" / "monado").is_dir():
    VR = Path.home() / "vr"

MODE = sys.argv[1] if len(sys.argv) > 1 else "1"
TRACKING = sys.argv[2] if len(sys.argv) > 2 else "3dof"

# Not a literal /run/user/1000: jack-in-wayland.sh derives it the same way, and this rig is
# meant to run unattended on more than one box/user.
IPC_SOCKET = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "monado_comp_ipc"
# Monado's own log, written by jack-in-wayland.sh (the role list lives there).
MONADO_LOG = VR / "jack-in-wayland.log"
GAME_STOP = HERE / "game-stop.py"

# Verbose logging, per the docs/27 survey -- turned ON here (not left as a
# someday-maybe) because that's what was asked for after the survey landed.
# Rule from docs/23's own trap: anything that needs to reach the actual
# Proton/game process must be exported BEFORE the `steam` client starts, not
# set via per-game Launch Options -- so this has to happen here, in the env
# passed to the Popen call, not anywhere downstream. XR_LOADER_DEBUG applies
# to any OpenXR client (the 360 player too, not just Steam titles) since
# it's read by libopenxr_loader.so regardless of who links it.
LOG_DIR = VR / "logs"
LOG_DIR.mkdir(exist_ok=True)
GAME_ENV = {
    **os.environ,
    "XR_LOADER_DEBUG": "all",
    "PROTON_LOG": "1",
    "PROTON_LOG_DIR": str(LOG_DIR),
    # Proton's own base set (+timestamp,+pid,+tid,+seh,+unwind,+debugstr,
    # +loaddll,+mscoree) plus +env/+file per docs/27 -- setting this
    # ourselves, since an explicit WINEDEBUG here would otherwise just get
    # overridden by whichever value Proton auto-picks when PROTON_LOG=1 sees
    # nothing already set.
    "WINEDEBUG": "+timestamp,+pid,+tid,+seh,+unwind,+debugstr,+loaddll,+mscoree,+env,+file",
    "DXVK_LOG_LEVEL": "info",
    "VKD3D_DEBUG": "warn",
}
# NOT automated here, on purpose: Unreal Engine's own -log/-LogCmds flags
# (Aircar) need to reach the game binary itself, which only happens via
# Steam's per-game Launch Options UI -- docs/23's "Trap: Steam launch
# options edited on disk don't exist" already established that editing
# localconfig.vdf directly while Steam runs is unreliable/dangerous. Add
# "-log -LogCmds=\"LogInit Verbose, LogHMD Verbose\"" there by hand if
# UE-level detail is ever needed. Unity's Player.log needs no flag at all --
# it's already produced every run at ~/.config/unity3d/<Company>/<Product>/
# Player.log, just go read it.

# name, Steam AppID -- from docs/23-game-compatibility.md's "Working" table only.
# Order matches the doc (roughly discovery order, not a ranking). installed_games()
# filters this down to what has an appmanifest right now, so a long list costs nothing.
GAMES = [
    ("International Space Station Tour VR", "797200"),
    ("Aliens Attack VR", "932190"),
    ("Cosmic Flow: A Relaxing VR Experience", "1267950"),
    ("VRSailing by BeTomorrow", "579050"),
    ("SUPERHOT VR", "617830"),
    ("VRChat", "438100"),
    ("Propagation VR", "1363430"),
    ("Aircar", "1073390"),
    # Added 2026-08-26: confirmed working worn by the user same day ("andaba bien"),
    # but with zero recorded fps/pacing/duration data -- see docs/75.
    ("Dreams of Dali", "591360"),
    ("Google Earth VR", "348250"),
    ("Dead Herring VR", "1498490"),
    ("Tank Mechanic Simulator VR", "1463010"),
    ("SafeZoneVR", "1701090"),
    # Added 2026-08-23 (docs/23 rows that existed but were never copied here).
    ("Wolfenstein: Cyberpilot", "1056970"),
    ("Sniper Elite VR", "752480"),
    ("Vertical Shift", "1807480"),
    ("Hellblade: Senua's Sacrifice VR Edition", "747350"),
    ("Interkosmos", "579110"),
    ("Emergence", "1337820"),
    ("Blast the Past", "943170"),
    ("Audio Factory", "722590"),
    ("VersaillesVR | The Palace is yours", "1098190"),
    ("Steam 360 Video Player", "613220"),
    ("Aperture Hand Lab", "868020"),
    ("Transmissions: Element 120", "365300"),
    ("OpenVR Benchmark", "955610"),
    # Added 2026-08-26 from docs/77 (art/literary shortlist), both free, both installed on
    # /mnt/win5 with their Proton prefixes pre-relocated to ext4 (docs/70 bug). Neither has
    # been worn on this stack yet; both reportedly need controller point/grab (docs/77).
    ("The Night Cafe", "482390"),
    ("Anne Frank House VR", "2877690"),
    # docs/23: its FAIL verdict (T161) was measured with launch options missing
    # PRESSURE_VESSEL_FILESYSTEMS_RW -- recipe complete since, never retested.
    ("NVIDIA VR Funhouse", "468700"),
    # 2026-08-26: native idTech (non-Unity, lower flat-fallback risk); prefix relocated off
    # NTFS (docs/70). Motion-controller title -> default profile (constellation ON).
    ("DOOM VFR", "650000"),
    # 2026-08-26: Source 2, Valve's own, excellent Proton VR support; prefix pre-created on
    # ext4. Standing/long/heavy (69GB, 8GB-VRAM marathon risk). Motion controllers.
    ("Half-Life: Alyx", "546560"),
]
DEFAULT_GAME = "Aircar"

# Per-title VR resource profiles (user-named 2026-08-18, NEXT-STEP WS4): env
# overrides applied to the SERVICE launch (jack-in-wayland.sh inherits our
# environ), decided by which title was picked -- the picker knows the title
# BEFORE Monado comes up, which is the only moment constellation can be chosen.
# Rationale: constellation costs real CPU (~140 solves/s at good geometry, sank
# SLAM to 9.9 Hz in T180); a title flown on the Xbox gamepad pays that for
# nothing. Default for unlisted titles: constellation ON (hands-drawing titles
# are the majority of the catalog).
TITLE_PROFILES = {
    # Aircar: the reference gamepad title -- controllers optional, hands never
    # needed. Constellation off = fewer subsystems live during a demo.
    # The four SLAM knobs are the 2026-08-26 seated-6dof "feels like 3dof but with
    # 6dof" recipe (wearer verdict "super similar a windows"; patch 0097 + docs/80):
    # gyro-orientation prediction (2) + freeze position + 150mm neck-model arc +
    # 50ms correction spread. Inert in 3dof (SLAM not running), so harmless on the
    # approved 3dof demo path; they only engage on the 6dof button.
    "1073390": {
        "WMR_CONSTELLATION_CONTROLLERS": "0",
        "SLAM_PREDICTION_TYPE": "2",
        "SLAM_PRED_FREEZE_POSITION": "1",
        # 2026-08-29 06:14-06:37 (docs/80 "The 10-minute wearer slot"): 150 -> 100. Neck-arm A/B
        # worn in a lit room under the JQ stack, dashboard buttons JN0 / JN100 / JN200 vs the
        # profile's 150: order 0 ~= 100 < 150 < 200 ("me mueve de lugar mucho menos" at 0,
        # "igual parece a la vez anterior" at 100, "la deriva es claramente mayor ahora" at 200).
        # Hypothesis (a) confirmed: less arm, less rotation-onset displacement; 150 was over.
        # 100 rather than 0 because 0 showed near-field cockpit jitter ("un poco de jittering al
        # mirar la cabina de cerca"). Reversible: 0 felt the same, 150/200 worse. The wearer
        # confirmed 100 on 2026-08-29 15:35 ("deja el brazo de cuello en 100").
        "SLAM_PRED_NECK_ARM_MM": "100",
        # 2026-08-27 (evening): 50 -> 25. Variant F (A + spread 25) worn: "bastante solido",
        # smoother settle, latency still low -- the wearer's own ask (E's smoothness without
        # E's delay), confirmed in-headset. Aircar only; Cyberpilot keeps 50 (not re-tested).
        "SLAM_CORRECTION_SPREAD_MS": "25",
        # 2026-08-27 (night, docs/80): Basalt backend config "J" -- recall on, marg-lost off,
        # 2 cm triangulation gate, 12 keyframes, Basalt's default recall norms. The wearer's yaw
        # recording replayed offline: drift over ten 400-600 deg/s turns 2.62 -> 0.28 m; worn:
        # "varios cm" where F went "uno o dos metros". Per-title on purpose (the global
        # basalt-g2-config.json is shared with Dali/Cyberpilot). The Dali 6dof check ran
        # 2026-08-29 05:24 in a DARK room and was invalid -- base ran away just as far in the
        # same dark and was clean once lit; P2 stays per-title, not promoted (docs/80 "the gate
        # run was invalid"). Costs ~18 ms/frame in the frontend (p50 46 vs 28 ms, budget 33) --
        # round P.
        # 2026-08-28 ~18:47 (docs/80, seven worn A/Bs): "JQ" = the round's stack, best verdict
        # "solido, pero no resuelto aun". P2 = J + detection grid 40 (frontend 27 ms instead
        # of 45, same drift); AVG_N 3 (jitter, patch 0103); mid-exposure camera stamp (fewer
        # excursions, patch 0101); queue depth 1 (Basalt 0021: pose age p90 94 ms instead of
        # 138-186, Basalt in->out p90 50 instead of 170-188). Horizon stays 50 (100 was worse).
        "SLAM_CONFIG": os.path.expanduser("~/vr/basalt-variants/P2.toml"),
        "SLAM_CORRECTION_AVG_N": "3",
        "WMR_CAM_TS_MID_EXPOSURE": "1",
        "VIT_QUEUE_DEPTH": "1",
        # 2026-08-27: Monado supersamples 140% by DEFAULT (3024^2/eye) which left this title
        # GPU-bound in 6dof -- fps dived to a 41-71 floor on heavy scenes and reprojected
        # (the felt jitter/drift). 100% (2160^2/eye, native) gave GPU headroom: floor rose to
        # ~79, "muy fluido, muy parejo" (wearer) -> 6dof finally reads as real gold. Trades a
        # little supersampling sharpness; holding 90 wins for this project. NOTE: also applies
        # to the 3dof approved run (slightly less sharp) -- re-confirm 3dof on the next demo.
        "XRT_COMPOSITOR_SCALE_PERCENTAGE": "100",
        # 2026-08-27: patch 0099 (docs/85, Faulto fork review), first wearer test result: guards
        # clean, 0 false triggers over ~12 min including real fast-turn motion. Kept on.
        # SLAM_QUAT_NORM_CHECK / SLAM_SESSION_ANCHOR_RADIUS_CM: two more divergence guards next
        # to the existing speed-based one. 300cm anchor radius chosen generously for seated
        # cockpit head movement -- watch Monado's log for "Tracker diverged" spam, which would
        # mean the radius is too tight for this title (raise it) rather than a real runaway.
        "SLAM_QUAT_NORM_CHECK": "1",
        "SLAM_SESSION_ANCHOR_RADIUS_CM": "300",
        # 2026-08-27: patch 0098 (WMR_FORWARD_ANGULAR_VELOCITY) REMOVED after its first wearer
        # test -- confirmed no perceptible effect on the fast-turn drift ("no parece cambiar
        # nada", docs/85's closing section), a real negative. Pulled out to cut a variable
        # before the next attempt at the actual blocker, not because it caused harm.
        #
        # 2026-08-27 (later): candidates from docs/80's fast-motion research pass
        # (wf_c99cb54e-e54), ready for the next combined wearer test. SLAM_THREADS=6 is new and
        # genuinely untested in this exact condition -- every past SLAM_THREADS rejection had
        # WMR constellation controller-tracking competing for the same camera/CPU budget; this
        # profile runs with constellation OFF, and last night's own timing.csv
        # (/mnt/vrtmp/slam-20260826-042947) shows the TRACKING sub-stage (tbb-parallelized,
        # confirmed) dominating frontend cost 2x over detection (the confirmed-single-threaded,
        # confirmed-unfixable-by-threads stage that killed every prior SLAM_THREADS attempt).
        # Estimated ~10ms anchor-age reduction (106ms -> ~95-96ms) if the extrapolation from the
        # one closest real measurement (T235: 24.6->13.4ms tracking at 4->8 threads) holds.
        # Real risk: CPU contention with Aircar's own render/game threads on this 6C/12T box --
        # must be checked against fps/pacing, not assumed safe just because Aircar is GPU-bound.
        "SLAM_THREADS": "6",
        # 2026-08-27 (night): patch 0100, SLAM_PRED_POSITION_HORIZON_MS + its speed clamp --
        # WEARER-VALIDATED as "variant A" in the 5-way A/B (docs/80): beats the pure-freeze
        # control on latency ("responde mas agil", "se actualiza mas seguido"); B (25ms) and
        # D (clamp 1.0) were indistinguishable from it. Extrapolates real SLAM linear velocity
        # for up to 50ms before holding flat, clamped to 1.5 m/s -- the clamp is load-bearing:
        # the first (unclamped) test sent the wearer 1-3 m out of the cockpit because raw SLAM
        # velocity has 0.2% re-localization spikes of up to 127 m/s (6 m in one 50ms frame).
        # The remaining METERS of drift on fast yaw are NOT this layer's -- they are Basalt's
        # backend losing every landmark under yaw (p10 = 0 above 90 deg/s); see the G-J
        # backend variants in status-dashboard.py and docs/80's night section.
        "SLAM_PRED_POSITION_HORIZON_MS": "50",
        "SLAM_PRED_POSITION_MAX_SPEED_CM_S": "150",  # explicit; also the code default
    },
    # ISS Tour VR: Aircar-class (does not render hands, docs/23) and the heaviest
    # content measured in the whole sweep (8K, monado-service at 519% CPU on T243
    # night) -- the last thing it needs is ~140 solves/s of constellation it never shows.
    "797200": {"WMR_CONSTELLATION_CONTROLLERS": "0"},
    # OpenVR Benchmark: a pure GPU/pacing loop, no hands, used as an instrument --
    # constellation would only add CPU noise to the number being measured.
    "955610": {"WMR_CONSTELLATION_CONTROLLERS": "0"},
    # Dreams of Dali: worn-confirmed 2026-08-26 -- headset-only (gaze/head look),
    # no gamepad, no motion controllers at all. (An earlier guess here from static
    # binary evidence -- OVRGamepad.dll in the install -- wrongly called this
    # gamepad-class; the user's own live playthrough overrides that.) Run with 6dof
    # head tracking per the user's own direction.
    # No head-prediction / anchor knobs on purpose: Dali is the only approved title that
    # receives Basalt's position unclamped (no SLAM_PRED_FREEZE_POSITION, no
    # SLAM_SESSION_ANCHOR_RADIUS_CM), and it needs a LIT room for 6dof -- 2026-08-29 05:24 in
    # the dark it ran 161 m away under P2 and 80 m under base, and was "solido" the minute the
    # lights came on (docs/80 "the gate run was invalid"; scripts/light-preflight.sh).
    "591360": {
        "WMR_CONSTELLATION_CONTROLLERS": "0",
        # 2026-08-29 (docs/80): same rationale as Aircar's 2026-08-27 change above. The 05:24
        # P2 worn run rendered at Monado's 140 % default (3024^2/eye, comp_swapchain_create_init
        # in its log) with the wearer reading "60fps" and one nvidia-smi grab at 94 % / 245 W;
        # the 05:44 control ran with this var from the env (2160^2/eye) and one grab read
        # 73 % / 235 W -- single grabs (docs/84 s2 wants 4+ over 15 s), no fps instrument ran
        # ('up' mode, U_PACING_APP_LOG unset), and the two runs differed in more than scale.
        # The util drop is consistent with the 1.96x pixel ratio if the app then ran ~90 fps.
        # Justified as the next thing to try, not validated: the 2026-08-26 worn approval was
        # at 140 % -- re-confirm worn and get Dali's first measured fps number.
        "XRT_COMPOSITOR_SCALE_PERCENTAGE": "100",
        # 2026-08-29 (docs/80 "the thread finding"): the base control ran at jack-in-wayland.sh's
        # plain default of 4 SLAM threads (nobody set an override for Dali) while P2.toml
        # hardcodes num-threads=6. Per-stage split of the worn timing.csv: TRACKING (the one
        # tbb-parallel frontend stage) p50 20.4 ms at 4 threads vs 12.4 ms at 6, half of each
        # frontend budget (total p50 40.9 vs 24.2 ms); detection is sequential and did not move
        # with threads. Aircar already carries SLAM_THREADS=6 with constellation off, same here.
        "SLAM_THREADS": "6",
        # 2026-08-29 15:02 (docs/80 "the anchor test"): the 0099 session anchor Aircar and Cyberpilot
        # already run, now for Dali too. Worn in a lit room with either Basalt config, Dali ran ~40 m
        # away in the first two minutes of a session (VIO scale snap after a rotation-only start) and
        # settled 2-9 m off; with the anchor: max 3.45 m, 6 resets carrying 0.02-0.21 m and <= 0.02 deg
        # of yaw, final 0.50 m, wearer "se juega muy similar" (1-2 m off at the start, playable).
        # Operator rule that goes with it: headset still on the desk until the title has loaded, then
        # the guest puts it on. Reversible: remove both lines to get the raw position back.
        # 2026-08-29 15:50: the 1-2 m residue is handled by the dashboard's Recentrar button (xrizer
        # patch 0008: touches ~/vr/logs/xrizer-recenter, WaitGetPoses recentres Standing + Seated on
        # the current head pose) once the guest is seated and looking straight ahead -- worn-validated,
        # docs/80 "the recentre lever". No launcher knob involved.
        "SLAM_SESSION_ANCHOR_RADIUS_CM": "300",
        "SLAM_QUAT_NORM_CHECK": "1",
    },
    # Wolfenstein: Cyberpilot (1056970) -- seated mech cockpit; motion controllers
    # are REQUIRED, so constellation stays ON (unlike Aircar/Dali, which drop it).
    # 2026-08-27: user confirmed it renders in-headset but with a pronounced head
    # redraw + controller "saltitos"; Monado's log showed the SLAM frontend dropping
    # camera frames (vit: input_img_queue dropped ...). Apply Aircar's seated-6dof
    # head-prediction recipe (patch 0097: gyro-pred + freeze position + 150mm
    # neck-arc + 50ms correction spread) to smooth the head redraw -- WITHOUT the
    # constellation-off knob, since the game needs tracked hands.
    "1056970": {
        "WMR_CONSTELLATION_CONTROLLERS": "1",  # explicit: the game needs 6dof hands
        "SLAM_PREDICTION_TYPE": "2",
        "SLAM_PRED_FREEZE_POSITION": "1",
        "SLAM_PRED_NECK_ARM_MM": "150",
        "SLAM_CORRECTION_SPREAD_MS": "50",
        # 2026-08-27: same 0099 first wearer test as the Aircar profile above -- see its
        # comment for what to watch for in the log. 2026-08-28: patch 0098
        # (WMR_FORWARD_ANGULAR_VELOCITY) REMOVED here too, for the same reason as Aircar:
        # a confirmed no-effect on the fast-turn drift ("no parece cambiar nada", docs/85's
        # closing section) with a documented double-counting risk against
        # SLAM_PRED_FREEZE_POSITION -- one variable fewer, not a harm fix. SPREAD_MS stays 50
        # here: Aircar's 25 was only validated worn on Aircar, not on this title.
        "SLAM_QUAT_NORM_CHECK": "1",
        "SLAM_SESSION_ANCHOR_RADIUS_CM": "300",
    },
}
PROFILE_DEFAULT = {"WMR_CONSTELLATION_CONTROLLERS": "1"}
# Titles whose verdict in docs/23 does not depend on hands at all (gamepad class): the
# controller-registration check below stays informational for them instead of loud.
# 591360 (Dreams of Dali) is here on the same unconfirmed static evidence as its
# TITLE_PROFILES entry above -- see the comment there.
NO_HANDS_TITLES = {"1073390", "797200", "955610", "591360"}


JACKIN_OUT_LOG = LOG_DIR / "jack-in-launcher.log"


def _save_jackin_output(stdout, stderr, rc):
    """Persist jack-in-wayland.sh's OWN output (not Monado's log -- that one
    already lands in ~/vr/jack-in-wayland.log).

    Real gap found 2026-08-11 (T145): this launcher runs jack-in-wayland.sh with
    capture_output=True and only echoes it to tty4, which nothing records. When the
    boot chain failed that night with "Found no connectors available for direct
    mode", the ONE piece of evidence that would have discriminated between "the
    panel/DP never came up" and "the connector was up but mutter didn't offer it
    for lease yet" was jack-in-wayland.sh's own pre-flight lines ("HMD connector
    (non-desktop=1) up." vs. the "!!" warnings) -- printed to a VT that had already
    been overwritten by agetty by the time anyone looked. /tmp/vr-launcher-console-
    debug.log stayed empty precisely because capture_output=True swallows this
    stream before it can reach that redirect. Same lesson as the tty-hides-stderr
    trap in vr-launcher-console.sh: cheap file, harmless, keep it permanently."""
    try:
        stamp = subprocess.run(["date", "-Iseconds"], capture_output=True, text=True).stdout.strip()
        with open(JACKIN_OUT_LOG, "a") as f:
            f.write(f"\n===== {stamp}  mode={MODE} tracking={TRACKING} rc={rc} =====\n")
            f.write(stdout or "")
            if stderr:
                f.write("----- stderr -----\n")
                f.write(stderr)
    except OSError as e:
        print(f"(could not save the jack-in log: {e})")


def bring_up_monado():
    print("=== subiendo Monado ===")
    IPC_SOCKET.unlink(missing_ok=True)  # SIGKILL de una corrida anterior no limpia esto
    # 180s, no 60s -- encontrado en vivo 2026-08-10: jack-in-wayland.sh's propio
    # peor caso (10s de poll de DP + hasta 3 intentos de ~50s cada uno con 3s de
    # settle entre reintentos) puede superar los 166s. Con 60s, un TimeoutExpired
    # sin capturar tiraba todo el launcher abajo a mitad de un reintento legitimo
    # y dejaba un monado-service huerfano corriendo (subprocess.run mata al hijo
    # directo en el timeout, pero setsid dentro de jack-in-wayland.sh ya habia
    # desacoplado a monado-service de ese proceso).
    try:
        r = subprocess.run(
            [str(VR / "jack-in-wayland.sh"), MODE, TRACKING],
            capture_output=True, text=True, timeout=180,
        )
    except subprocess.TimeoutExpired as e:
        print(f"jack-in-wayland.sh no termino en 180s -- abortando y limpiando.")
        partial = e.stdout if isinstance(e.stdout, (str, type(None))) else e.stdout.decode(errors="replace")
        _save_jackin_output(partial, "(timeout a los 180s)", "timeout")
        if partial:
            print(partial)
        # pgrep -x (exact comm), not -f -- matches jack-in-wayland.sh's own convention
        # (see rig_telemetry.monado_pid()'s docstring): -f scans every process's full
        # command line, so it would also SIGKILL an agent's wait-loop or an ssh wrapper
        # whose argv merely mentions monado-service -- that ghost class is what left
        # demo-recorder.py sampling for 22.5 h on 2026-08-27.
        pids = subprocess.run(["pgrep", "-x", "monado-service"], capture_output=True, text=True).stdout.split()
        for pid in pids:
            subprocess.run(["kill", "-9", pid])
        IPC_SOCKET.unlink(missing_ok=True)
        return False
    _save_jackin_output(r.stdout, r.stderr, r.returncode)
    print(r.stdout)
    if r.returncode != 0 or not IPC_SOCKET.exists():
        print("jack-in-wayland.sh no dejo el socket de Monado listo.")
        print(r.stderr)
        return False
    return True


def check_controller_battery():
    """Runs controller-battery-check.py right after Monado is up, before anything is
    actually launched -- see docs/03-controllers.md's "Battery status" section and
    patches/monado/0040 for why this can't happen earlier (in power-on.py, before
    Monado exists) or via a lighter standalone HID query like controller-pair-check.py's.
    Never blocks: same philosophy as the controller-presence check in power-on.py step
    5 -- only the headset itself (jack-in-wayland.sh's own DP/USB checks) stops the
    user, battery is informational. A missing/old libmonado build without the patch
    just prints "no data" and moves on, it doesn't fail the launch."""
    check_py = HERE / "controller-battery-check.py"
    try:
        r = subprocess.run([sys.executable, str(check_py)], timeout=10)
        if r.returncode != 0:
            print("(controller-battery-check.py salio con error -- no bloquea, sigo igual)")
    except subprocess.TimeoutExpired:
        print("(controller-battery-check.py no termino en 10s -- no bloquea, sigo igual)")
    except OSError as e:
        print(f"(no pude correr controller-battery-check.py: {e} -- no bloquea, sigo igual)")


def check_network_link():
    """Runs network-link-check.py before anything else: online titles feel a
    lossy link as lag/rubber-banding with no error anywhere, and the 2026-08-19
    dual-WAN session measured the loss arriving in periodic multi-second bursts
    a user only discovers mid-match. Single-player titles don't depend on it --
    so, same contract as check_controller_battery(): informational, never
    blocks, a missing script or dead network just prints and moves on."""
    check_py = HERE / "network-link-check.py"
    try:
        r = subprocess.run([sys.executable, str(check_py)], timeout=15)
        if r.returncode != 0:
            print("(network-link-check.py salio con error -- no bloquea, sigo igual)")
    except subprocess.TimeoutExpired:
        print("(network-link-check.py no termino en 15s -- no bloquea, sigo igual)")
    except OSError as e:
        print(f"(no pude correr network-link-check.py: {e} -- no bloquea, sigo igual)")


def game_trees_status():
    """Returns (text, alive) from `game-stop.py status`. alive=False also when the script
    is missing -- then the caller says so and moves on, it does not invent a clean state."""
    if not GAME_STOP.exists():
        return f"(no encuentro {GAME_STOP} -- no puedo verificar si quedo un juego corriendo)", False
    try:
        r = subprocess.run([sys.executable, str(GAME_STOP), "status"],
                           capture_output=True, text=True, timeout=15)
    except (subprocess.TimeoutExpired, OSError) as e:
        return f"(game-stop.py status fallo: {e})", False
    text = (r.stdout or "").strip()
    alive = bool(text) and "no Proton game trees running" not in text
    return text, alive


def check_no_game_running():
    """The second-client trap, closed at the launcher: if any Proton tree is still alive,
    stop it (default after 10 s, or Enter/'s'), or 'n' to go on anyway (an experiment that
    WANTS two clients must say so), or 'q' to abort. Returns False to abort the launch."""
    text, alive = game_trees_status()
    if not alive:
        if text:
            print(f"  juegos previos: {text}")
        return True
    print("!! Hay un juego de Steam TODAVIA corriendo (el wrapper murio, el arbol Wine no):")
    for line in text.splitlines():
        print(f"     {line}")
    print("   Lanzar otro encima = dos clientes en Monado, numeros de CPU/GPU/fps invalidos.")
    ans = read_choice_with_timeout(
        "   [Enter/s] pararlos ahora   [n] seguir igual   [q] abortar   (10s -> parar): ",
        10, "s", "pararlos",
    ).lower()
    if ans == "q":
        print("   abortado por pedido.")
        return False
    if ans == "n":
        print("   siguiendo con el juego previo vivo -- anotalo en la medicion.")
        return True
    r = subprocess.run([sys.executable, str(GAME_STOP), "stop", "all"], text=True)
    if r.returncode != 0:
        print("   game-stop.py no pudo parar todo (ver arriba). No lanzo otro encima.")
        return False
    return True


ROLE_LINE = re.compile(r"^\s*(left|right):\s*(.+?)\s*$")


def check_controllers_registered(appid):
    """Read Monado's role list from its own log after it came up. A controller powered on
    after monado-service started gets its config read (battery shows up) but stays `<none>`
    for the whole session (docs/23, T244; the right-hand startup race in CLAUDE.md). We only
    REPORT: restarting the service here would chain restarts, which is a USB2-fault trigger.
    Loud for hands titles, one line for the gamepad class (NO_HANDS_TITLES)."""
    roles = {}
    try:
        with open(MONADO_LOG, errors="replace") as f:
            for line in f:
                m = ROLE_LINE.match(line)
                if m and m.group(1) not in roles:  # first role list = this service start
                    roles[m.group(1)] = m.group(2)
    except OSError as e:
        print(f"  (no pude leer {MONADO_LOG} para los roles de los controles: {e})")
        return
    if not roles:
        print("  (Monado no imprimio todavia su lista de roles -- no se si los controles registraron)")
        return
    missing = [h for h in ("left", "right") if roles.get(h, "<none>").startswith("<none>")]
    summary = ", ".join(f"{h}: {roles.get(h, '?')}" for h in ("left", "right"))
    if not missing:
        print(f"  controles registrados: {summary}")
        return
    if appid in NO_HANDS_TITLES:
        print(f"  controles: {summary} -- titulo sin manos, sigue igual.")
        return
    print(f"!! Controles NO registrados en esta sesion: {', '.join(missing)} ({summary}).")
    print("   Un control prendido DESPUES de monado-service no registra nunca. Si el titulo")
    print("   necesita manos: bajar con jack-in-wayland.sh down, prender los dos controles,")
    print("   y volver a subir -- una vez, no en loop (reinicios encadenados = falla USB2).")


def find_steamapps_dirs():
    """Every real steamapps dir this rig has, primary AND secondary libraries.

    Found live 2026-08-26: this used to return just the FIRST primary path it
    found and stop there, so any title installed on a secondary library (this
    rig has two: /mnt/win5/SteamLibrary, /mnt/videos/SteamLibrary -- Dali,
    Hellblade and Cyberpilot all live on those, not the primary) silently read
    as "not installed" and vanished from the picker with no error, right
    before a live demo. Reads the primary's own libraryfolders.vdf for the
    authoritative secondary-library list (it can lag a fresh install by one
    write cycle, so /mnt/*/SteamLibrary is also scanned directly as a
    fallback) rather than hardcoding mount paths that could change."""
    primaries = (
        Path.home() / ".steam" / "debian-installation",
        Path.home() / ".steam" / "steam",
        Path.home() / ".local" / "share" / "Steam",
    )
    primary = next((p for p in primaries if (p / "steamapps").is_dir()), None)
    if primary is None:
        return []
    dirs = [primary / "steamapps"]
    vdf = primary / "steamapps" / "libraryfolders.vdf"
    if vdf.is_file():
        for m in re.finditer(r'"path"\s+"([^"]+)"', vdf.read_text(errors="replace")):
            candidate = Path(m.group(1)) / "steamapps"
            if candidate.is_dir() and candidate not in dirs:
                dirs.append(candidate)
    for mnt_lib in Path("/mnt").glob("*/SteamLibrary/steamapps"):
        if mnt_lib.is_dir() and mnt_lib not in dirs:
            dirs.append(mnt_lib)
    return dirs


def installed_games():
    """"mapeamos lo que hay" -- don't just trust the hardcoded catalog, check
    which of those AppIDs are actually installed right now (an
    appmanifest_<id>.acf really exists in ANY known library), so an
    uninstalled/removed title never shows up as pickable, and one actually
    installed on a secondary library isn't missed either. Falls back to the
    full catalog if no steamapps dir at all can be found -- better to offer
    something than nothing."""
    steamapps_dirs = find_steamapps_dirs()
    if not steamapps_dirs:
        return list(GAMES)
    return [
        (name, appid) for name, appid in GAMES
        if any((d / f"appmanifest_{appid}.acf").exists() for d in steamapps_dirs)
    ]


def read_choice_with_timeout(prompt, timeout, default_choice, default_label):
    """Same philosophy as vr-boot-selector.sh's own a/m timeout: give a real
    choice, but don't require one -- proceed with a known-good default if
    nobody answers in time. This is what "arma todo para lanzar apps en vr"
    (auto keeps going, doesn't just wait forever) actually means once hardware
    is already confirmed healthy."""
    print(prompt, end="", flush=True)
    ready, _, _ = select.select([sys.stdin], [], [], timeout)
    if ready:
        return sys.stdin.readline().strip()
    print(f"\n  (sin respuesta en {timeout}s -- sigo con {default_label})")
    return default_choice


def main():
    # Subcommands that do not launch anything: process-state hygiene from the console.
    if MODE == "status":
        text, _alive = game_trees_status()
        print(text)
        return
    if MODE == "stop":
        target = TRACKING if len(sys.argv) > 2 else "all"
        sys.exit(subprocess.run([sys.executable, str(GAME_STOP), "stop", target]).returncode)

    games = installed_games()

    print("==================================================")
    print("  VR launcher")
    print("==================================================")
    # Link verdict on screen while the user picks a title (or the timeout
    # picks for them): a single-player pick can ignore an AMARILLO/ROJO,
    # an online pick shouldn't be surprised by it mid-match.
    check_network_link()
    print()
    print("  [1] Player 360/VR180 (contenido de prueba)")
    default_n = None
    for i, (name, _appid) in enumerate(games):
        n = 2 + i
        tag = "  -- default" if name == DEFAULT_GAME else ""
        print(f"  [{n}] {name}{tag}")
        if name == DEFAULT_GAME:
            default_n = n
    stub_n = 2 + len(games)
    print(f"  [{stub_n}] Juego que no es de Steam (todavia no armado)")
    print()

    if default_n is None:
        # DEFAULT_GAME isn't installed right now -- fall back to the player,
        # never point the unattended default at a game that can't launch.
        default_n, default_label = 1, "el player 360"
    else:
        default_label = DEFAULT_GAME
    # Non-interactive pick (an agent driving a measurement session, or a future arcade mode):
    # VR_LAUNCH_APPID=<appid> (or "player") skips the 15 s prompt entirely. Without it, stdin at
    # EOF (as under a non-interactive shell) would read "" and land on "Opcion invalida".
    forced = os.environ.get("VR_LAUNCH_APPID")
    if forced == "player":
        choice = "1"
    elif forced:
        hit = [str(2 + i) for i, (_n, a) in enumerate(games) if a == forced]
        if not hit:
            print(f"VR_LAUNCH_APPID={forced} no esta instalado/en el catalogo -- no lanzo nada.")
            sys.exit(2)
        choice = hit[0]
        print(f"  (VR_LAUNCH_APPID={forced} -> opcion {choice}, sin prompt)")
    else:
        choice = read_choice_with_timeout(
            f"Elegí [1-{stub_n}], 15s -> {default_label}: ", 15, str(default_n), default_label,
        )

    if choice == str(stub_n):
        print(f"Opcion {stub_n} todavia no tiene nada real conectado -- no hay ningun juego")
        print("no-Steam identificado ni probado todavia. No finjo que anda.")
        return

    try:
        choice_n = int(choice)
    except ValueError:
        choice_n = -1

    if choice_n == 1:
        selected = ("__player__", None)
    elif 2 <= choice_n <= stub_n - 1:
        selected = games[choice_n - 2]
    else:
        print("Opcion invalida.")
        return

    # Apply the selected title's VR resource profile BEFORE the service comes up
    # (constellation on/off is a service-launch decision, not changeable after).
    # Ambient env wins over the profile: an operator exporting the var explicitly
    # is doing an experiment and the picker must not fight them.
    _name, _appid = selected
    # Merge OVER PROFILE_DEFAULT so a partial per-title profile still inherits the
    # constellation default (ON). A listed title that omits WMR_CONSTELLATION_CONTROLLERS
    # would otherwise fall through to jack-in-wayland's 6dof default of OFF, silently
    # dropping positional controller tracking (the 2026-08-27 Cyberpilot regression:
    # its profile set only the SLAM head knobs and lost 6dof hands).
    profile = {**PROFILE_DEFAULT, **TITLE_PROFILES.get(_appid, {})}
    for k, v in profile.items():
        if k not in os.environ:
            os.environ[k] = v
            print(f"perfil de titulo: {k}={v}")

    # No second client by accident: a previous title's Wine tree must be gone first.
    if not check_no_game_running():
        sys.exit(1)

    if not bring_up_monado():
        print("No lanzo nada -- Monado no quedo listo.")
        sys.exit(1)

    check_controller_battery()
    check_controllers_registered(_appid)

    name, appid = selected
    if name == "__player__":
        print("=== lanzando el player 360/VR180 ===")
        subprocess.Popen([str(VR / "play360.sh"), str(VR / "media" / "test-equirect.jpg"), "-s"], env=GAME_ENV)
    else:
        print(f"=== lanzando {name} (Steam appid {appid}) ===")
        subprocess.Popen(["steam", "-applaunch", appid], env=GAME_ENV)

    print("  lanzado (queda corriendo en background, este script no espera a que cierre).")

    # Auto-registro del demo (docs/75, docs/80). Opt-in via VR_DEMO_RECORD=1 so it fires for
    # real demo runs (the dashboard demo buttons set it) but not for dev/tuning launches.
    # demo-recorder.py records to RAM while the session is live and flushes to permanent
    # storage with date + eye-height + notes when monado-service ends. It stops on its own
    # (bound to the monado-service pid it finds at start; DEMO_RECORDER_MAX_H backstop).
    if os.environ.get("VR_DEMO_RECORD") == "1":
        rec = VR / "demo-recorder.py"
        if rec.exists():
            comment = os.environ.get("VR_DEMO_COMMENT", f"{name} {TRACKING}")
            reclog = open(LOG_DIR / "demo-recorder.out", "a")
            subprocess.Popen([sys.executable, str(rec), "start", comment],
                             stdin=subprocess.DEVNULL, stdout=reclog, stderr=subprocess.STDOUT,
                             start_new_session=True)
            print(f"  auto-registro del demo iniciado (demo-recorder.py, comentario: {comment!r}).")


if __name__ == "__main__":
    main()
