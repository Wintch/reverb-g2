/*
 * libOVRPlugin.so -- a do-nothing stub that reports "no Oculus HMD present".
 *
 * WHY THIS EXISTS. InCell VR and InMind VR (Nival VR, DK2 era) ship NATIVE Linux Unity
 * builds that call into OVRPlugin -- Oculus's own native plugin -- before doing anything
 * else, via OVRSwitcher.GetVRActiveDevice() / OVRManager.Update(). Oculus abandoned Linux
 * in 2015 and libOVRPlugin.so has never existed on this platform, so Mono throws
 * DllNotFoundException and the process aborts within a second. That abort is what earlier
 * sessions recorded as "an unrelated Mono crash" -- it is a symptom, not a cause.
 *
 * Both games have an OVRSwitcher, i.e. they can fall through to a non-Oculus device. They
 * simply never get the chance. This stub gives Mono something to bind to and answers
 * "no HMD, not initialised, no capabilities" to everything, so the switcher can move on
 * to OpenVR -- which is where xrizer is waiting.
 *
 * It deliberately implements NOTHING. If a title ever needs real behaviour here, that is
 * a LibOVR-to-OpenVR shim and a much larger piece of work (see the parked idea note).
 *
 * Calls are traced once per symbol to stderr when OVRSTUB_TRACE=1, so the set a given
 * title actually uses is discoverable rather than guessed.
 *
 * Build:   ./build.sh
 * Install: copy the .so next to the game's libmono.so (<Game>_Data/Mono/x86_64/).
 *
 * ABI note: every entry point is declared variadic-free and returns 0 (or 0.0f for the
 * handful that return float in OVRPlugin 0.1.0). On x86-64 SysV the caller cleans up, so
 * ignoring arguments is safe; returning the wrong *class* of value would not be, which is
 * why the float-returning ones are listed explicitly rather than lumped in.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int trace_on(void)
{
	static int cached = -1;
	if (cached < 0) {
		const char *e = getenv("OVRSTUB_TRACE");
		cached = (e && *e && strcmp(e, "0") != 0) ? 1 : 0;
	}
	return cached;
}

/* Trace each symbol the first time it is called, so we learn what a title really needs. */
#define TRACE_ONCE(name)                                                        \
	do {                                                                    \
		static int seen = 0;                                            \
		if (!seen && trace_on()) {                                      \
			seen = 1;                                               \
			fprintf(stderr, "[ovrplugin-stub] %s\n", name);         \
			fflush(stderr);                                         \
		}                                                               \
	} while (0)

#define STUB_INT(name)                                                          \
	int name(void)                                                          \
	{                                                                       \
		TRACE_ONCE(#name);                                              \
		return 0;                                                       \
	}

#define STUB_FLOAT(name)                                                        \
	float name(void)                                                        \
	{                                                                       \
		TRACE_ONCE(#name);                                              \
		return 0.0f;                                                    \
	}

STUB_INT(ovrp_DismissHSW)
STUB_INT(ovrp_GetAppHasVrFocus)
STUB_INT(ovrp_GetAppLatencyTimings)
STUB_INT(ovrp_GetAppMonoscopic)
STUB_INT(ovrp_GetAppShouldQuit)
STUB_INT(ovrp_GetAppShouldRecenter)
STUB_INT(ovrp_GetAudioInId)
STUB_INT(ovrp_GetAudioOutId)
STUB_INT(ovrp_GetBatteryStatus)
STUB_INT(ovrp_GetCaps)
STUB_INT(ovrp_GetCaps2)
STUB_INT(ovrp_GetControllerState)
STUB_INT(ovrp_GetEyeAcceleration)
STUB_INT(ovrp_GetEyeFrustum)
STUB_INT(ovrp_GetEyeOcclusionMeshEnabled)
STUB_FLOAT(ovrp_GetEyeTextureScale)
STUB_INT(ovrp_GetEyeTextureSize)
STUB_INT(ovrp_GetEyeVelocity)
STUB_FLOAT(ovrp_GetFloat)
STUB_INT(ovrp_GetHeadphonesPresent)
STUB_INT(ovrp_GetInitialized)
STUB_INT(ovrp_GetInputState)
STUB_INT(ovrp_GetNativeSDKVersion)
STUB_INT(ovrp_GetNodeAcceleration)
STUB_INT(ovrp_GetNodeFrustum)
STUB_INT(ovrp_GetNodeOrientationTracked)
STUB_INT(ovrp_GetNodePose)
STUB_INT(ovrp_GetNodePositionTracked)
STUB_INT(ovrp_GetNodePresent)
STUB_INT(ovrp_GetNodeVelocity)
STUB_INT(ovrp_GetStatus)
STUB_INT(ovrp_GetStatus2)
STUB_INT(ovrp_GetString)
STUB_FLOAT(ovrp_GetSystemBatteryLevel)
STUB_INT(ovrp_GetSystemBatteryStatus)
STUB_FLOAT(ovrp_GetSystemBatteryTemperature)
STUB_INT(ovrp_GetSystemCpuLevel)
STUB_FLOAT(ovrp_GetSystemDisplayFrequency)
STUB_INT(ovrp_GetSystemGpuLevel)
STUB_INT(ovrp_GetSystemHeadphonesPresent)
STUB_INT(ovrp_GetSystemPowerSavingMode)
STUB_INT(ovrp_GetSystemProductName)
STUB_INT(ovrp_GetSystemVolume)
STUB_INT(ovrp_GetSystemVSyncCount)
STUB_INT(ovrp_GetTrackerFrustum)
STUB_INT(ovrp_GetTrackerPose)
STUB_INT(ovrp_GetTrackingCalibratedOrigin)
STUB_INT(ovrp_GetTrackingOrientationEnabled)
STUB_INT(ovrp_GetTrackingOrientationSupported)
STUB_INT(ovrp_GetTrackingOriginType)
STUB_INT(ovrp_GetTrackingPositionEnabled)
STUB_INT(ovrp_GetTrackingPositionSupported)
STUB_INT(ovrp_GetUserEyeDepth)
STUB_INT(ovrp_GetUserEyeHeight)
STUB_INT(ovrp_GetUserIPD)
STUB_INT(ovrp_GetUserPresent)
STUB_INT(ovrp_GetVersion)
STUB_INT(ovrp_RecenterTrackingOrigin)
STUB_INT(ovrp_SetAppIgnoreVrFocus)
STUB_INT(ovrp_SetAppMonoscopic)
STUB_INT(ovrp_SetCaps)
STUB_INT(ovrp_SetControllerVibration)
STUB_INT(ovrp_SetEyeOcclusionMeshEnabled)
STUB_INT(ovrp_SetEyeTextureScale)
STUB_INT(ovrp_SetFloat)
STUB_INT(ovrp_SetOverlayQuad)
STUB_INT(ovrp_SetOverlayQuad2)
STUB_INT(ovrp_SetSystemCpuLevel)
STUB_INT(ovrp_SetSystemGpuLevel)
STUB_INT(ovrp_SetSystemVSyncCount)
STUB_INT(ovrp_SetTrackingOrientationEnabled)
STUB_INT(ovrp_SetTrackingOriginType)
STUB_INT(ovrp_SetTrackingPositionEnabled)
STUB_INT(ovrp_SetUserEyeDepth)
STUB_INT(ovrp_SetUserEyeHeight)
STUB_INT(ovrp_SetUserIPD)
STUB_INT(ovrp_ShowSystemUI)
STUB_INT(ovrp_ShowUI)
