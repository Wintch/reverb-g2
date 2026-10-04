# jack-in-fence-ab.sh is jack-in-wayland.sh with a selectable service binary. Generate it with:
#   sed "s|^SERVICE=.*|SERVICE=\"\${MONADO_SERVICE:-\$VR/monado/build/src/xrt/targets/service/monado-service}\"|" ~/vr/jack-in-wayland.sh > ~/vr/jack-in-fence-ab.sh
