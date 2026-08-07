// Lists DRM connectors and their properties relevant to DRM lease for an HMD.
// What matters: "non-desktop" = 1 makes the compositor NOT use it as a monitor and
// offer it via wp_drm_lease_v1. If the G2 doesn't have it, patch 0002 isn't taking
// effect on this path and Monado will never see a leasable connector.
#include <stdio.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <xf86drm.h>
#include <xf86drmMode.h>

int main(int argc, char **argv) {
    const char *path = argc > 1 ? argv[1] : "/dev/dri/card0";
    int fd = open(path, O_RDWR);
    if (fd < 0) { perror(path); return 1; }

    drmModeRes *res = drmModeGetResources(fd);
    if (!res) { perror("drmModeGetResources"); close(fd); return 1; }

    for (int i = 0; i < res->count_connectors; i++) {
        drmModeConnector *c = drmModeGetConnector(fd, res->connectors[i]);
        if (!c) continue;

        printf("connector %u  type=%d  %s  modes=%d\n",
               c->connector_id, c->connector_type,
               c->connection == DRM_MODE_CONNECTED ? "CONNECTED" : "disconnected",
               c->count_modes);

        drmModeObjectProperties *props = drmModeObjectGetProperties(
            fd, c->connector_id, DRM_MODE_OBJECT_CONNECTOR);
        if (props) {
            for (uint32_t p = 0; p < props->count_props; p++) {
                drmModePropertyRes *pr = drmModeGetProperty(fd, props->props[p]);
                if (!pr) continue;
                if (!strcmp(pr->name, "non-desktop") || !strcmp(pr->name, "DPMS") ||
                    !strcmp(pr->name, "link-status"))
                    printf("    %-12s = %llu\n", pr->name,
                           (unsigned long long)props->prop_values[p]);
                drmModeFreeProperty(pr);
            }
            drmModeFreeObjectProperties(props);
        }
        // The first modes, to identify the headset by its resolution
        for (int m = 0; m < c->count_modes && m < 3; m++)
            printf("    mode: %dx%d@%d\n", c->modes[m].hdisplay,
                   c->modes[m].vdisplay, c->modes[m].vrefresh);
        drmModeFreeConnector(c);
    }
    drmModeFreeResources(res);
    close(fd);
    return 0;
}
