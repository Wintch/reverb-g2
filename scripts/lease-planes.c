// ¿El lease incluye un PLANO? Si no, SetCrtc "anda" pero no hay nada que escanear.
#define _GNU_SOURCE
#include <stdio.h>
#include <string.h>
#include <wayland-client.h>
#include <xf86drm.h>
#include <xf86drmMode.h>
#include "drm-lease-v1-client-protocol.h"
static struct wp_drm_lease_device_v1 *dev; static struct wp_drm_lease_connector_v1 *cn;
static int lfd=-1,done; static uint32_t cid;
static void n(void*d,struct wp_drm_lease_connector_v1*c,const char*s){(void)d;(void)c;(void)s;}
static void de(void*d,struct wp_drm_lease_connector_v1*c,const char*s){(void)d;(void)c;(void)s;}
static void i(void*d,struct wp_drm_lease_connector_v1*c,uint32_t x){(void)d;(void)c;cid=x;}
static void dn(void*d,struct wp_drm_lease_connector_v1*c){(void)d;(void)c;}
static void w(void*d,struct wp_drm_lease_connector_v1*c){(void)d;(void)c;}
static const struct wp_drm_lease_connector_v1_listener CL={n,de,i,dn,w};
static void df(void*d,struct wp_drm_lease_device_v1*v,int f){(void)d;(void)v;(void)f;}
static void dc(void*d,struct wp_drm_lease_device_v1*v,struct wp_drm_lease_connector_v1*c){
 (void)d;(void)v; if(cn){wp_drm_lease_connector_v1_destroy(c);return;} cn=c;
 wp_drm_lease_connector_v1_add_listener(c,&CL,NULL);}
static void dd(void*d,struct wp_drm_lease_device_v1*v){(void)d;(void)v;}
static void dr(void*d,struct wp_drm_lease_device_v1*v){(void)d;(void)v;}
static const struct wp_drm_lease_device_v1_listener DL={df,dc,dd,dr};
static void lf(void*d,struct wp_drm_lease_v1*l,int f){(void)d;(void)l;lfd=f;done=1;}
static void lfi(void*d,struct wp_drm_lease_v1*l){(void)d;(void)l;done=1;}
static const struct wp_drm_lease_v1_listener LL={lf,lfi};
static void ra(void*d,struct wl_registry*r,uint32_t nm,const char*ifc,uint32_t v){(void)d;(void)v;
 if(!strcmp(ifc,wp_drm_lease_device_v1_interface.name)){
  dev=wl_registry_bind(r,nm,&wp_drm_lease_device_v1_interface,1);
  wp_drm_lease_device_v1_add_listener(dev,&DL,NULL);}}
static void rd(void*d,struct wl_registry*r,uint32_t n){(void)d;(void)r;(void)n;}
static const struct wl_registry_listener RL={ra,rd};
int main(void){
 struct wl_display*dp=wl_display_connect(NULL); if(!dp){puts("sin wayland");return 1;}
 struct wl_registry*rg=wl_display_get_registry(dp);
 wl_registry_add_listener(rg,&RL,NULL);
 wl_display_roundtrip(dp); wl_display_roundtrip(dp); wl_display_roundtrip(dp);
 if(!cn){puts("sin conector arrendable");return 1;}
 struct wp_drm_lease_request_v1*rq=wp_drm_lease_device_v1_create_lease_request(dev);
 wp_drm_lease_request_v1_request_connector(rq,cn);
 struct wp_drm_lease_v1*ls=wp_drm_lease_request_v1_submit(rq);
 wp_drm_lease_v1_add_listener(ls,&LL,NULL);
 while(!done) if(wl_display_dispatch(dp)<0) break;
 if(lfd<0){puts("lease negado");return 1;}
 printf("lease fd=%d  conector=%u\n",lfd,cid);
 drmModeRes*r=drmModeGetResources(lfd);
 printf("recursos del lease: %d crtcs, %d conectores, %d encoders\n",
        r?r->count_crtcs:-1, r?r->count_connectors:-1, r?r->count_encoders:-1);
 printf("cap UNIVERSAL_PLANES: %d\n", drmSetClientCap(lfd,DRM_CLIENT_CAP_UNIVERSAL_PLANES,1));
 printf("cap ATOMIC         : %d\n", drmSetClientCap(lfd,DRM_CLIENT_CAP_ATOMIC,1));
 drmModePlaneRes*pr=drmModeGetPlaneResources(lfd);
 if(!pr){puts("drmModeGetPlaneResources fallo");return 1;}
 printf(">>> PLANOS EN EL LEASE: %u\n",pr->count_planes);
 for(uint32_t k=0;k<pr->count_planes;k++){
  drmModePlane*pl=drmModeGetPlane(lfd,pr->planes[k]);
  if(pl){printf("   plano %u  crtc=%u  possible_crtcs=0x%x  formatos=%u\n",
                pl->plane_id,pl->crtc_id,pl->possible_crtcs,pl->count_formats);}
 }
 return 0;}
