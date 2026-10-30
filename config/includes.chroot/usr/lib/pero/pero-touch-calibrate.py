#!/usr/bin/python3
"""pero-touch-calibrate — four taps, and the touchscreen hits where the finger is.

Shows a cross in each corner of the screen; the taps give the mapping from
what the touchscreen reports to the screen (mirroring, swapped axes, offset and
scale in one affine matrix). It is stored as the libinput calibration matrix of
every touchscreen, system-wide (/etc/X11/xorg.conf.d), so the login screen
gets it too, and applied to the running session at once.

  pero-touch-calibrate              calibrate, then save (asks for the password)
  pero-touch-calibrate --print      calibrate and only print the matrix (pero-update saves it)
  pero-touch-calibrate --save "a b c d e f"   (root) write the matrix
  pero-touch-calibrate --reset      (root) remove the calibration
"""
import os
import subprocess
import sys

CONF = "/etc/X11/xorg.conf.d/99-pero-touch-calibration.conf"
PROP = "libinput Calibration Matrix"
IDENTITY = [1, 0, 0, 0, 1, 0]
TARGETS = [(0.1, 0.1), (0.9, 0.1), (0.1, 0.9), (0.9, 0.9)]


def run(*cmd):
	try:
		return subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout
	except (OSError, subprocess.TimeoutExpired):
		return ""


def touch_devices():
	"""X input devices of touchscreens: the absolute ones with a calibration matrix."""
	ids = []
	for line in run("xinput", "list", "--id-only").split():
		props = run("xinput", "list-props", line)
		if PROP in props and "Coordinate Transformation Matrix" in props:
			if "libinput Accel Speed" not in props:   # touchpads and mice have it
				ids.append(line)
	return ids


def set_matrix(m):
	vals = [str(round(v, 6)) for v in m] + ["0", "0", "1"]
	for dev in touch_devices():
		subprocess.run(["xinput", "set-prop", dev, PROP] + vals, capture_output=True)


def save(m):
	os.makedirs(os.path.dirname(CONF), exist_ok=True)
	vals = " ".join(str(round(v, 6)) for v in m) + " 0 0 1"
	with open(CONF, "w") as f:
		f.write(f"""# pero-touch-calibrate: where the touchscreen's reports land on the screen
Section "InputClass"
	Identifier "pero touch calibration"
	MatchIsTouchscreen "on"
	MatchDriver "libinput"
	Option "CalibrationMatrix" "{vals}"
EndSection
""")


def solve(points):
	"""Least-squares affine map (u, v) -> (x, y) over the tapped points."""
	def row(target):
		# normal equations A^T A p = A^T t for p = (a, b, c), rows (u, v, 1)
		s = [[0.0] * 3 for _ in range(3)]
		r = [0.0] * 3
		for (u, v), t in zip([p[0] for p in points], [p[1][target] for p in points]):
			a = (u, v, 1.0)
			for i in range(3):
				r[i] += a[i] * t
				for j in range(3):
					s[i][j] += a[i] * a[j]
		return cramer(s, r)
	x, y = row(0), row(1)
	return None if x is None or y is None else x + y


def cramer(s, r):
	def det(m):
		return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
			- m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
			+ m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))
	d = det(s)
	if abs(d) < 1e-9:
		return None
	out = []
	for k in range(3):
		m = [list(rw) for rw in s]
		for i in range(3):
			m[i][k] = r[i]
		out.append(det(m) / d)
	return out


def calibrate():
	import gi
	gi.require_version("Gtk", "3.0")
	from gi.repository import Gdk, GLib, Gtk

	# Measure what the touchscreen reports on its own, in the normal orientation
	set_matrix(IDENTITY)
	subprocess.run(["pero-rotate", "normal"], capture_output=True)

	result = {}
	taps = []
	win = Gtk.Window()
	win.set_title("Калибровка сенсора")
	win.fullscreen()
	win.set_keep_above(True)
	area = Gtk.DrawingArea()
	win.add(area)
	win.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.TOUCH_MASK
		| Gdk.EventMask.KEY_PRESS_MASK)
	last = {"t": 0}

	def draw(widget, cr):
		w, h = widget.get_allocated_width(), widget.get_allocated_height()
		cr.set_source_rgb(0.07, 0.07, 0.07)
		cr.paint()
		cr.set_source_rgb(0.9, 0.9, 0.9)
		cr.select_font_face("Inter")
		cr.set_font_size(28)
		text = (f"Коснитесь крестика ({len(taps) + 1} из {len(TARGETS)})"
			if len(taps) < len(TARGETS) else "Готово")
		ext = cr.text_extents(text)
		cr.move_to((w - ext.width) / 2, h / 2)
		cr.show_text(text)
		cr.set_font_size(18)
		hint = "Esc — отмена (сама закроется через минуту без касаний)"
		ext = cr.text_extents(hint)
		cr.move_to((w - ext.width) / 2, h / 2 + 40)
		cr.show_text(hint)
		if len(taps) < len(TARGETS):
			tx, ty = TARGETS[len(taps)]
			x, y = tx * w, ty * h
			cr.set_source_rgb(1, 0.35, 0.2)
			cr.set_line_width(4)
			cr.move_to(x - 40, y)
			cr.line_to(x + 40, y)
			cr.move_to(x, y - 40)
			cr.line_to(x, y + 40)
			cr.stroke()
			cr.arc(x, y, 14, 0, 6.2832)
			cr.stroke()

	def press(_w, ev):
		# A touch can come as a touch event, as the pointer press X emulates
		# from it, or both: one tap counts once
		if ev.type == Gdk.EventType.TOUCH_BEGIN:
			pass
		elif ev.type != Gdk.EventType.BUTTON_PRESS or ev.time - last["t"] < 400:
			return True
		last["t"] = ev.time
		w, h = win.get_allocated_width(), win.get_allocated_height()
		if not w or not h:
			return True
		taps.append(((ev.x_root / w, ev.y_root / h), TARGETS[len(taps)]))
		area.queue_draw()
		if len(taps) == len(TARGETS):
			m = solve(taps)
			# taps that disagree with each other: the finger slipped, start over
			if m and max(abs(m[0] * u + m[1] * v + m[2] - tx) + abs(m[3] * u + m[4] * v + m[5] - ty)
					for (u, v), (tx, ty) in taps) < 0.06:
				result["m"] = m
				Gtk.main_quit()
			else:
				taps.clear()
				area.queue_draw()
		return True

	def key(_w, ev):
		if ev.keyval == Gdk.KEY_Escape:
			Gtk.main_quit()
		return True

	area.connect("draw", draw)
	win.connect("button-press-event", press)
	win.connect("touch-event", press)
	win.connect("key-press-event", key)
	win.connect("destroy", Gtk.main_quit)
	win.show_all()
	# Nobody tapping (the touchscreen is dead, or no one is there): give up
	# instead of leaving a full-screen window and a waiting pero-update
	timer = {"id": None}
	def idle_out():
		Gtk.main_quit()
		return False
	def rearm(*_a):
		if timer["id"]:
			GLib.source_remove(timer["id"])
		timer["id"] = GLib.timeout_add_seconds(60, idle_out)
		return False
	rearm()
	win.connect_after("button-press-event", rearm)
	win.connect_after("touch-event", rearm)
	Gtk.main()
	win.destroy()
	return result.get("m")


def main():
	args = sys.argv[1:]
	if args[:1] == ["--save"]:
		vals = [float(v) for v in args[1].split()][:6]
		save(vals)
		print(f"Сохранено: {CONF}")
		return 0
	if args[:1] == ["--reset"]:
		try:
			os.remove(CONF)
		except FileNotFoundError:
			pass
		return 0

	old = None
	m = calibrate()
	if not m:
		# Cancelled: put back what the session had
		if os.path.exists(CONF):
			for line in open(CONF):
				if "CalibrationMatrix" in line:
					old = [float(v) for v in line.split('"')[3].split()][:6]
		set_matrix(old or IDENTITY)
		print("Калибровка отменена", file=sys.stderr)
		return 1
	set_matrix(m)
	vals = " ".join(str(round(v, 6)) for v in m)
	if args[:1] == ["--print"]:
		print(vals)
		return 0
	subprocess.run(["pkexec", "/usr/local/bin/pero-touch-calibrate", "--save", vals])
	print(vals)
	return 0


if __name__ == "__main__":
	sys.exit(main())
