#!/usr/bin/python3
"""pero-ripple — a soft circle that spreads and fades under the finger.

pero-touchd starts it and writes one line "x y" (screen pixels) per new touch.
The circle is drawn in a small click-through window, so it never takes a touch
itself. Needs the compositor (xfwm4 has it on); without one it does nothing,
rather than flash black squares.
"""
import os
import sys

import cairo
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

SIZE = 112      # px, window (the circle grows to just inside it)
TIME = 320      # ms
POOL = 4        # windows reused for taps in quick succession


class Ripple:
	def __init__(self):
		self.win = Gtk.Window(type=Gtk.WindowType.POPUP)
		self.win.set_app_paintable(True)
		self.win.set_default_size(SIZE, SIZE)
		self.win.set_accept_focus(False)
		self.win.set_keep_above(True)
		visual = self.win.get_screen().get_rgba_visual()
		if visual:
			self.win.set_visual(visual)
		self.win.connect("draw", self.draw)
		self.win.connect("realize", lambda w: w.input_shape_combine_region(cairo.Region()))
		self.t = 1.0
		self.timer = None

	def show(self, x, y):
		self.win.move(int(x) - SIZE // 2, int(y) - SIZE // 2)
		self.t = 0.0
		self.win.show()
		if self.timer:
			GLib.source_remove(self.timer)
		self.start = GLib.get_monotonic_time()
		self.timer = GLib.timeout_add(16, self.tick)

	def tick(self):
		self.t = min(1.0, (GLib.get_monotonic_time() - self.start) / 1000 / TIME)
		self.win.queue_draw()
		if self.t >= 1.0:
			self.win.hide()
			self.timer = None
			return False
		return True

	def busy(self):
		return self.timer is not None

	def draw(self, _w, cr):
		cr.set_operator(cairo.OPERATOR_SOURCE)
		cr.set_source_rgba(0, 0, 0, 0)
		cr.paint()
		cr.set_operator(cairo.OPERATOR_OVER)
		ease = 1 - (1 - self.t) ** 3
		r = 10 + ease * (SIZE / 2 - 12)
		alpha = 0.42 * (1 - self.t)
		cr.arc(SIZE / 2, SIZE / 2, r, 0, 6.2832)
		cr.set_source_rgba(1, 1, 1, alpha * 0.55)
		cr.fill_preserve()
		cr.set_line_width(2)
		cr.set_source_rgba(1, 1, 1, alpha)
		cr.stroke()


def main():
	screen = Gtk.Window().get_screen()
	if not screen.get_rgba_visual() or not screen.is_composited():
		# no compositor: transparency would come out as black squares; read and drop
		for _line in sys.stdin:
			pass
		return
	pool = [Ripple() for _ in range(POOL)]

	buf = [b""]

	def readable(fd, cond):
		data = os.read(fd, 4096) if cond & GLib.IO_IN else b""
		if not data:
			Gtk.main_quit()
			return False
		buf[0] += data
		*lines, buf[0] = buf[0].split(b"\n")
		for line in lines:
			try:
				x, y = (float(v) for v in line.split()[:2])
			except ValueError:
				continue
			free = next((r for r in pool if not r.busy()), pool[0])
			free.show(x, y)
		return True

	GLib.unix_fd_add_full(GLib.PRIORITY_DEFAULT, sys.stdin.fileno(), GLib.IO_IN | GLib.IO_HUP, readable)
	Gtk.main()


if __name__ == "__main__":
	main()
