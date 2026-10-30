#!/bin/bash
# Pero OS build script. Run as root on Debian 13 (or in WSL2 Debian).
#   sudo ./build.sh          build ISO into ./out/
#   sudo ./build.sh clean    wipe the build tree (keeps the package cache)
set -euo pipefail

SRC="${PERO_SRC:-$(cd "$(dirname "$0")" && pwd)}"
# live-build needs a Linux filesystem (chroot, device nodes, hardlinks) — never NTFS.
WORK="${PERO_WORK:-/var/tmp/pero-build}"
OUT="$SRC/out"

[ "$(id -u)" -eq 0 ] || { echo "Нужен root: sudo $0"; exit 1; }

if [ "${1:-}" = "clean" ]; then
	[ -d "$WORK" ] && (cd "$WORK" && lb clean --purge || true)
	rm -rf "$WORK"
	exit 0
fi

echo ">>> Зависимости сборки"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq live-build debootstrap xorriso squashfs-tools mtools dosfstools \
	grub-efi-amd64-bin grub-efi-ia32-bin grub-pc-bin librsvg2-bin fonts-inter git rsync curl unzip >/dev/null

echo ">>> Подготовка дерева в $WORK"
mkdir -p "$WORK"
rsync -a --delete --exclude cache --exclude chroot --exclude binary --exclude '.build' \
	--exclude 'config/*' --exclude '*.iso' "$SRC/auto" "$WORK/"
mkdir -p "$WORK/config"
rsync -a --delete "$SRC/config/" "$WORK/config.src/"
# Windows checkouts may bring CRLF and lose the executable bit
find "$WORK/auto" "$WORK/config.src/hooks" "$WORK/config.src/includes.chroot/usr/local/bin" "$WORK/config.src/includes.chroot/usr/local/sbin" \
	"$WORK/config.src/includes.chroot/usr/share/pero/calamares" -type f \
	-exec sed -i 's/\r$//' {} + -exec chmod +x {} +
find "$WORK/config.src" -type f \( -name '*.xml' -o -name '*.desktop' -o -name '*.rc' -o -name '*.conf' \
	-o -name '*.list.*' -o -name '*.override' -o -name '*.css' -o -name '*.desc' -o -name '*.qml' \) \
	-exec sed -i 's/\r$//' {} +
sed -i 's/\r$//' "$WORK/config.src/includes.chroot/etc/X11/Xsession.d/90pero-tablet" \
	"$WORK/config.src/includes.chroot/usr/share/pero/zramswap"

INC="$WORK/config.src/includes.chroot"

echo ">>> Графика: обои, логотип"
mkdir -p "$INC/usr/share/backgrounds/pero" "$INC/usr/share/pero" \
	"$INC/usr/share/icons/hicolor/scalable/apps" "$INC/etc/calamares/branding/pero"
rsvg-convert -w 1920 -h 1920 "$SRC/assets/wallpaper.svg" -o "$INC/usr/share/backgrounds/pero/pero-dark.png"
cp "$SRC/assets/logo.svg" "$INC/usr/share/icons/hicolor/scalable/apps/pero-logo.svg"
rsvg-convert -w 256 -h 256 "$SRC/assets/logo.svg" -o "$INC/etc/calamares/branding/pero/logo.png"
rsvg-convert -w 96 -h 96 "$SRC/assets/logo.svg" -o "$INC/usr/share/pero/greeter-logo.png"
rsvg-convert -w 1200 -h 560 "$SRC/assets/welcome.svg" -o "$INC/etc/calamares/branding/pero/welcome.png"
rsvg-convert -w 1200 -h 560 "$SRC/assets/welcome.svg" -o "$INC/etc/calamares/branding/pero/slide1.png"
rsvg-convert -w 800 -h 600 "$SRC/assets/grub-splash.svg" -o "$INC/usr/share/pero/grub-splash.png"

echo ">>> Прошивки Silead (onitake/gsl-firmware)"
GSL="$WORK/gsl-firmware"
if [ -d "$GSL/.git" ]; then git -C "$GSL" pull -q --ff-only || true
else git clone -q --depth 1 https://github.com/onitake/gsl-firmware "$GSL"; fi
mkdir -p "$INC/usr/lib/firmware/silead" "$INC/usr/share/pero/gsl-tools"
cp "$GSL"/firmware/linux/silead/*.fw "$INC/usr/lib/firmware/silead/"
cp "$GSL"/tools/scanwindrv "$GSL"/tools/fwtool "$GSL"/tools/LICENSE "$INC/usr/share/pero/gsl-tools/"

echo ">>> Игры: ядра libretro, которых нет в Debian (buildbot.libretro.com)"
# PSP, PS1, DS, N64, Dreamcast, arcades. Downloads are cached in $WORK/libretro.
BB=https://buildbot.libretro.com
LR="$WORK/libretro"
mkdir -p "$LR" "$INC/usr/lib/x86_64-linux-gnu/libretro" "$INC/usr/share/libretro/overlays" \
	"$INC/usr/share/libretro/autoconfig" "$INC/etc/skel/.config/retroarch/system"
for core in ppsspp pcsx_rearmed melonds mupen64plus_next flycast fbneo; do
	z="$LR/${core}_libretro.so.zip"
	[ -s "$z" ] || curl -fsSL -o "$z" "$BB/nightly/linux/x86_64/latest/${core}_libretro.so.zip"
	unzip -qo "$z" -d "$INC/usr/lib/x86_64-linux-gnu/libretro/"
done
for f in system/PPSSPP frontend/overlays frontend/autoconfig; do
	z="$LR/$(basename $f).zip"
	[ -s "$z" ] || curl -fsSL -o "$z" "$BB/assets/$f.zip"
done
# PPSSPP needs its font/flash0 files in the RetroArch system folder
unzip -qo "$LR/PPSSPP.zip" -d "$INC/etc/skel/.config/retroarch/system/"
# One on-screen gamepad is enough for a tablet
unzip -qo "$LR/overlays.zip" 'gamepads/neo-retropad/*' -d "$INC/usr/share/libretro/overlays/"
unzip -qo "$LR/autoconfig.zip" 'udev/*' -d "$INC/usr/share/libretro/autoconfig/"

echo ">>> TorrServer (github.com/YouROK/TorrServer, GPL-3.0)"
TS_VER=MatriX.146.1
TSB="$WORK/torrserver/ts-$TS_VER"
mkdir -p "$WORK/torrserver"
[ -s "$TSB" ] || curl -fsSL -o "$TSB" "https://github.com/YouROK/TorrServer/releases/download/$TS_VER/TorrServer-linux-amd64"
install -m 0755 "$TSB" "$INC/usr/local/bin/torrserver"

echo ">>> GRUB-пакеты для установщика (взаимоисключающие, поэтому не в пуле ISO)"
DEBS="$INC/usr/share/pero/debs"
rm -rf "$DEBS" && mkdir -p "$DEBS"
(cd "$DEBS" && apt-get download -qq grub-efi-ia32 grub-efi-amd64 grub-efi-amd64-signed grub-pc grub2-common cryptsetup-initramfs)

echo ">>> live-build"
cd "$WORK"
lb clean >/dev/null 2>&1 || true
rm -rf config
./auto/config >/dev/null
rsync -a "$WORK/config.src/" "$WORK/config/"
lb build 2>&1 | tee "$WORK/build.log"

ISO=$(ls -t "$WORK"/*.iso 2>/dev/null | head -n1)
[ -n "$ISO" ] || { echo "ISO не собран, смотрите $WORK/build.log"; exit 1; }
mkdir -p "$OUT"
NAME="pero-os-1.0-$(date +%Y%m%d)-amd64.iso"
cp "$ISO" "$OUT/$NAME"
(cd "$OUT" && sha256sum "$NAME" >"$NAME.sha256")
echo ">>> Готово: $OUT/$NAME ($(du -h "$OUT/$NAME" | cut -f1))"
