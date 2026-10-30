#!/usr/bin/python3
"""pero-touch-calibrate — four taps, and the touchscreen hits where the finger is.

Shows a cross in each corner of the screen and reads the taps straight from the
touchscreen device (not through X, so it works however wrong the current
mapping is). The taps give the affine map from what the touchscreen reports to
the screen: mirroring, swapped axes, offset and scale at once. pero-touchd
applies it to every touch from then on.

  pero-touch-calibrate          calibrate (Esc cancels, gives up after a minute idle)
  pero-touch-calibrate --reset  forget the calibration
"""
import os
import subprocess
import sys

import evdev
from evdev import ecodes as e

SAVE = os.path.expanduser("~/.config/pero/touch-calibration")
RAW_FLAG = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "pero-touch-raw")
CLONE = "pero-touch"
TARGETS = [(0.1, 0.1), (0.9, 0.1), (0.1, 0.9), (0.9, 0.9)]
IDLE = 60   # s without taps before giving up


def run(*cmd):
	try:
		return subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout
	except (OSError, subprocess.TimeoutExpired):
		return ""


def touchscreen():
	"""pero-touchd's clone when it runs (it has the original grabbed), else the
	touchscreen itself."""
	found = None
	for path in evdev.list_devices():
		try:
			dev = evdev.InputDevice(path)
		except OSError:
			continue
		caps = dev.capabilities(absinfo=False)
		if e.ABS_X in caps.get(e.EV_ABS, []) and e.INPUT_PROP_DIRECT in dev.input_props():
			if dev.name == CLONE:
				return dev
			found = found or dev
	return found


def screen_matrix(name):
	"""X's Coordinate Transformation Matrix of the device: rotation / output mapping
	applied after our calibration."""
	for line in run("xinput", "list-props", name).splitlines():
		if "Coordinate Transformation Matrix" in line:
			v = [float(x) for x in line.split(":", 1)[1].split(",")]
			return v[:6]
	return [1, 0, 0, 0, 1, 0]


def invert(m):
	a, b, c, d, f, g = m
	det = a * f - b * d
	if abs(det) < 1e-9:
		return [1, 0, 0, 0, 1, 0]
	ia, ib, id_, if_ = f / det, -b / det, -d / det, a / det
	return [ia, ib, -(ia * c + ib * g), id_, if_, -(id_ * c + if_ * g)]


def compose(p, q):
	"""p after q, both affine (a b c / d e f)."""
	return [p[0] * q[0] + p[1] * q[3], p[0] * q[1] + p[1] * q[4], p[0] * q[2] + p[1] * q[5] + p[2],
		p[3] * q[0] + p[4] * q[3], p[3] * q[1] + p[4] * q[4], p[3] * q[2] + p[4] * q[5] + p[5]]


def solve(points):
	"""Least-squares affine map (u, v) -> target over the tapped points."""
	def row(k):
		s = [[0.0] * 3 for _ in range(3)]
		r = [0.0] * 3
		for (u, v), t in points:
			a = (u, v, 1.0)
			for i in range(3):
				r[i] += a[i] * t[k]
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


def fits(m, points, tol=0.06):
	return max(abs(m[0] * u + m[1] * v + m[2] - tx) + abs(m[3] * u + m[4] * v + m[5] - ty)
		for (u, v), (tx, ty) in points) < tol


def calibrate(dev):
	import gi
	gi.require_version("Gtk", "3.0")
	from gi.repository import Gdk, GLib, Gtk

	rx, ry = dev.absinfo(e.ABS_X), dev.absinfo(e.ABS_Y)
	state = {"u": None, "v": None, "down": False, "timer": None, "result": None}
	taps = []

	win = Gtk.Window(title="Калибровка сенсора")
	win.fullscreen()
	win.set_keep_above(True)
	area = Gtk.DrawingArea()
	win.add(area)

	def draw(widget, cr):
		w, h = widget.get_allocated_width(), widget.get_allocated_height()
		cr.set_source_rgb(0.07, 0.07, 0.07)
		cr.paint()
		cr.set_source_rgb(0.9, 0.9, 0.9)
		cr.set_font_size(28)
		text = f"Коснитесь центра крестика ({len(taps) + 1} из {len(TARGETS)})"
		ext = cr.text_extents(text)
		cr.move_to((w - ext.width) / 2, h / 2)
		cr.show_text(text)
		cr.set_font_size(18)
		hint = "Esc — отмена, через минуту без касаний закроется само"
		ext = cr.text_extents(hint)
		cr.move_to((w - ext.width) / 2, h / 2 + 40)
		cr.show_text(hint)
		tx, ty = TARGETS[min(len(taps), len(TARGETS) - 1)]
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

	def give_up():
		Gtk.main_quit()
		return False

	def rearm():
		if state["timer"]:
			GLib.source_remove(state["timer"])
		state["timer"] = GLib.timeout_add_seconds(IDLE, give_up)

	def tapped():
		taps.append(((state["u"], state["v"]), TARGETS[len(taps)]))
		if len(taps) == len(TARGETS):
			m = solve(taps)
			if m and fits(m, taps):
				state["result"] = m
				Gtk.main_quit()
				return
			taps.clear()   # a finger slipped: start over
		area.queue_draw()

	def readable(_fd, _cond):
		try:
			for ev in dev.read():
				if ev.type == e.EV_ABS and ev.code == e.ABS_X:
					state["u"] = (ev.value - rx.min) / max(1, rx.max - rx.min)
				elif ev.type == e.EV_ABS and ev.code == e.ABS_Y:
					state["v"] = (ev.value - ry.min) / max(1, ry.max - ry.min)
				elif ev.type == e.EV_KEY and ev.code == e.BTN_TOUCH:
					if ev.value:
						state["down"] = True
						rearm()
					elif state["down"]:
						state["down"] = False
						if state["u"] is not None and state["v"] is not None:
							tapped()
		except BlockingIOError:
			pass
		except OSError:
			Gtk.main_quit()
			return False
		return True

	def key(_w, ev):
		if ev.keyval == Gdk.KEY_Escape:
			Gtk.main_quit()
		return True

	area.connect("draw", draw)
	win.connect("key-press-event", key)
	win.connect("destroy", Gtk.main_quit)
	GLib.io_add_watch(dev.fd, GLib.IO_IN, readable)
	win.show_all()
	rearm()
	Gtk.main()
	win.destroy()
	return state["result"]


def main():
	if sys.argv[1:2] == ["--reset"]:
		try:
			os.remove(SAVE)
		except FileNotFoundError:
			pass
		print("Калибровка сброшена")
		return 0

	dev = touchscreen()
	if dev is None:
		print("Сенсорный экран не найден (нет устройства с касаниями).", file=sys.stderr)
		return 1

	# Measure in the normal orientation, with pero-touchd passing positions as they are
	subprocess.run(["pero-rotate", "normal"], capture_output=True)
	open(RAW_FLAG, "w").close()
	try:
		m = calibrate(dev)
	finally:
		os.remove(RAW_FLAG)
	if not m:
		print("Калибровка отменена, всё осталось как было", file=sys.stderr)
		return 1

	# The taps measured device -> screen; X still applies its own matrix (rotation,
	# output) after pero-touchd, so the stored mapping undoes that part
	m = compose(invert(screen_matrix(dev.name)), m)
	os.makedirs(os.path.dirname(SAVE), exist_ok=True)
	with open(SAVE, "w") as f:
		f.write(" ".join(f"{v:.6f}" for v in m) + "\n")
	print("Калибровка сохранена:", " ".join(f"{v:.4f}" for v in m))
	if dev.name != CLONE:
		print("pero-touchd не запущен: калибровка заработает, когда он запустится (после входа в систему).")
	return 0


if __name__ == "__main__":
	sys.exit(main())
