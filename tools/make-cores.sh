#!/bin/bash
# make-cores.sh — build the pinned libretro core bundle Pero OS ships.
#
# RetroArch comes from Debian (1.20.0). The cores Debian lacks are taken from
# libretro's *stable* 1.20.0 build, not from nightly: a core built the same day
# as the frontend, the same for every ISO and every pero-update. PPSSPP's own
# files (fonts, system dialogs) come from the PPSSPP release that core was
# built from, so they match it.
#
#   tools/make-cores.sh [out-dir]     → pero-cores-<ver>.tar.xz + .sha256
#
# The bundle is published once as the GitHub release "cores-<ver>"; build.sh and
# pero-update download it from there and check it against usr/share/pero/cores.sha256.

set -euo pipefail
VER=1.20.0
PPSSPP_TAG=v1.18.1
CORES="ppsspp pcsx_rearmed melondsds mupen64plus_next flycast fbneo fceumm"

OUT=$(realpath -m "${1:-out}")
WORK=${PERO_CORES_WORK:-/var/tmp/pero-cores}
mkdir -p "$OUT" "$WORK"
cd "$WORK"

[ -s RetroArch_cores.7z ] ||
	curl -fsSL -o RetroArch_cores.7z "https://buildbot.libretro.com/stable/$VER/linux/x86_64/RetroArch_cores.7z"
[ -s "ppsspp-$PPSSPP_TAG.tar.gz" ] ||
	curl -fsSL -o "ppsspp-$PPSSPP_TAG.tar.gz" "https://codeload.github.com/hrydgard/ppsspp/tar.gz/refs/tags/$PPSSPP_TAG"

rm -rf bundle && mkdir -p bundle/libretro bundle/system
P=RetroArch-Linux-x86_64/RetroArch-Linux-x86_64.AppImage.home/.config/retroarch/cores
for c in $CORES; do
	7z e -y -obundle/libretro RetroArch_cores.7z "$P/${c}_libretro.so" >/dev/null
	[ -s "bundle/libretro/${c}_libretro.so" ] || { echo "no $c in the $VER cores" >&2; exit 1; }
done
chmod 0644 bundle/libretro/*.so

# PPSSPP's assets folder is what RetroArch's system/PPSSPP holds
tar -xzf "ppsspp-$PPSSPP_TAG.tar.gz" -C bundle/system "ppsspp-${PPSSPP_TAG#v}/assets"
mv "bundle/system/ppsspp-${PPSSPP_TAG#v}/assets" bundle/system/PPSSPP
rmdir "bundle/system/ppsspp-${PPSSPP_TAG#v}"

printf 'retroarch %s\nppsspp-assets %s\ncores %s\n' "$VER" "$PPSSPP_TAG" "$CORES" >bundle/VERSION

NAME=pero-cores-$VER.tar.xz
tar -C bundle --owner=0 --group=0 --sort=name --mtime=@0 -cJf "$OUT/$NAME" .
(cd "$OUT" && sha256sum "$NAME" >"$NAME.sha256")
ls -l "$OUT/$NAME"
cat "$OUT/$NAME.sha256"
