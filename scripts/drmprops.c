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
                // EDID byte count alone is NOT a health signal -- desktop monitors on this
                // rig also report a plain 128-byte base block with a perfectly good mode
                // list (no DisplayID extension needed for an ordinary monitor). What DOES
                // identify the G2 unambiguously is its EDID manufacturer+product ID, a
                // fixed fingerprint read straight from a known-good capture
                // (forum-attachments/g2-edid.bin): mfg "HPN" (bytes 8-9 = 0x22 0x0e),
                // product 0x36c1 (bytes 10-11, LE). Connector IDs reshuffle across boots;
                // this doesn't.
                if (!strcmp(pr->name, "EDID")) {
                    if (props->prop_values[p]) {
                        drmModePropertyBlobRes *blob =
                            drmModeGetPropertyBlob(fd, props->prop_values[p]);
                        int is_g2 = 0;
                        if (blob && blob->length >= 12) {
                            const unsigned char *d = blob->data;
                            unsigned mfg = (d[8] << 8) | d[9];
                            unsigned prod = d[10] | (d[11] << 8);
                            is_g2 = (mfg == 0x220e && prod == 0x36c1);
                        }
                        printf("    EDID         = %u bytes%s\n",
                               blob ? blob->length : 0,
                               is_g2 ? " (fingerprint matches the G2 panel)" : "");
                        if (blob && blob->length >= 16) {
                            const unsigned char *d = blob->data;
                            printf("    EDID[0:16]   =");
                            for (int k = 0; k < 16; k++) printf(" %02x", d[k]);
                            printf("\n");
                        }
                        if (blob) drmModeFreePropertyBlob(blob);
                    } else {
                        printf("    EDID         = 0 bytes (no blob at all)\n");
                    }
                }
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
