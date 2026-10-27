#!/bin/bash
# Boot the ISO headless in QEMU and save screenshots.
#   test/qemu-boot.sh <iso> <ia32|x64|bios> <outdir> [seconds...]
# Screenshots are taken at each given second mark (default: 25 90 150).
set -euo pipefail

ISO=$1 FW=$2 OUT=$3; shift 3
MARKS=("${@:-25 90 150}")
[ $# -eq 0 ] && MARKS=(25 90 150)
mkdir -p "$OUT"
RUN=$(mktemp -d)
MON="$RUN/mon"

case "$FW" in
	ia32) cp /usr/share/OVMF/OVMF32_VARS_4M.fd "$RUN/vars.fd"
	      FWARGS=(-drive if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF32_CODE_4M.fd
	              -drive if=pflash,format=raw,file="$RUN/vars.fd") ;;
	x64)  cp /usr/share/OVMF/OVMF_VARS_4M.fd "$RUN/vars.fd"
	      FWARGS=(-drive if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd
	              -drive if=pflash,format=raw,file="$RUN/vars.fd") ;;
	bios) FWARGS=() ;;
esac

ACCEL=(-accel tcg)
[ -w /dev/kvm ] && ACCEL=(-accel kvm -cpu host)

qemu-system-x86_64 -machine q35 "${ACCEL[@]}" -m 3072 -smp 4 \
	"${FWARGS[@]}" -cdrom "$ISO" -boot d \
	-device virtio-vga -display none -device qemu-xhci -device usb-tablet \
	-monitor unix:"$MON",server,nowait -serial file:"$OUT/serial-$FW.log" &
QPID=$!

start=$(date +%s)
for t in "${MARKS[@]}"; do
	while [ $(( $(date +%s) - start )) -lt "$t" ]; do
		kill -0 $QPID 2>/dev/null || { echo "QEMU exited early"; exit 1; }
		sleep 1
	done
	echo "screendump $RUN/s.ppm" | socat - UNIX-CONNECT:"$MON" >/dev/null
	sleep 1
	pnmtopng "$RUN/s.ppm" >"$OUT/$FW-${t}s.png" 2>/dev/null && echo "shot $OUT/$FW-${t}s.png"
done

echo quit | socat - UNIX-CONNECT:"$MON" >/dev/null || kill $QPID
rm -rf "$RUN"
