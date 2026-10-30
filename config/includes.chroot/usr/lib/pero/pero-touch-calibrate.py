#!/usr/bin/python3
"""pero-touch-calibrate — four taps, and the touchscreen hits where the finger is.

Shows crosses along a vertical and a horizontal line through the centre, seven
on each, from edge to edge, and reads the taps straight from the touchscreen
device (not through X, so it works however wrong the current mapping is).
The taps give
  - an affine map from what the touchscreen reports to the screen: mirroring,
    swapped axes, offset and scale at once;
  - per axis, a piecewise-linear correction through the seven taps on that
    axis: Silead panels are not linear, they bend between the middle and the
    edges, and a correction pinned only at the edges and the centre misses that.
pero-touchd applies both to every touch from then on.

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
LINE = (0.03, 0.15, 0.3, 0.5, 0.7, 0.85, 0.97)
# top to bottom through the centre, then left to right (the centre once)
TARGETS = [(0.5, t) for t in LINE] + [(t, 0.5) for t in LINE if t != 0.5]
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


def on_line(points, axis):
	"""The taps of the line along axis (0: horizontal line, 1: vertical line)."""
	return [p for p in points if abs(p[1][1 - axis] - 0.5) < 1e-6]


def knots(m, points, axis):
	"""Piecewise-linear correction for one screen axis after the affine map m:
	(where the affine map put a tap, where its cross is) along that axis."""
	out = sorted(((m[0] * u + m[1] * v + m[2], m[3] * u + m[4] * v + m[5])[axis], t[axis])
		for (u, v), t in on_line(points, axis))
	# out of order or bunched up: a tap slipped onto the wrong cross
	if any(b[1] <= a[1] or b[0] - a[0] < 0.03 for a, b in zip(out, out[1:])):
		return None
	return out


def bend(k, t):
	"""Apply a knot list: linear between knots, the end segments extended."""
	if not k:
		return t
	for (p0, q0), (p1, q1) in zip(k, k[1:]):
		if t <= p1 or (p1, q1) == k[-1]:
			return q0 + (t - p0) * (q1 - q0) / (p1 - p0)
	return t


def model(points):
	m = solve(points)
	if not m:
		return None
	kx, ky = knots(m, points, 0), knots(m, points, 1)
	if not kx or not ky:
		return None
	return m, kx, ky


def fits(mod, points, tol=0.05):
	"""The taps of each line stay on that line after the full correction (along
	the line the knots fit exactly): a slipped tap would stray off it."""
	m, kx, ky = mod
	return max(abs(bend(kx, m[0] * u + m[1] * v + m[2]) - tx) + abs(bend(ky, m[3] * u + m[4] * v + m[5]) - ty)
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
			m = model(taps)
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
	# output) after pero-touchd, so the stored mapping ends by undoing that part
	m, kx, ky = m
	post = invert(screen_matrix(dev.name))
	lines = [
		"m " + " ".join(f"{v:.6f}" for v in m),
		"x " + " ".join(f"{p:.6f} {q:.6f}" for p, q in kx),
		"y " + " ".join(f"{p:.6f} {q:.6f}" for p, q in ky),
		"post " + " ".join(f"{v:.6f}" for v in post),
	]
	os.makedirs(os.path.dirname(SAVE), exist_ok=True)
	with open(SAVE, "w") as f:
		f.write("\n".join(lines) + "\n")
	print("Калибровка сохранена:")
	print("\n".join(lines))
	if dev.name != CLONE:
		print("pero-touchd не запущен: калибровка заработает, когда он запустится (после входа в систему).")
	return 0


if __name__ == "__main__":
	sys.exit(main())
