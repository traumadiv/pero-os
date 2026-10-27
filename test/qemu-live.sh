#!/bin/bash
# Interactive QEMU helper for the live ISO (headless, driven via the monitor).
#   test/qemu-live.sh start <iso|none> <ia32|x64> [disk.qcow2]
#   test/qemu-live.sh shot <file.png>
#   test/qemu-live.sh click <x> <y> [double]     screen pixels (1280x800 assumed)
#   test/qemu-live.sh key <qemu-key>...          e.g. ret, ctrl-alt-t, a b c
#   test/qemu-live.sh stop
set -euo pipefail
RUN=/root/pero-qemu
MON=$RUN/mon
W=1280 H=800

mon() { echo "$*" | socat - UNIX-CONNECT:"$MON" >/dev/null; }

case "$1" in
start)
	mkdir -p "$RUN"
	case "$3" in
		ia32) CODE=/usr/share/OVMF/OVMF32_CODE_4M.fd; cp /usr/share/OVMF/OVMF32_VARS_4M.fd "$RUN/vars.fd" ;;
		x64)  CODE=/usr/share/OVMF/OVMF_CODE_4M.fd;   cp /usr/share/OVMF/OVMF_VARS_4M.fd "$RUN/vars.fd" ;;
	esac
	DISK=()
	[ -n "${4:-}" ] && DISK=(-drive file="$4",if=none,id=hd0,format=qcow2 -device ide-hd,drive=hd0,bus=ide.1)
	# iso "none": boot the installed system from the disk
	CD=(-cdrom "$2" -boot d)
	[ "$2" = none ] && CD=()
	qemu-system-x86_64 -machine q35 -accel tcg -m 3072 -smp 4 \
		-drive if=pflash,format=raw,readonly=on,file="$CODE" \
		-drive if=pflash,format=raw,file="$RUN/vars.fd" \
		"${CD[@]}" "${DISK[@]}" \
		-device virtio-vga,xres=$W,yres=$H -display none -device qemu-xhci -device usb-tablet \
		-monitor unix:"$MON",server,nowait -qmp unix:"$RUN/qmp",server,nowait -serial file:"$RUN/serial.log" >"$RUN/qemu.log" 2>&1
	;;
shot)
	mon "screendump $RUN/s.ppm"; sleep 1
	pnmtopng "$RUN/s.ppm" >"$2" && echo "saved $2"
	;;
click)
	# absolute pointer via QMP (usb-tablet range 0..32767)
	ax=$(( $2 * 32767 / W )) ay=$(( $3 * 32767 / H ))
	ev() { printf '{"execute":"input-send-event","arguments":{"events":[%s]}}
' "$1"; }
	{
		echo '{"execute":"qmp_capabilities"}'; sleep 0.2
		ev "{\"type\":\"abs\",\"data\":{\"axis\":\"x\",\"value\":$ax}},{\"type\":\"abs\",\"data\":{\"axis\":\"y\",\"value\":$ay}}"; sleep 0.3
		ev '{"type":"btn","data":{"down":true,"button":"left"}}'; sleep 0.1
		ev '{"type":"btn","data":{"down":false,"button":"left"}}'; sleep 0.3
	} | socat - UNIX-CONNECT:"$RUN/qmp" >/dev/null
	;;
key)
	shift; for k in "$@"; do mon "sendkey $k"; sleep 0.15; done
	;;
type)
	# latin letters, digits, space, '-' and '.' only
	s=$2
	for (( i=0; i<${#s}; i++ )); do
		c=${s:i:1}
		case "$c" in
			" ") k=spc ;; "-") k=minus ;; "." ) k=dot ;; "/") k=slash ;;
			"|") k=shift-backslash ;; "'") k=apostrophe ;; ">") k=shift-dot ;; "<") k=shift-comma ;;
			";") k=semicolon ;; ":") k=shift-semicolon ;; "=") k=equal ;; "_") k=shift-minus ;;
			"*") k=shift-8 ;; "~") k=shift-grave_accent ;; ",") k=comma ;; '"') k=shift-apostrophe ;;
			"&") k=shift-7 ;; "$") k=shift-4 ;;
			[A-Z]) k="shift-${c,,}" ;;
			*) k=$c ;;
		esac
		mon "sendkey $k"; sleep 0.12
	done
	;;
stop)
	mon quit || pkill -f "qemu-system-x86_64.*pero" || true
	;;
esac
