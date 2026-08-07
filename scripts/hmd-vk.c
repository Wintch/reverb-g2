// hmd-vk — drives the headset panel through the SAME path as Monado: Vulkan display,
// not KMS. Useful for requesting modes that aren't in the EDID and sweeping refresh rates.
//
//   ./hmd-vk list                    lists the modes VULKAN reports (not the EDID)
//   ./hmd-vk native <idx> [secs]     uses a mode exactly as Vulkan reports it
//   ./hmd-vk custom <w> <h> <mHz>    ARBITRARY mode via vkCreateDisplayModeKHR
//                             [secs] e.g.: custom 2880 1440 75000  -> 75.000 Hz
//
//   secs = 0  ->  keeps the image up INDEFINITELY until you kill it.
//                 This is the default on purpose: a physical test can't time out while the
//                 user is looking at it or before they respond. This has happened before and
//                 contaminated results.
//
// WHY VULKAN AND NOT KMS (measured, see ch. 04):
// The previous attempt did a modeset via DRM lease with KMS ioctls. NVIDIA accepts EVERYTHING
// (SetCrtc, AtomicCommit with ALLOW_MODESET, mode_valid=1 on readback) and nothing comes out
// over the cable: the panel stays on the HP logo even with the 60Hz mode that Monado drives
// perfectly. In the NVIDIA driver, DRM/KMS is a partial layer for displays in
// direct-mode; the hardware is actually programmed by nvidia-modeset via the Vulkan path.
// Monado uses VK_EXT_acquire_drm_display + VK_KHR_display + VK_EXT_direct_mode_display, so
// this does the same thing.
//
// The display is obtained via wp_drm_lease_v1 (the connector is non-desktop, the compositor
// doesn't use it), and that leased fd is passed to vkGetDrmDisplayEXT/vkAcquireDrmDisplayEXT.
// No need to switch VTs or stop GNOME, and no desktop monitor is touched.
//
// Verification is still PHYSICAL. You have to look inside the headset.

#define _GNU_SOURCE
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <wayland-client.h>
#include <vulkan/vulkan.h>
#include "drm-lease-v1-client-protocol.h"

#define VKCHK(x, msg)                                                                      \
	do {                                                                               \
		VkResult _r = (x);                                                         \
		if (_r != VK_SUCCESS) {                                                    \
			fprintf(stderr, "%s: VkResult %d\n", (msg), _r);                    \
			return 1;                                                          \
		}                                                                          \
	} while (0)

// ---- lease (same mechanism as hmd-modeset.c) ------------------------------------------

static struct wp_drm_lease_device_v1 *lease_dev;
static struct wp_drm_lease_connector_v1 *hmd_conn;
static int lease_fd = -1, lease_done;
static uint32_t hmd_conn_id;
static char hmd_name[64];

static void c_name(void *d, struct wp_drm_lease_connector_v1 *c, const char *n)
{ (void)d; (void)c; snprintf(hmd_name, sizeof(hmd_name), "%s", n); }
static void c_desc(void *d, struct wp_drm_lease_connector_v1 *c, const char *s)
{ (void)d; (void)c; (void)s; }
static void c_id(void *d, struct wp_drm_lease_connector_v1 *c, uint32_t id)
{ (void)d; (void)c; hmd_conn_id = id; }
static void c_done(void *d, struct wp_drm_lease_connector_v1 *c) { (void)d; (void)c; }
static void c_wd(void *d, struct wp_drm_lease_connector_v1 *c) { (void)d; (void)c; }
static const struct wp_drm_lease_connector_v1_listener CL = { c_name, c_desc, c_id, c_done, c_wd };

static void d_fd(void *d, struct wp_drm_lease_device_v1 *v, int fd)
{ (void)d; (void)v; (void)fd; }
static void d_conn(void *d, struct wp_drm_lease_device_v1 *v,
                   struct wp_drm_lease_connector_v1 *c)
{
	(void)d; (void)v;
	if (hmd_conn) { wp_drm_lease_connector_v1_destroy(c); return; }
	hmd_conn = c;
	wp_drm_lease_connector_v1_add_listener(c, &CL, NULL);
}
static void d_done(void *d, struct wp_drm_lease_device_v1 *v) { (void)d; (void)v; }
static void d_rel(void *d, struct wp_drm_lease_device_v1 *v) { (void)d; (void)v; }
static const struct wp_drm_lease_device_v1_listener DL = { d_fd, d_conn, d_done, d_rel };

static void l_fd(void *d, struct wp_drm_lease_v1 *l, int fd)
{ (void)d; (void)l; lease_fd = fd; lease_done = 1; }
static void l_fin(void *d, struct wp_drm_lease_v1 *l)
{ (void)d; (void)l; lease_done = 1; }
static const struct wp_drm_lease_v1_listener LL = { l_fd, l_fin };

static void reg_add(void *d, struct wl_registry *r, uint32_t nm, const char *i, uint32_t v)
{
	(void)d; (void)v;
	if (!strcmp(i, wp_drm_lease_device_v1_interface.name)) {
		lease_dev = wl_registry_bind(r, nm, &wp_drm_lease_device_v1_interface, 1);
		wp_drm_lease_device_v1_add_listener(lease_dev, &DL, NULL);
	}
}
static void reg_del(void *d, struct wl_registry *r, uint32_t n) { (void)d; (void)r; (void)n; }
static const struct wl_registry_listener RL = { reg_add, reg_del };

static int get_lease(void)
{
	struct wl_display *dpy = wl_display_connect(NULL);
	if (!dpy) { fprintf(stderr, "no Wayland session\n"); return -1; }
	struct wl_registry *reg = wl_display_get_registry(dpy);
	wl_registry_add_listener(reg, &RL, NULL);
	wl_display_roundtrip(dpy);
	if (!lease_dev) { fprintf(stderr, "compositor doesn't offer wp_drm_lease_device_v1\n"); return -1; }
	wl_display_roundtrip(dpy);
	wl_display_roundtrip(dpy);
	if (!hmd_conn) { fprintf(stderr, "compositor doesn't offer leasable connectors\n"); return -1; }
	printf("connector: %s (id %u)\n", hmd_name, hmd_conn_id);

	struct wp_drm_lease_request_v1 *rq = wp_drm_lease_device_v1_create_lease_request(lease_dev);
	wp_drm_lease_request_v1_request_connector(rq, hmd_conn);
	struct wp_drm_lease_v1 *ls = wp_drm_lease_request_v1_submit(rq);
	wp_drm_lease_v1_add_listener(ls, &LL, NULL);
	while (!lease_done)
		if (wl_display_dispatch(dpy) < 0) break;
	if (lease_fd < 0) { fprintf(stderr, "compositor DENIED the lease\n"); return -1; }
	printf("lease OK (fd %d)\n", lease_fd);
	return lease_fd;
}

// ---- utilities -------------------------------------------------------------------------

static double now_s(void)
{
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	return ts.tv_sec + ts.tv_nsec / 1e9;
}

static void activate_panel(void)
{
	const char *cmd = getenv("HMD_PANEL_CMD");
	if (!cmd) cmd = "./scripts/panel.py activate";
	printf(">>> activating panel: %s\n", cmd);
	fflush(stdout);
	if (system(cmd) != 0) fprintf(stderr, "  (panel activation failed)\n");
}

// ---- main --------------------------------------------------------------------------------

int main(int argc, char **argv)
{
	if (argc < 2) {
		fprintf(stderr,
		        "usage: %s list | native <idx> [secs] | custom <w> <h> <mHz> [secs]\n"
		        "     secs=0 (default) keeps the image up until you kill it\n", argv[0]);
		return 2;
	}
	int do_list = !strcmp(argv[1], "list");
	int do_native = !strcmp(argv[1], "native");
	int do_custom = !strcmp(argv[1], "custom");
	if (!do_list && !do_native && !do_custom) { fprintf(stderr, "unknown command\n"); return 2; }

	int fd = get_lease();
	if (fd < 0) return 1;

	// --- instance ---
	const char *inst_exts[] = {
		VK_KHR_SURFACE_EXTENSION_NAME,
		VK_KHR_DISPLAY_EXTENSION_NAME,
		VK_EXT_DIRECT_MODE_DISPLAY_EXTENSION_NAME,
		VK_EXT_ACQUIRE_DRM_DISPLAY_EXTENSION_NAME,
	};
	VkApplicationInfo app = { .sType = VK_STRUCTURE_TYPE_APPLICATION_INFO,
	                          .pApplicationName = "hmd-vk", .apiVersion = VK_API_VERSION_1_1 };
	VkInstanceCreateInfo ici = { .sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,
	                             .pApplicationInfo = &app,
	                             .enabledExtensionCount = 4,
	                             .ppEnabledExtensionNames = inst_exts };
	VkInstance inst;
	VKCHK(vkCreateInstance(&ici, NULL, &inst), "vkCreateInstance");

	PFN_vkGetDrmDisplayEXT p_GetDrmDisplay =
	    (PFN_vkGetDrmDisplayEXT)vkGetInstanceProcAddr(inst, "vkGetDrmDisplayEXT");
	PFN_vkAcquireDrmDisplayEXT p_AcquireDrmDisplay =
	    (PFN_vkAcquireDrmDisplayEXT)vkGetInstanceProcAddr(inst, "vkAcquireDrmDisplayEXT");
	if (!p_GetDrmDisplay || !p_AcquireDrmDisplay) {
		fprintf(stderr, "missing vkGetDrmDisplayEXT / vkAcquireDrmDisplayEXT\n");
		return 1;
	}

	uint32_t ndev = 0;
	vkEnumeratePhysicalDevices(inst, &ndev, NULL);
	if (!ndev) { fprintf(stderr, "no Vulkan devices\n"); return 1; }
	VkPhysicalDevice *devs = calloc(ndev, sizeof(*devs));
	vkEnumeratePhysicalDevices(inst, &ndev, devs);

	// The leased display is only visible to the GPU driving it: we try until one claims it.
	VkPhysicalDevice phys = VK_NULL_HANDLE;
	VkDisplayKHR display = VK_NULL_HANDLE;
	for (uint32_t i = 0; i < ndev; i++) {
		VkPhysicalDeviceProperties pp;
		vkGetPhysicalDeviceProperties(devs[i], &pp);
		VkDisplayKHR d = VK_NULL_HANDLE;
		VkResult r = p_GetDrmDisplay(devs[i], fd, hmd_conn_id, &d);
		printf("  GPU '%s': vkGetDrmDisplayEXT -> %d\n", pp.deviceName, r);
		if (r == VK_SUCCESS && d != VK_NULL_HANDLE) { phys = devs[i]; display = d; break; }
	}
	if (!phys) { fprintf(stderr, "no GPU could claim connector %u\n", hmd_conn_id); return 1; }
	VKCHK(p_AcquireDrmDisplay(phys, fd, display), "vkAcquireDrmDisplayEXT");
	printf("display acquired by Vulkan\n");

	// --- modes reported by VULKAN (note: may differ from the EDID) ---
	uint32_t nmodes = 0;
	vkGetDisplayModePropertiesKHR(phys, display, &nmodes, NULL);
	VkDisplayModePropertiesKHR *modes = calloc(nmodes ? nmodes : 1, sizeof(*modes));
	vkGetDisplayModePropertiesKHR(phys, display, &nmodes, modes);
	printf("\nmodes reported by Vulkan (%u):\n", nmodes);
	for (uint32_t i = 0; i < nmodes; i++) {
		VkDisplayModeParametersKHR p = modes[i].parameters;
		printf("  [%u] %ux%u @ %.3f Hz  (refreshRate=%u mHz)\n", i,
		       p.visibleRegion.width, p.visibleRegion.height,
		       p.refreshRate / 1000.0, p.refreshRate);
	}
	if (do_list) return 0;

	// --- choose/create the mode ---
	VkDisplayModeKHR mode = VK_NULL_HANDLE;
	VkExtent2D extent;
	uint32_t refresh_mhz;
	int secs = 0;

	if (do_native) {
		uint32_t idx = argc > 2 ? (uint32_t)atoi(argv[2]) : 0;
		if (argc > 3) secs = atoi(argv[3]);
		if (idx >= nmodes) { fprintf(stderr, "index out of range\n"); return 2; }
		mode = modes[idx].displayMode;
		extent = modes[idx].parameters.visibleRegion;
		refresh_mhz = modes[idx].parameters.refreshRate;
		printf("\nNATIVE mode [%u] from Vulkan\n", idx);
	} else {
		if (argc < 5) { fprintf(stderr, "usage: custom <w> <h> <mHz> [secs]\n"); return 2; }
		extent.width = (uint32_t)atoi(argv[2]);
		extent.height = (uint32_t)atoi(argv[3]);
		refresh_mhz = (uint32_t)atoi(argv[4]);
		if (argc > 5) secs = atoi(argv[5]);
		VkDisplayModeCreateInfoKHR mci = {
			.sType = VK_STRUCTURE_TYPE_DISPLAY_MODE_CREATE_INFO_KHR,
			.parameters = { .visibleRegion = extent, .refreshRate = refresh_mhz },
		};
		VkResult r = vkCreateDisplayModeKHR(phys, display, &mci, NULL, &mode);
		if (r != VK_SUCCESS) {
			printf("\n>>> vkCreateDisplayModeKHR REJECTED: VkResult %d\n", r);
			printf(">>> the driver does not accept %ux%u @ %.3f Hz\n",
			       extent.width, extent.height, refresh_mhz / 1000.0);
			printf(">>> (this IS ALREADY a result: it shows where the limit is)\n");
			return 1;
		}
		printf("\n>>> CUSTOM mode accepted by the driver: %ux%u @ %.3f Hz\n",
		       extent.width, extent.height, refresh_mhz / 1000.0);
	}

	// --- plane and surface ---
	uint32_t nplanes = 0;
	vkGetPhysicalDeviceDisplayPlanePropertiesKHR(phys, &nplanes, NULL);
	VkDisplayPlanePropertiesKHR *planes = calloc(nplanes ? nplanes : 1, sizeof(*planes));
	vkGetPhysicalDeviceDisplayPlanePropertiesKHR(phys, &nplanes, planes);

	uint32_t plane_idx = UINT32_MAX, plane_stack = 0;
	for (uint32_t i = 0; i < nplanes; i++) {
		uint32_t nsup = 0;
		vkGetDisplayPlaneSupportedDisplaysKHR(phys, i, &nsup, NULL);
		if (!nsup) continue;
		VkDisplayKHR *sup = calloc(nsup, sizeof(*sup));
		vkGetDisplayPlaneSupportedDisplaysKHR(phys, i, &nsup, sup);
		for (uint32_t k = 0; k < nsup; k++)
			if (sup[k] == display) { plane_idx = i; plane_stack = planes[i].currentStackIndex; }
		free(sup);
		if (plane_idx != UINT32_MAX) break;
	}
	if (plane_idx == UINT32_MAX) { fprintf(stderr, "no plane supports this display\n"); return 1; }
	printf("plane %u (stack %u)\n", plane_idx, plane_stack);

	VkDisplayPlaneCapabilitiesKHR caps;
	vkGetDisplayPlaneCapabilitiesKHR(phys, mode, plane_idx, &caps);
	VkDisplayPlaneAlphaFlagBitsKHR alpha =
	    (caps.supportedAlpha & VK_DISPLAY_PLANE_ALPHA_OPAQUE_BIT_KHR)
	        ? VK_DISPLAY_PLANE_ALPHA_OPAQUE_BIT_KHR
	        : VK_DISPLAY_PLANE_ALPHA_GLOBAL_BIT_KHR;

	VkDisplaySurfaceCreateInfoKHR sci = {
		.sType = VK_STRUCTURE_TYPE_DISPLAY_SURFACE_CREATE_INFO_KHR,
		.displayMode = mode,
		.planeIndex = plane_idx,
		.planeStackIndex = plane_stack,
		.transform = VK_SURFACE_TRANSFORM_IDENTITY_BIT_KHR,
		.globalAlpha = 1.0f,
		.alphaMode = alpha,
		.imageExtent = extent,
	};
	VkSurfaceKHR surface;
	VKCHK(vkCreateDisplayPlaneSurfaceKHR(inst, &sci, NULL, &surface), "vkCreateDisplayPlaneSurfaceKHR");

	// --- device + swapchain ---
	uint32_t nq = 0;
	vkGetPhysicalDeviceQueueFamilyProperties(phys, &nq, NULL);
	VkQueueFamilyProperties *qf = calloc(nq, sizeof(*qf));
	vkGetPhysicalDeviceQueueFamilyProperties(phys, &nq, qf);
	uint32_t qi = UINT32_MAX;
	for (uint32_t i = 0; i < nq; i++) {
		VkBool32 present = VK_FALSE;
		vkGetPhysicalDeviceSurfaceSupportKHR(phys, i, surface, &present);
		if ((qf[i].queueFlags & VK_QUEUE_GRAPHICS_BIT) && present) { qi = i; break; }
	}
	if (qi == UINT32_MAX) { fprintf(stderr, "no graphics queue that can present\n"); return 1; }

	float prio = 1.0f;
	VkDeviceQueueCreateInfo qci = { .sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
	                                .queueFamilyIndex = qi, .queueCount = 1,
	                                .pQueuePriorities = &prio };
	const char *dev_exts[] = { VK_KHR_SWAPCHAIN_EXTENSION_NAME };
	VkDeviceCreateInfo dci = { .sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,
	                           .queueCreateInfoCount = 1, .pQueueCreateInfos = &qci,
	                           .enabledExtensionCount = 1, .ppEnabledExtensionNames = dev_exts };
	VkDevice dev;
	VKCHK(vkCreateDevice(phys, &dci, NULL, &dev), "vkCreateDevice");
	VkQueue queue;
	vkGetDeviceQueue(dev, qi, 0, &queue);

	VkSurfaceCapabilitiesKHR scaps;
	vkGetPhysicalDeviceSurfaceCapabilitiesKHR(phys, surface, &scaps);
	uint32_t nfmt = 0;
	vkGetPhysicalDeviceSurfaceFormatsKHR(phys, surface, &nfmt, NULL);
	VkSurfaceFormatKHR *fmts = calloc(nfmt ? nfmt : 1, sizeof(*fmts));
	vkGetPhysicalDeviceSurfaceFormatsKHR(phys, surface, &nfmt, fmts);

	// The G2's EDID does NOT declare a color depth (byte 0x14 = 0x80, "undefined"), so
	// the source picks one. NVIDIA on Linux falls back to 6 bits per color (nvidia-modeset logs
	// "18 bpp", and the headset reports 6 in byte 18 of its DEVICE_STATUS); Windows uses 8 and
	// works at 90Hz. HMD_VK_FORMAT lets you test whether the swapchain format moves that choice.
	printf("surface formats (%u):\n", nfmt);
	for (uint32_t i = 0; i < nfmt; i++)
		printf("  [%u] format=%d colorSpace=%d\n", i, fmts[i].format, fmts[i].colorSpace);
	uint32_t fmt_idx = 0;
	const char *fmt_env = getenv("HMD_VK_FORMAT");
	if (fmt_env) {
		uint32_t want = (uint32_t)atoi(fmt_env);
		if (want < nfmt) fmt_idx = want;
		else fprintf(stderr, "  HMD_VK_FORMAT=%u out of range, using 0\n", want);
	}
	printf("using format [%u] = %d\n", fmt_idx, fmts[fmt_idx].format);

	uint32_t nimg = scaps.minImageCount < 2 ? 2 : scaps.minImageCount;
	if (scaps.maxImageCount && nimg > scaps.maxImageCount) nimg = scaps.maxImageCount;

	VkSwapchainCreateInfoKHR swci = {
		.sType = VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR,
		.surface = surface,
		.minImageCount = nimg,
		.imageFormat = fmts[fmt_idx].format,
		.imageColorSpace = fmts[fmt_idx].colorSpace,
		.imageExtent = extent,
		.imageArrayLayers = 1,
		.imageUsage = VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT,
		.imageSharingMode = VK_SHARING_MODE_EXCLUSIVE,
		.preTransform = VK_SURFACE_TRANSFORM_IDENTITY_BIT_KHR,
		.compositeAlpha = VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR,
		.presentMode = VK_PRESENT_MODE_FIFO_KHR,
		.clipped = VK_TRUE,
	};
	VkSwapchainKHR swap;
	VKCHK(vkCreateSwapchainKHR(dev, &swci, NULL, &swap), "vkCreateSwapchainKHR");
	uint32_t nsi = 0;
	vkGetSwapchainImagesKHR(dev, swap, &nsi, NULL);
	VkImage *imgs = calloc(nsi, sizeof(*imgs));
	vkGetSwapchainImagesKHR(dev, swap, &nsi, imgs);
	printf("swapchain: %u images, format %d, %ux%u\n", nsi, fmts[fmt_idx].format,
	       extent.width, extent.height);

	VkCommandPoolCreateInfo pci = { .sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,
	                                .flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT,
	                                .queueFamilyIndex = qi };
	VkCommandPool pool;
	VKCHK(vkCreateCommandPool(dev, &pci, NULL, &pool), "vkCreateCommandPool");
	VkCommandBufferAllocateInfo cbi = { .sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
	                                    .commandPool = pool,
	                                    .level = VK_COMMAND_BUFFER_LEVEL_PRIMARY,
	                                    .commandBufferCount = 1 };
	VkCommandBuffer cmd;
	VKCHK(vkAllocateCommandBuffers(dev, &cbi, &cmd), "vkAllocateCommandBuffers");

	VkSemaphoreCreateInfo sem_ci = { .sType = VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO };
	VkSemaphore sem_acq, sem_done;
	vkCreateSemaphore(dev, &sem_ci, NULL, &sem_acq);
	vkCreateSemaphore(dev, &sem_ci, NULL, &sem_done);
	VkFenceCreateInfo fci = { .sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO };
	VkFence fence;
	vkCreateFence(dev, &fci, NULL, &fence);

	// --- first frame, and the panel IMMEDIATELY after ---
	printf("\n>>> presenting. ");
	if (secs > 0) printf("for %d s.\n", secs);
	else printf("INDEFINITELY (Ctrl-C or kill to stop).\n");
	printf(">>> you should see flat colors ALTERNATING (orange / blue / green).\n");
	printf(">>> HP logo, black, or nothing = didn't sync.\n\n");
	fflush(stdout);

	double t0 = now_s(), last = t0;
	uint64_t frames = 0, last_frames = 0;
	int activated = 0;

	// Three clearly distinct colors: if the panel syncs it's impossible to confuse it with "nothing".
	// NOTE: they alternate EVERY FRAME (at 90fps that's a 30Hz strobe by design) — they're useful
	// for "syncs/doesn't sync", NEVER for judging backlight flicker. For that,
	// HMD_VK_SOLID=1 paints solid white, zero source variation: any flicker you see there
	// is from the panel/backlight, not from the test.
	const VkClearColorValue COLORS[3] = {
		{ { 1.0f, 0.40f, 0.0f, 1.0f } },
		{ { 0.0f, 0.35f, 1.0f, 1.0f } },
		{ { 0.0f, 0.85f, 0.25f, 1.0f } },
	};
	const VkClearColorValue WHITE = { { 1.0f, 1.0f, 1.0f, 1.0f } };
	const int solid = getenv("HMD_VK_SOLID") != NULL;
	if (solid) printf(">>> HMD_VK_SOLID: solid white (backlight flicker test).\n");

	for (;;) {
		if (secs > 0 && now_s() - t0 >= secs) break;

		uint32_t idx;
		VkResult r = vkAcquireNextImageKHR(dev, swap, UINT64_MAX, sem_acq, VK_NULL_HANDLE, &idx);
		if (r != VK_SUCCESS && r != VK_SUBOPTIMAL_KHR) {
			fprintf(stderr, "vkAcquireNextImageKHR: %d\n", r);
			break;
		}

		vkResetCommandBuffer(cmd, 0);
		VkCommandBufferBeginInfo bi = { .sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO,
		                                .flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT };
		vkBeginCommandBuffer(cmd, &bi);

		VkImageSubresourceRange range = { VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1 };
		VkImageMemoryBarrier to_dst = {
			.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
			.oldLayout = VK_IMAGE_LAYOUT_UNDEFINED,
			.newLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
			.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
			.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
			.image = imgs[idx], .subresourceRange = range,
			.dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT,
		};
		vkCmdPipelineBarrier(cmd, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,
		                     VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 0, NULL, 0, NULL, 1, &to_dst);
		vkCmdClearColorImage(cmd, imgs[idx], VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,
		                     solid ? &WHITE : &COLORS[frames % 3], 1, &range);
		VkImageMemoryBarrier to_present = to_dst;
		to_present.oldLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;
		to_present.newLayout = VK_IMAGE_LAYOUT_PRESENT_SRC_KHR;
		to_present.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
		to_present.dstAccessMask = 0;
		vkCmdPipelineBarrier(cmd, VK_PIPELINE_STAGE_TRANSFER_BIT,
		                     VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT, 0, 0, NULL, 0, NULL,
		                     1, &to_present);
		vkEndCommandBuffer(cmd);

		VkPipelineStageFlags wait_stage = VK_PIPELINE_STAGE_TRANSFER_BIT;
		VkSubmitInfo si = { .sType = VK_STRUCTURE_TYPE_SUBMIT_INFO,
		                    .waitSemaphoreCount = 1, .pWaitSemaphores = &sem_acq,
		                    .pWaitDstStageMask = &wait_stage,
		                    .commandBufferCount = 1, .pCommandBuffers = &cmd,
		                    .signalSemaphoreCount = 1, .pSignalSemaphores = &sem_done };
		vkQueueSubmit(queue, 1, &si, fence);

		VkPresentInfoKHR pi = { .sType = VK_STRUCTURE_TYPE_PRESENT_INFO_KHR,
		                        .waitSemaphoreCount = 1, .pWaitSemaphores = &sem_done,
		                        .swapchainCount = 1, .pSwapchains = &swap,
		                        .pImageIndices = &idx };
		r = vkQueuePresentKHR(queue, &pi);
		if (r != VK_SUCCESS && r != VK_SUBOPTIMAL_KHR) {
			fprintf(stderr, "vkQueuePresentKHR: %d\n", r);
			break;
		}
		vkWaitForFences(dev, 1, &fence, VK_TRUE, UINT64_MAX);
		vkResetFences(dev, 1, &fence);
		frames++;

		// The panel turns itself off after ~3 s without a signal, so it's only turned on once
		// frames are actually going out -- and afterward the screen-enable is resent, like
		// Monado does, because the companion may re-enumerate and eat the first one.
		if (!activated && frames >= 2) { activated = 1; activate_panel(); }
		if (activated == 1 && now_s() - t0 > 4.0) {
			activated = 2;
			const char *on = getenv("HMD_PANEL_ON_CMD");
			if (!on) on = "./scripts/panel.py on";
			if (system(on) != 0) { /* not critical */ }
			printf("  [%.1fs] screen-enable resent\n", now_s() - t0);
			fflush(stdout);
		}

		double t = now_s();
		if (t - last >= 3.0) {
			printf("  [%6.1fs] %.2f fps presented  (requested mode %.3f Hz)\n",
			       t - t0, (frames - last_frames) / (t - last), refresh_mhz / 1000.0);
			fflush(stdout);
			last = t;
			last_frames = frames;
		}
	}

	double dur = now_s() - t0;
	printf("\nsummary: %llu frames in %.1f s = %.2f fps (requested mode %.3f Hz)\n",
	       (unsigned long long)frames, dur, frames / dur, refresh_mhz / 1000.0);
	return 0;
}
