#!/bin/bash
# Build Hyprland v0.50.1 + its hypr* libraries into ~/vr/hyprland-build/prefix (user-space; nothing system-wide).
W=$HOME/vr/hyprland-build; P=$W/prefix; mkdir -p $W/src $P; exec >$W/build.log 2>&1
export CC=clang-19 CXX=clang++-19 PKG_CONFIG_PATH=$P/lib/pkgconfig:$P/share/pkgconfig PATH=$P/bin:$PATH LD_LIBRARY_PATH=$P/lib CMAKE_PREFIX_PATH=$P
fail(){ echo "FAILED at: $1"; echo "$1" > $W/.failed; exit 1; }
declare -A TAG=([hyprwayland-scanner]=v0.4.5 [hyprutils]=v0.8.1 [hyprlang]=v0.6.3 [hyprland-protocols]=v0.6.4 [hyprgraphics]=v0.1.5 [hyprcursor]=v0.1.12 [aquamarine]=v0.9.2)
tagfor(){ echo ${TAG[$1]}; }
build(){ # name tag [extra cmake args]
  n=$1; t=$2; shift 2
  [ -d $W/src/$n ] || git clone -q --depth 1 --branch $t https://github.com/hyprwm/$n.git $W/src/$n || fail "clone $n $t"
  echo "=== $n $t"
  if [ -f $W/src/$n/meson.build ] && [ ! -f $W/src/$n/CMakeLists.txt ]; then
    meson setup $W/src/$n/build $W/src/$n --prefix=$P >$W/$n.cfg.log 2>&1 && ninja -C $W/src/$n/build install >$W/$n.build.log 2>&1 || fail "meson $n"; return
  fi
  cmake -S $W/src/$n -B $W/src/$n/build -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=$P "$@" >$W/$n.cfg.log 2>&1 || { tail -15 $W/$n.cfg.log; fail "configure $n"; }
  cmake --build $W/src/$n/build -j6 >$W/$n.build.log 2>&1 || { grep -m5 -E "error" $W/$n.build.log; fail "build $n"; }
  cmake --install $W/src/$n/build >/dev/null 2>&1 || fail "install $n"
}
for n in hyprwayland-scanner hyprutils hyprlang hyprland-protocols hyprgraphics hyprcursor aquamarine; do
  t=$(tagfor $n); echo "$n -> $t"; build $n $t -DBUILD_TESTING=OFF
done
build Hyprland v0.50.1 -DNO_XWAYLAND=true -DNO_UWSM=true -DNO_HYPRPM=true -DBUILD_TESTING=OFF
echo OK > $W/.done; ls -l $P/bin/Hyprland
