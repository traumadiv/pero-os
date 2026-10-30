#!/usr/bin/python3
"""pero-touchd — touch gestures X11 has no answer for on its own.

  long press (0.6 s, finger still)      right click
  two-finger tap                        right click
  swipe in from the right screen edge   quick settings (pero-panel)

Each touchscreen is grabbed and replayed through a uinput clone. A new touch is
held back only until it is clear what it is: a tap or a drag goes through at
once (with everything buffered so far), a gesture is swallowed.

The clone also carries the calibration (pero-touch-calibrate): positions are
mapped by an affine matrix before X sees them, so mirrored or offset panels
hit under the finger, and the gestures use the same corrected positions.
"""
import asyncio
import os
import subprocess
import sys
import time

import evdev
from evdev import ecodes as e

HOLD = 0.6     # s, long press
SLOP = 0.008   # travel (fraction of the screen) that still counts as standing still
EDGE = 0.03    # a swipe starts this close to the right edge
SWIPE = 0.06   # and has to come in this far
TAP2 = 0.5     # s, two-finger tap

CLONE = "pero-touch"
CALIBRATION = [os.path.expanduser("~/.config/pero/touch-calibration"), "/etc/pero/touch-calibration"]
# pero-touch-calibrate creates this while it measures: pass positions through as they are
RAW_FLAG = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "pero-touch-raw")
ROT_STATE = os.path.expanduser("~/.config/pero/rotation-current")
DEBUG = os.environ.get("PERO_TOUCH_DEBUG") == "1"


def run(*cmd):
	try:
		return subprocess.run(cmd, capture_output=True, text=True, timeout=3).stdout
	except (OSError, subprocess.TimeoutExpired):
		return ""


def is_touchscreen(dev):
	caps = dev.capabilities(absinfo=False)
	return (e.ABS_MT_POSITION_X in caps.get(e.EV_ABS, [])
		and e.INPUT_PROP_DIRECT in dev.input_props()
		and e.BTN_TOOL_PEN not in caps.get(e.EV_KEY, [])
		and dev.name != CLONE)


class Calibration:
	"""Device position (0..1) to corrected position (0..1): x = a u + b v + c, y = d u + e v + f."""

	IDENTITY = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0)

	def __init__(self):
		self.m = self.IDENTITY
		self.stamp = None

	def update(self):
		stamp = os.path.exists(RAW_FLAG)
		for path in CALIBRATION:
			try:
				stamp = (stamp, path, os.stat(path).st_mtime)
				break
			except OSError:
				continue
		if stamp == self.stamp:
			return
		self.stamp = stamp
		self.m = self.IDENTITY
		if os.path.exists(RAW_FLAG) or not isinstance(stamp, tuple):
			return
		try:
			vals = [float(x) for x in open(stamp[1]).read().split()[:6]]
			if len(vals) == 6:
				self.m = tuple(vals)
		except (OSError, ValueError):
			pass

	def map(self, u, v):
		m = self.m
		return m[0] * u + m[1] * v + m[2], m[3] * u + m[4] * v + m[5]


CAL = Calibration()


class Screen:
	"""Device coordinates (0..1) to X screen pixels, following rotation."""

	def __init__(self):
		self.stamp = None
		self.m = [1, 0, 0, 0, 1, 0]
		self.size = (1, 1)

	def update(self):
		try:
			stamp = os.stat(ROT_STATE).st_mtime
		except OSError:
			stamp = 0
		if stamp == self.stamp:
			return
		self.stamp = stamp
		for line in run("xinput", "list-props", CLONE).splitlines():
			if "Coordinate Transformation Matrix" in line:
				vals = [float(x) for x in line.split(":", 1)[1].split(",")]
				self.m = vals[:6]
		wh = run("xdotool", "getdisplaygeometry").split()
		if len(wh) == 2:
			self.size = (int(wh[0]), int(wh[1]))

	def norm(self, u, v):
		u, v = CAL.map(u, v)
		m = self.m
		return m[0] * u + m[1] * v + m[2], m[3] * u + m[4] * v + m[5]

	def pixels(self, u, v):
		x, y = self.norm(u, v)
		return int(x * self.size[0]), int(y * self.size[1])


class Touch:
	IDLE, PENDING, PASS, SWALLOW = range(4)

	def __init__(self, dev, screen):
		self.dev, self.screen = dev, screen
		self.clone = evdev.UInput.from_device(dev, name=CLONE, input_props=dev.input_props())
		self.rx = dev.absinfo(e.ABS_MT_POSITION_X)
		self.ry = dev.absinfo(e.ABS_MT_POSITION_Y)
		self.slot = 0
		self.slots = {}      # slot -> [u, v, u0, v0] of the fingers down
		# last coordinates per slot: the kernel does not repeat a value that has not
		# changed, even for a new finger in that slot
		self.pos = {}
		self.state = self.IDLE
		self.buf, self.buf_slot = [], 0
		self.timer = None
		self.st = [0.5, 0.5]   # single-touch ABS_X / ABS_Y, normalized
		CAL.update()

	async def loop(self):
		try:
			self.dev.grab()
			async for ev in self.dev.async_read_loop():
				self.event(ev)
		finally:
			self.clone.close()

	def event(self, ev):
		if self.state == self.IDLE and not self.buf:
			CAL.update()   # a new touch: pick up a fresh calibration before mapping it
		if ev.type == e.EV_ABS:
			if ev.code == e.ABS_MT_SLOT:
				self.slot = ev.value
			elif ev.code == e.ABS_MT_TRACKING_ID:
				if ev.value < 0:
					self.slots.pop(self.slot, None)
				else:
					u, v = self.pos.get(self.slot, (None, None))
					self.slots[self.slot] = [u, v, None, None]
			elif ev.code in (e.ABS_MT_POSITION_X, e.ABS_MT_POSITION_Y):
				r = self.rx if ev.code == e.ABS_MT_POSITION_X else self.ry
				i = 0 if ev.code == e.ABS_MT_POSITION_X else 1
				val = (ev.value - r.min) / max(1, r.max - r.min)
				last = list(self.pos.get(self.slot, (None, None)))
				last[i] = val
				self.pos[self.slot] = tuple(last)
				if self.slot in self.slots:
					self.slots[self.slot][i] = val
			elif ev.code in (e.ABS_X, e.ABS_Y):
				r = self.rx if ev.code == e.ABS_X else self.ry
				self.st[0 if ev.code == e.ABS_X else 1] = (ev.value - r.min) / max(1, r.max - r.min)
		elif ev.type == e.EV_KEY and ev.code == e.BTN_TOUCH and ev.value == 0:
			# every finger is up, whatever got lost on the way
			self.slots.clear()

		out = self.calibrated(ev)
		if self.state == self.PASS:
			for code, val in out:
				self.clone.write(ev.type, code, val)
		elif self.state in (self.IDLE, self.PENDING):
			if not self.buf:
				self.buf_slot = self.slot
			self.buf.extend((ev.type, code, val) for code, val in out)

		if ev.type == e.EV_SYN and ev.code == e.SYN_REPORT:
			self.frame()

	def calibrated(self, ev):
		"""(code, value) pairs to send for ev: positions go through the calibration.
		A mapping can mix the axes, so a change of X or Y sends both."""
		if ev.type != e.EV_ABS:
			return [(ev.code, ev.value)]
		if ev.code in (e.ABS_MT_POSITION_X, e.ABS_MT_POSITION_Y):
			u, v = self.pos.get(self.slot, (None, None))
			codes = (e.ABS_MT_POSITION_X, e.ABS_MT_POSITION_Y)
		elif ev.code in (e.ABS_X, e.ABS_Y):
			(u, v), codes = self.st, (e.ABS_X, e.ABS_Y)
		else:
			return [(ev.code, ev.value)]
		if u is None or v is None:
			return [(ev.code, ev.value)]
		x, y = CAL.map(u, v)
		return [(codes[0], self.scale(x, self.rx)), (codes[1], self.scale(y, self.ry))]

	@staticmethod
	def scale(t, r):
		t = min(1.0, max(0.0, t))
		return int(round(r.min + t * (r.max - r.min)))

	def frame(self):
		if DEBUG:
			print(self.state, {k: [round(c, 3) if c is not None else None for c in s] for k, s in self.slots.items()},
				file=sys.stderr, flush=True)
		for s in self.slots.values():
			if s[2] is None and s[0] is not None and s[1] is not None:
				s[2], s[3] = s[0], s[1]
		n = len(self.slots)

		if self.state == self.IDLE:
			if n == 0:
				self.flush()
				return
			self.state = self.PENDING
			self.t0, self.most = time.monotonic(), n
			CAL.update()
			self.screen.update()
			first = self.first()
			self.x0 = self.screen.norm(first[2], first[3])[0] if first else 0
			self.last = (first[2], first[3]) if first else (0, 0)
			self.edge = self.x0 > 1 - EDGE
			self.timer = asyncio.get_running_loop().call_later(HOLD, self.hold)
			return

		if self.state == self.PENDING:
			self.most = max(self.most, n)
			if n == 0:
				if self.most >= 2 and time.monotonic() - self.t0 < TAP2:
					self.drop()
					self.right_click(*self.last)
				else:
					self.flush()
				self.end()
				return
			first = self.first()
			if first and first[0] is not None:
				self.last = (first[0], first[1])
			if self.edge and self.most == 1 and first:
				x = self.screen.norm(first[0], first[1])[0]
				if self.x0 - x >= SWIPE:
					self.drop()
					self.state = self.SWALLOW
					self.cancel()
					subprocess.Popen(["pero-panel"], start_new_session=True)
				elif x > self.x0 + SLOP or self.moved(across=True):
					self.flush()
				return
			if self.moved():
				self.flush()
			return

		if n == 0:
			self.end()

	def first(self):
		live = [s for s in self.slots.values() if s[2] is not None]
		return live[0] if live else None

	def moved(self, across=False):
		"""Some finger travelled more than SLOP (only up/down when across)."""
		for s in self.slots.values():
			if s[2] is None:
				continue
			du, dv = s[0] - s[2], s[1] - s[3]
			m = self.screen.m
			dx, dy = m[0] * du + m[1] * dv, m[3] * du + m[4] * dv
			if (abs(dy) if across else max(abs(dx), abs(dy))) > (SWIPE if across else SLOP):
				return True
		return False

	def hold(self):
		self.timer = None
		if self.state != self.PENDING or len(self.slots) != 1 or self.most != 1:
			return
		first = self.first()
		if not first:
			return
		self.drop()
		self.state = self.SWALLOW
		self.right_click(first[0], first[1])

	def right_click(self, u, v):
		x, y = self.screen.pixels(u, v)
		subprocess.Popen(["xdotool", "mousemove", str(x), str(y), "click", "3"])

	def flush(self):
		"""Let the touch through: replay what was held back, then pass the rest."""
		self.cancel()
		if self.buf:
			self.clone.write(e.EV_ABS, e.ABS_MT_SLOT, self.buf_slot)
			for typ, code, val in self.buf:
				self.clone.write(typ, code, val)
			self.buf = []
		if self.slots:
			self.state = self.PASS

	def drop(self):
		self.cancel()
		self.buf = []

	def cancel(self):
		if self.timer:
			self.timer.cancel()
			self.timer = None

	def end(self):
		self.cancel()
		self.buf = []
		self.state = self.IDLE


async def main():
	screen = Screen()
	running = {}
	remapped = False
	while True:
		paths = evdev.list_devices()
		for path in paths:
			if path in running:
				continue
			try:
				dev = evdev.InputDevice(path)
				if not is_touchscreen(dev):
					dev.close()
					continue
				touch = Touch(dev, screen)
			except OSError:
				continue
			running[path] = asyncio.ensure_future(touch.loop())
			remapped = False
		for path, task in list(running.items()):
			# a device that failed stays failed until it is unplugged
			if task.done() and path not in paths:
				del running[path]
		if running and not remapped:
			# the clone is a new X input device: map it to the screen like the real one
			await asyncio.sleep(1)
			run("pero-rotate", "remap")
			screen.stamp = None
			remapped = True
		await asyncio.sleep(3)


if __name__ == "__main__":
	try:
		asyncio.run(main())
	except KeyboardInterrupt:
		sys.exit(0)
