// hmd-modeset — direct modeset on the headset's connector, without Monado or Vulkan.
//
//   ./hmd-modeset list                lists the EDID modes and exits
//   ./hmd-modeset native <idx> [sec]  uses an EDID mode unmodified
//   ./hmd-modeset <hz> [sec]          synthetic modeline (NOTE: NVIDIA rejects it, see below)
//
// Gets the display via wp_drm_lease_v1, same as Monado: the Wayland compositor never uses
// the headset (it's marked non-desktop), so leasing it doesn't touch any desktop monitor
// and there's no need to switch VT or stop GNOME.
//
// MEASURED, and that's why this tool is ordered this way:
//
//  1. The panel turns ITSELF OFF after ~3 s if it doesn't receive a signal. That's why all
//     the setup (lease, CRTC, framebuffers) happens BEFORE turning on the panel, and the
//     HID activation happens immediately after the first modeset.
//  2. Just sending screen-enable {0x04,0x01} is NOT enough: without the Reverb's full
//     activation sequence the panel stays dead, it doesn't even show the HP logo.
//     This is delegated to scripts/panel.py (override with HMD_PANEL_CMD).
//  3. Monado resends the screen-enable after things settle, because the companion can
//     re-enumerate and miss the command. The same trick is used here.
//  4. NVIDIA rejects with EINVAL any modeline that doesn't come from the EDID, so the
//     synthetic "<hz>" mode almost certainly fails. It's kept because the EINVAL itself
//     is useful information.
//
// The page-flip loop isn't decorative: counting COMPLETED flips measures whether the CRTC
// is actually scanning out and generating vblanks. It's the only reliable non-physical
// signal we have, because Vulkan/OpenXR happily report 90 fps with the panel black.
//
// Still: the final verification is PHYSICAL. You have to look inside the headset.

#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>
#include <wayland-client.h>
#include <drm_fourcc.h>
#include <xf86drm.h>
#include <xf86drmMode.h>
#include "drm-lease-v1-client-protocol.h"

static struct wp_drm_lease_device_v1 *lease_dev;
static struct wp_drm_lease_connector_v1 *hmd_conn;
static int lease_fd = -1, probe_fd = -1, lease_done;
static uint32_t hmd_conn_id;
static char hmd_name[64];

// ---- lease protocol ---------------------------------------------------------------

static void c_name(void *d, struct wp_drm_lease_connector_v1 *c, const char *n)
{ (void)d; (void)c; snprintf(hmd_name, sizeof(hmd_name), "%s", n); }
static void c_desc(void *d, struct wp_drm_lease_connector_v1 *c, const char *s)
{ (void)d; (void)c; (void)s; }
static void c_id(void *d, struct wp_drm_lease_connector_v1 *c, uint32_t id)
{ (void)d; (void)c; hmd_conn_id = id; }
static void c_done(void *d, struct wp_drm_lease_connector_v1 *c) { (void)d; (void)c; }
static void c_withdrawn(void *d, struct wp_drm_lease_connector_v1 *c) { (void)d; (void)c; }
static const struct wp_drm_lease_connector_v1_listener conn_listener = {
	c_name, c_desc, c_id, c_done, c_withdrawn,
};

static void d_fd(void *d, struct wp_drm_lease_device_v1 *v, int fd)
{ (void)d; (void)v; probe_fd = fd; }
static void d_conn(void *d, struct wp_drm_lease_device_v1 *v,
                   struct wp_drm_lease_connector_v1 *c)
{
	(void)d; (void)v;
	if (hmd_conn) { wp_drm_lease_connector_v1_destroy(c); return; }
	hmd_conn = c;
	wp_drm_lease_connector_v1_add_listener(c, &conn_listener, NULL);
}
static void d_done(void *d, struct wp_drm_lease_device_v1 *v) { (void)d; (void)v; }
static void d_rel(void *d, struct wp_drm_lease_device_v1 *v) { (void)d; (void)v; }
static const struct wp_drm_lease_device_v1_listener dev_listener = {
	d_fd, d_conn, d_done, d_rel,
};

static void l_fd(void *d, struct wp_drm_lease_v1 *l, int fd)
{ (void)d; (void)l; lease_fd = fd; lease_done = 1; }
static void l_fin(void *d, struct wp_drm_lease_v1 *l)
{ (void)d; (void)l; lease_done = 1; }
static const struct wp_drm_lease_v1_listener lease_listener = { l_fd, l_fin };

static void reg_add(void *d, struct wl_registry *r, uint32_t name, const char *i, uint32_t v)
{
	(void)d; (void)v;
	if (!strcmp(i, wp_drm_lease_device_v1_interface.name)) {
		lease_dev = wl_registry_bind(r, name, &wp_drm_lease_device_v1_interface, 1);
		wp_drm_lease_device_v1_add_listener(lease_dev, &dev_listener, NULL);
	}
}
static void reg_del(void *d, struct wl_registry *r, uint32_t n) { (void)d; (void)r; (void)n; }
static const struct wl_registry_listener reg_listener = { reg_add, reg_del };

// ---- framebuffers ----------------------------------------------------------------------

struct fb {
	uint32_t handle, fb_id, pitch;
	uint64_t size;
	uint8_t *px;
};

// Returns 0 on success. Tries AddFB2 (with explicit format) and falls back to AddFB if
// needed; which of the two worked is useful information about what nvidia-drm accepts
// for scanout.
static int fb_create(int fd, uint32_t w, uint32_t h, uint32_t argb, struct fb *out,
                     const char **how)
{
	struct drm_mode_create_dumb creq = { .width = w, .height = h, .bpp = 32 };
	if (drmIoctl(fd, DRM_IOCTL_MODE_CREATE_DUMB, &creq)) {
		fprintf(stderr, "  CREATE_DUMB: %s\n", strerror(errno));
		return -1;
	}
	out->handle = creq.handle;
	out->pitch = creq.pitch;
	out->size = creq.size;

	uint32_t handles[4] = { creq.handle, 0, 0, 0 };
	uint32_t pitches[4] = { creq.pitch, 0, 0, 0 };
	uint32_t offsets[4] = { 0, 0, 0, 0 };
	if (!drmModeAddFB2(fd, w, h, DRM_FORMAT_XRGB8888, handles, pitches, offsets,
	                   &out->fb_id, 0)) {
		*how = "AddFB2/XRGB8888";
	} else if (!drmModeAddFB(fd, w, h, 24, 32, creq.pitch, creq.handle, &out->fb_id)) {
		*how = "AddFB (legacy, depth24/bpp32)";
	} else {
		fprintf(stderr, "  AddFB2 and AddFB both failed: %s\n", strerror(errno));
		return -1;
	}

	struct drm_mode_map_dumb mreq = { .handle = creq.handle };
	if (drmIoctl(fd, DRM_IOCTL_MODE_MAP_DUMB, &mreq)) {
		fprintf(stderr, "  MAP_DUMB: %s\n", strerror(errno));
		return -1;
	}
	out->px = mmap(0, creq.size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, mreq.offset);
	if (out->px == MAP_FAILED) { perror("  mmap"); return -1; }

	// Flat color + a vertical band of maximum contrast. If the panel locks on, this is
	// impossible to confuse with "I don't see anything".
	for (uint32_t y = 0; y < h; y++) {
		uint32_t *row = (uint32_t *)(out->px + y * creq.pitch);
		for (uint32_t x = 0; x < w; x++)
			row[x] = (x % 256 < 32) ? 0x00FFFFFF : argb;
	}
	return 0;
}

// ---- KMS properties (for atomic) -----------------------------------------------------

static uint32_t prop_id(int fd, uint32_t obj, uint32_t type, const char *name)
{
	drmModeObjectProperties *props = drmModeObjectGetProperties(fd, obj, type);
	if (!props) return 0;
	uint32_t id = 0;
	for (uint32_t i = 0; i < props->count_props && !id; i++) {
		drmModePropertyRes *p = drmModeGetProperty(fd, props->props[i]);
		if (!p) continue;
		if (!strcmp(p->name, name)) id = p->prop_id;
		drmModeFreeProperty(p);
	}
	drmModeFreeObjectProperties(props);
	return id;
}

static uint64_t prop_val(int fd, uint32_t obj, uint32_t type, const char *name, int *found)
{
	drmModeObjectProperties *props = drmModeObjectGetProperties(fd, obj, type);
	if (found) *found = 0;
	if (!props) return 0;
	uint64_t val = 0;
	for (uint32_t i = 0; i < props->count_props; i++) {
		drmModePropertyRes *p = drmModeGetProperty(fd, props->props[i]);
		if (!p) continue;
		if (!strcmp(p->name, name)) {
			val = props->prop_values[i];
			if (found) *found = 1;
			drmModeFreeProperty(p);
			break;
		}
		drmModeFreeProperty(p);
	}
	drmModeFreeObjectProperties(props);
	return val;
}

// ---- page flips ------------------------------------------------------------------------

static volatile int flips, pending;

static void on_flip(int fd, unsigned seq, unsigned sec, unsigned usec, void *data)
{ (void)fd; (void)seq; (void)sec; (void)usec; (void)data; flips++; pending = 0; }

static double now_s(void)
{
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	return ts.tv_sec + ts.tv_nsec / 1e9;
}

// ---- main -------------------------------------------------------------------------------

int main(int argc, char **argv)
{
	if (argc < 2) {
		fprintf(stderr, "usage: %s list | native <idx> [sec] | <hz> [sec]\n", argv[0]);
		return 2;
	}
	int list_only = !strcmp(argv[1], "list");
	int use_native = !strcmp(argv[1], "native");
	int secs = 30;

	struct wl_display *dpy = wl_display_connect(NULL);
	if (!dpy) { fprintf(stderr, "no Wayland session\n"); return 1; }
	struct wl_registry *reg = wl_display_get_registry(dpy);
	wl_registry_add_listener(reg, &reg_listener, NULL);
	wl_display_roundtrip(dpy);
	if (!lease_dev) { fprintf(stderr, "the compositor doesn't offer wp_drm_lease_device_v1\n"); return 1; }
	wl_display_roundtrip(dpy);
	wl_display_roundtrip(dpy);
	if (!hmd_conn) { fprintf(stderr, "the compositor doesn't offer leasable connectors\n"); return 1; }
	printf("connector: %s (id %u)\n", hmd_name, hmd_conn_id);

	drmModeConnector *c = drmModeGetConnector(probe_fd, hmd_conn_id);
	if (!c) { perror("drmModeGetConnector"); return 1; }
	printf("EDID modes (%d):\n", c->count_modes);
	for (int i = 0; i < c->count_modes; i++) {
		drmModeModeInfo *m = &c->modes[i];
		printf("  [%d] %ux%u  clock=%u kHz  htot=%u vtot=%u  -> %.2f Hz\n", i,
		       m->hdisplay, m->vdisplay, m->clock, m->htotal, m->vtotal,
		       m->clock * 1000.0 / (m->htotal * (double)m->vtotal));
	}
	if (list_only) return 0;

	drmModeModeInfo mode;
	if (use_native) {
		int idx = argc > 2 ? atoi(argv[2]) : 1;
		if (idx < 0 || idx >= c->count_modes) { fprintf(stderr, "index out of range\n"); return 2; }
		mode = c->modes[idx];
		if (argc > 3) secs = atoi(argv[3]);
		printf("\nNATIVE mode [%d] unmodified\n", idx);
	} else {
		double hz = atof(argv[1]);
		if (argc > 2) secs = atoi(argv[2]);
		mode = c->modes[0];
		for (int i = 0; i < c->count_modes; i++)
			if (c->modes[i].hdisplay == 2880) { mode = c->modes[i]; break; }
		double per_frame = (double)mode.htotal * mode.vtotal;
		mode.clock = (uint32_t)(hz * per_frame / 1000.0 + 0.5);
		mode.vrefresh = (uint32_t)(hz + 0.5);
		snprintf(mode.name, sizeof(mode.name), "%ux%u@%d", mode.hdisplay, mode.vdisplay,
		         mode.vrefresh);
		printf("\nSYNTHETIC modeline (NVIDIA usually rejects it)\n");
	}
	double target_hz = mode.clock * 1000.0 / (mode.htotal * (double)mode.vtotal);
	printf("  %ux%u  clock=%u kHz  htot=%u vtot=%u  -> %.3f Hz\n",
	       mode.hdisplay, mode.vdisplay, mode.clock, mode.htotal, mode.vtotal, target_hz);

	// --- all setup BEFORE touching the panel (it turns itself off after ~3 s without signal) ---
	struct wp_drm_lease_request_v1 *req = wp_drm_lease_device_v1_create_lease_request(lease_dev);
	wp_drm_lease_request_v1_request_connector(req, hmd_conn);
	struct wp_drm_lease_v1 *lease = wp_drm_lease_request_v1_submit(req);
	wp_drm_lease_v1_add_listener(lease, &lease_listener, NULL);
	while (!lease_done)
		if (wl_display_dispatch(dpy) < 0) break;
	if (lease_fd < 0) { fprintf(stderr, "the compositor DENIED the lease\n"); return 1; }

	// The caps change WHAT is visible, so they go before requesting resources. Without
	// UNIVERSAL_PLANES the primary plane doesn't show up, and legacy page flip on a lease
	// fails with EINVAL (measured).
	int cap_up = drmSetClientCap(lease_fd, DRM_CLIENT_CAP_UNIVERSAL_PLANES, 1);
	int cap_at = drmSetClientCap(lease_fd, DRM_CLIENT_CAP_ATOMIC, 1);
	int atomic = (cap_up == 0 && cap_at == 0);

	drmModeRes *res = drmModeGetResources(lease_fd);
	if (!res || res->count_crtcs < 1) { fprintf(stderr, "the lease didn't bring a CRTC\n"); return 1; }
	uint32_t crtc_id = res->crtcs[0];
	printf("lease OK (fd %d, crtc %u)  atomic=%s\n", lease_fd, crtc_id,
	       atomic ? "yes" : "NO");

	uint32_t plane_id = 0;
	if (atomic) {
		drmModePlaneRes *pr = drmModeGetPlaneResources(lease_fd);
		for (uint32_t k = 0; pr && k < pr->count_planes; k++) {
			int found = 0;
			uint64_t t = prop_val(lease_fd, pr->planes[k], DRM_MODE_OBJECT_PLANE,
			                      "type", &found);
			if (found && t == DRM_PLANE_TYPE_PRIMARY) { plane_id = pr->planes[k]; break; }
		}
		if (!plane_id) {
			fprintf(stderr, "couldn't find a primary plane in the lease\n");
			atomic = 0;
		} else {
			printf("primary plane: %u\n", plane_id);
		}
	}

	struct fb fbs[2];
	const char *how = "?";
	if (fb_create(lease_fd, mode.hdisplay, mode.vdisplay, 0x00FF6000, &fbs[0], &how)) return 1;
	if (fb_create(lease_fd, mode.hdisplay, mode.vdisplay, 0x000060FF, &fbs[1], &how)) return 1;
	printf("framebuffers: %s  (%ux%u pitch=%u)\n", how, mode.hdisplay, mode.vdisplay, fbs[0].pitch);

	// --- modeset, and the panel IMMEDIATELY after ---
	uint32_t blob_id = 0;
	uint32_t p_conn_crtc = 0, p_crtc_mode = 0, p_crtc_active = 0;
	uint32_t p_fb = 0, p_pcrtc = 0, p_sx = 0, p_sy = 0, p_sw = 0, p_sh = 0,
	         p_cx = 0, p_cy = 0, p_cw = 0, p_ch = 0;

	if (atomic) {
		if (drmModeCreatePropertyBlob(lease_fd, &mode, sizeof(mode), &blob_id)) {
			perror("CreatePropertyBlob"); return 1;
		}
		p_conn_crtc   = prop_id(lease_fd, hmd_conn_id, DRM_MODE_OBJECT_CONNECTOR, "CRTC_ID");
		p_crtc_mode   = prop_id(lease_fd, crtc_id, DRM_MODE_OBJECT_CRTC, "MODE_ID");
		p_crtc_active = prop_id(lease_fd, crtc_id, DRM_MODE_OBJECT_CRTC, "ACTIVE");
		p_fb    = prop_id(lease_fd, plane_id, DRM_MODE_OBJECT_PLANE, "FB_ID");
		p_pcrtc = prop_id(lease_fd, plane_id, DRM_MODE_OBJECT_PLANE, "CRTC_ID");
		p_sx = prop_id(lease_fd, plane_id, DRM_MODE_OBJECT_PLANE, "SRC_X");
		p_sy = prop_id(lease_fd, plane_id, DRM_MODE_OBJECT_PLANE, "SRC_Y");
		p_sw = prop_id(lease_fd, plane_id, DRM_MODE_OBJECT_PLANE, "SRC_W");
		p_sh = prop_id(lease_fd, plane_id, DRM_MODE_OBJECT_PLANE, "SRC_H");
		p_cx = prop_id(lease_fd, plane_id, DRM_MODE_OBJECT_PLANE, "CRTC_X");
		p_cy = prop_id(lease_fd, plane_id, DRM_MODE_OBJECT_PLANE, "CRTC_Y");
		p_cw = prop_id(lease_fd, plane_id, DRM_MODE_OBJECT_PLANE, "CRTC_W");
		p_ch = prop_id(lease_fd, plane_id, DRM_MODE_OBJECT_PLANE, "CRTC_H");
		if (!(p_conn_crtc && p_crtc_mode && p_crtc_active && p_fb && p_pcrtc)) {
			fprintf(stderr, "missing KMS properties; falling back to legacy\n");
			atomic = 0;
		}
	}

	if (atomic) {
		drmModeAtomicReq *req = drmModeAtomicAlloc();
		drmModeAtomicAddProperty(req, hmd_conn_id, p_conn_crtc, crtc_id);
		drmModeAtomicAddProperty(req, crtc_id, p_crtc_mode, blob_id);
		drmModeAtomicAddProperty(req, crtc_id, p_crtc_active, 1);
		drmModeAtomicAddProperty(req, plane_id, p_fb, fbs[0].fb_id);
		drmModeAtomicAddProperty(req, plane_id, p_pcrtc, crtc_id);
		drmModeAtomicAddProperty(req, plane_id, p_sx, 0);
		drmModeAtomicAddProperty(req, plane_id, p_sy, 0);
		drmModeAtomicAddProperty(req, plane_id, p_sw, (uint64_t)mode.hdisplay << 16);
		drmModeAtomicAddProperty(req, plane_id, p_sh, (uint64_t)mode.vdisplay << 16);
		drmModeAtomicAddProperty(req, plane_id, p_cx, 0);
		drmModeAtomicAddProperty(req, plane_id, p_cy, 0);
		drmModeAtomicAddProperty(req, plane_id, p_cw, mode.hdisplay);
		drmModeAtomicAddProperty(req, plane_id, p_ch, mode.vdisplay);
		int r = drmModeAtomicCommit(lease_fd, req, DRM_MODE_ATOMIC_ALLOW_MODESET, NULL);
		drmModeAtomicFree(req);
		if (r) {
			printf("\n>>> ATOMIC commit REJECTED: %s\n", strerror(errno));
			printf(">>> falling back to legacy SetCrtc\n");
			atomic = 0;
		} else {
			printf("\n>>> ATOMIC modeset accepted\n");
		}
	}

	if (!atomic) {
		if (drmModeSetCrtc(lease_fd, crtc_id, fbs[0].fb_id, 0, 0, &hmd_conn_id, 1, &mode)) {
			printf("\n>>> drmModeSetCrtc REJECTED: %s\n", strerror(errno));
			printf(">>> the driver didn't accept this modeline: it never made it out over the cable\n");
			return 1;
		}
		printf("\n>>> legacy modeset accepted\n");
	}

	const char *panel_cmd = getenv("HMD_PANEL_CMD");
	if (!panel_cmd) panel_cmd = "./scripts/panel.py activate";
	printf(">>> activating panel: %s\n", panel_cmd);
	if (system(panel_cmd) != 0) fprintf(stderr, "  (panel activation failed)\n");

	drmModeCrtc *got = drmModeGetCrtc(lease_fd, crtc_id);
	if (got) {
		printf(">>> CRTC read back: mode_valid=%d  %ux%u  fb=%u\n",
		       got->mode_valid, got->mode.hdisplay, got->mode.vdisplay, got->buffer_id);
	}

	// --- page flips: measures whether the CRTC is actually scanning out ---
	printf(">>> flipping for %d s. LOOK INSIDE THE HEADSET.\n", secs);
	printf(">>> flashing orange/blue with white stripes = locked on\n");
	printf(">>> HP logo, black, or nothing = didn't lock on\n\n");
	fflush(stdout);

	drmEventContext ev = { .version = 2, .page_flip_handler = on_flip };
	double t0 = now_s(), last = t0, resent = 0;
	int cur = 0, last_flips = 0, flip_err = 0;

	while (now_s() - t0 < secs) {
		if (!pending) {
			cur ^= 1;
			int r;
			if (atomic) {
				drmModeAtomicReq *fr = drmModeAtomicAlloc();
				drmModeAtomicAddProperty(fr, plane_id, p_fb, fbs[cur].fb_id);
				r = drmModeAtomicCommit(lease_fd, fr,
				                        DRM_MODE_ATOMIC_NONBLOCK |
				                        DRM_MODE_PAGE_FLIP_EVENT, NULL);
				drmModeAtomicFree(fr);
			} else {
				r = drmModePageFlip(lease_fd, crtc_id, fbs[cur].fb_id,
				                    DRM_MODE_PAGE_FLIP_EVENT, NULL);
			}
			if (r) {
				if (!flip_err++)
					printf("  flip (%s) failed: %s\n",
					       atomic ? "atomic" : "legacy", strerror(errno));
			} else {
				pending = 1;
			}
		}
		struct pollfd pfd = { .fd = lease_fd, .events = POLLIN };
		if (poll(&pfd, 1, 200) > 0)
			drmHandleEvent(lease_fd, &ev);

		double t = now_s();
		// Monado resends the screen-enable once everything has settled, because the
		// companion can re-enumerate and eat the first one. Same trick.
		if (resent == 0 && t - t0 > 2.5) {
			resent = t;
			const char *on = getenv("HMD_PANEL_ON_CMD");
			if (!on) on = "./scripts/panel.py on";
			system(on);
			printf("  [%.1fs] screen-enable resent\n", t - t0);
			fflush(stdout);
		}
		if (t - last >= 2.0) {
			printf("  [%5.1fs] %.2f flips/s  (target %.2f Hz)\n",
			       t - t0, (flips - last_flips) / (t - last), target_hz);
			fflush(stdout);
			last = t;
			last_flips = flips;
		}
	}

	double dur = now_s() - t0;
	printf("\nsummary: %d flips in %.1f s = %.2f Hz measured (target %.2f)\n",
	       flips, dur, flips / dur, target_hz);
	if (flip_err)
		printf("  %d page flips failed\n", flip_err);
	if (flips < 5)
		printf("  !! almost no flips: the CRTC is NOT scanning out\n");
	return 0;
}
