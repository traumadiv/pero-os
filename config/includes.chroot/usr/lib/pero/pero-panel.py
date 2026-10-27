#!/usr/bin/python3
"""pero-panel — tablet quick settings on the right edge of the screen.

Stays resident after login (autostart with --hidden); pero-panel toggles it.
Wi-Fi, Bluetooth, airplane mode, auto-rotation, on-screen keyboard, power
saving, do-not-disturb, brightness, volume and the power actions.
"""
import locale
import os
import subprocess
import sys
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

WIDTH = 380
ROT_LOCK = os.path.expanduser("~/.config/pero/rotation-lock")

CSS = b"""
window.pero-panel { background: #141414; border-left: 1px solid rgba(255,255,255,0.08); }
.pero-panel * { font-family: Inter; color: #ececec; }
.pero-panel .clock { font-size: 44px; font-weight: 300; }
.pero-panel .date, .pero-panel .battery { font-size: 14px; color: #9a9a9a; }
.pero-panel .tile { background: #232323; border-radius: 16px; border: none; box-shadow: none; padding: 0; min-height: 66px; }
.pero-panel .tile button { background: transparent; border: none; box-shadow: none; border-radius: 16px; padding: 10px 12px; }
.pero-panel .tile button.more { padding: 10px 8px; }
.pero-panel .tile.on { background: #ececec; }
.pero-panel .tile.on * { color: #111111; }
.pero-panel .tile.off-limits { opacity: 0.35; }
.pero-panel .tile-title { font-size: 14px; font-weight: 600; }
.pero-panel .tile-sub { font-size: 12px; color: #9a9a9a; }
.pero-panel .tile.on .tile-sub { color: #444444; }
.pero-panel scale trough { background: #2c2c2c; min-height: 34px; border-radius: 17px; border: none; }
.pero-panel scale highlight { background: #ececec; border-radius: 17px; min-height: 34px; }
.pero-panel scale slider { background: transparent; border: none; box-shadow: none; min-width: 0; min-height: 0; margin: 0; }
.pero-panel .slider-icon { background: transparent; border: none; box-shadow: none; padding: 6px; }
.pero-panel .action { background: #232323; border-radius: 30px; border: none; box-shadow: none; min-width: 56px; min-height: 56px; padding: 0; }
.pero-panel .action:active, .pero-panel .tile button:active { background: rgba(255,255,255,0.15); }
.pero-panel .action-label { font-size: 11px; color: #9a9a9a; }
"""


def run(*cmd):
	try:
		return subprocess.run(cmd, capture_output=True, text=True, timeout=3).stdout.strip()
	except (OSError, subprocess.TimeoutExpired):
		return ""


def spawn(*cmd):
	try:
		subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
	except OSError:
		pass


def rfkill_on(kind):
	"""True/False for the radios of this kind, None if there are none."""
	states = run("rfkill", "--noheadings", "-o", "SOFT", "list", kind).split()
	return None if not states else all(s == "unblocked" for s in states)


# ---- toggles: state() -> (on or None if unavailable, subtitle); toggle(on) ----

def wifi_state():
	radio = run("nmcli", "radio", "wifi")
	if not radio:
		return None, "нет"
	if radio != "enabled":
		return False, "Выкл"
	for line in run("nmcli", "-t", "-f", "TYPE,NAME", "con", "show", "--active").splitlines():
		kind, _, name = line.partition(":")
		if kind == "802-11-wireless":
			return True, name
	return True, "Нет сети"


def wifi_toggle(on):
	run("nmcli", "radio", "wifi", "on" if on else "off")


def bt_state():
	on = rfkill_on("bluetooth")
	return on, {None: "нет", True: "Вкл", False: "Выкл"}[on]


def bt_toggle(on):
	run("rfkill", "unblock" if on else "block", "bluetooth")


def airplane_state():
	wlan, bt = rfkill_on("wlan"), rfkill_on("bluetooth")
	if wlan is None and bt is None:
		return None, "нет радио"
	on = not wlan and not bt
	return on, "Вкл" if on else "Выкл"


def airplane_toggle(on):
	run("rfkill", "block" if on else "unblock", "all")


def rotation_state():
	on = not os.path.exists(ROT_LOCK)
	return on, "Вкл" if on else "Заблокирован"


def rotation_toggle(on):
	if on:
		try:
			os.remove(ROT_LOCK)
		except FileNotFoundError:
			pass
	else:
		os.makedirs(os.path.dirname(ROT_LOCK), exist_ok=True)
		open(ROT_LOCK, "w").close()


def saver_state():
	profile = run("powerprofilesctl", "get")
	if not profile:
		return None, "нет"
	on = profile == "power-saver"
	return on, "Вкл" if on else "Выкл"


def saver_toggle(on):
	run("powerprofilesctl", "set", "power-saver" if on else "balanced")


def dnd_state():
	on = run("xfconf-query", "-c", "xfce4-notifyd", "-p", "/do-not-disturb") == "true"
	return on, "Вкл" if on else "Выкл"


def dnd_toggle(on):
	run("xfconf-query", "-c", "xfce4-notifyd", "-p", "/do-not-disturb", "-n", "-t", "bool", "-s",
		"true" if on else "false")


# ---- sliders ----

def brightness_get():
	# intel_backlight,backlight,400,40%,1000
	parts = run("brightnessctl", "-m", "-c", "backlight").split(",")
	return int(parts[3].rstrip("%")) if len(parts) >= 5 else None


def brightness_set(v):
	run("brightnessctl", "-q", "-c", "backlight", "set", "%d%%" % max(5, v))


def volume_get():
	# "Volume: 0.40" or "Volume: 0.40 [MUTED]"
	out = run("wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@").split()
	if len(out) < 2:
		return None, False
	return round(float(out[1]) * 100), "[MUTED]" in out


def volume_set(v):
	run("wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", "%.2f" % (v / 100))
	if v > 0:
		run("wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0")


def battery():
	base = "/sys/class/power_supply"
	try:
		names = os.listdir(base)
	except OSError:
		return ""
	for name in names:
		try:
			with open(os.path.join(base, name, "type")) as f:
				if f.read().strip() != "Battery":
					continue
			with open(os.path.join(base, name, "capacity")) as f:
				cap = f.read().strip()
			with open(os.path.join(base, name, "status")) as f:
				status = f.read().strip()
		except OSError:
			continue
		return "%s%%%s" % (cap, " · заряжается" if status == "Charging" else "")
	return ""


class Tile(Gtk.Box):
	def __init__(self, panel, icon, title, state=None, toggle=None, action=None, more=None):
		super().__init__()
		self.panel, self.state, self.toggle, self.action = panel, state, toggle, action
		self.on = False
		self.get_style_context().add_class("tile")

		main = Gtk.Button()
		main.connect("clicked", self.clicked)
		box = Gtk.Box(spacing=10)
		self.icon = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.LARGE_TOOLBAR)
		box.pack_start(self.icon, False, False, 0)
		text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
		label = Gtk.Label(label=title, xalign=0)
		label.get_style_context().add_class("tile-title")
		self.sub = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, max_width_chars=12)
		self.sub.get_style_context().add_class("tile-sub")
		text.pack_start(label, False, False, 0)
		text.pack_start(self.sub, False, False, 0)
		box.pack_start(text, True, True, 0)
		main.add(box)
		self.pack_start(main, True, True, 0)

		if more:
			btn = Gtk.Button.new_from_icon_name("pan-end-symbolic", Gtk.IconSize.BUTTON)
			btn.get_style_context().add_class("more")
			btn.connect("clicked", lambda _b: panel.launch(*more))
			self.pack_end(btn, False, False, 0)

	def refresh(self):
		if not self.state:
			return
		on, sub = self.state()
		self.on = bool(on)
		self.sub.set_text(sub)
		ctx = self.get_style_context()
		(ctx.add_class if on else ctx.remove_class)("on")
		(ctx.add_class if on is None else ctx.remove_class)("off-limits")

	def clicked(self, _btn):
		if self.action:
			self.panel.launch(*self.action)
			return
		self.toggle(not self.on)
		# rfkill and NetworkManager settle a moment later
		self.panel.refresh()
		GLib.timeout_add(700, self.panel.refresh_once)


class Slider(Gtk.Box):
	def __init__(self, icon, setter, icon_clicked=None):
		super().__init__(spacing=8)
		self.setter, self.pending = setter, None
		btn = Gtk.Button()
		btn.get_style_context().add_class("slider-icon")
		self.icon = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.LARGE_TOOLBAR)
		btn.add(self.icon)
		if icon_clicked:
			btn.connect("clicked", icon_clicked)
		self.pack_start(btn, False, False, 0)
		self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
		self.scale.set_draw_value(False)
		self.handler = self.scale.connect("value-changed", self.changed)
		self.pack_start(self.scale, True, True, 0)

	def set(self, value):
		self.scale.handler_block(self.handler)
		self.scale.set_value(value)
		self.scale.handler_unblock(self.handler)

	def changed(self, scale):
		# coalesce the stream of values while a finger drags
		if self.pending is None:
			self.pending = GLib.timeout_add(80, self.apply)

	def apply(self):
		self.pending = None
		self.setter(int(self.scale.get_value()))
		return False


class Panel(Gtk.Application):
	def __init__(self, hidden):
		super().__init__(application_id="org.pero.Panel")
		self.hidden_start = hidden
		self.win = None

	def do_activate(self):
		if self.win is None:
			self.build()
			self.hold()
			if self.hidden_start:
				return
		if self.win.get_visible():
			self.win.hide()
		else:
			self.show()

	def build(self):
		provider = Gtk.CssProvider()
		provider.load_from_data(CSS)
		Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider,
			Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

		win = self.win = Gtk.Window(application=self, title="Панель")
		win.get_style_context().add_class("pero-panel")
		win.set_decorated(False)
		win.set_skip_taskbar_hint(True)
		win.set_skip_pager_hint(True)
		win.set_keep_above(True)
		win.set_type_hint(Gdk.WindowTypeHint.DIALOG)
		win.connect("delete-event", lambda w, _e: w.hide() or True)
		win.connect("focus-out-event", lambda w, _e: w.hide())
		win.connect("key-press-event", lambda w, e: e.keyval == Gdk.KEY_Escape and w.hide())

		root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, margin=22)
		win.add(root)

		head = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
		self.clock = Gtk.Label(xalign=0)
		self.clock.get_style_context().add_class("clock")
		self.date = Gtk.Label(xalign=0)
		self.date.get_style_context().add_class("date")
		self.batt = Gtk.Label(xalign=0)
		self.batt.get_style_context().add_class("battery")
		for w in (self.clock, self.date, self.batt):
			head.pack_start(w, False, False, 0)
		root.pack_start(head, False, False, 0)

		self.tiles = [
			Tile(self, "network-wireless-symbolic", "Wi-Fi", wifi_state, wifi_toggle, more=("nm-connection-editor",)),
			Tile(self, "bluetooth-active-symbolic", "Bluetooth", bt_state, bt_toggle, more=("blueman-manager",)),
			Tile(self, "airplane-mode-symbolic", "Режим полёта", airplane_state, airplane_toggle),
			Tile(self, "rotation-allowed-symbolic", "Автоповорот", rotation_state, rotation_toggle),
			Tile(self, "power-profile-power-saver-symbolic", "Экономия", saver_state, saver_toggle),
			Tile(self, "notifications-disabled-symbolic", "Не беспокоить", dnd_state, dnd_toggle),
			Tile(self, "input-keyboard-symbolic", "Клавиатура", action=("pero-keyboard",)),
			Tile(self, "view-refresh-symbolic", "Повернуть", action=("pero-rotate", "next")),
		]
		self.tiles[6].sub.set_text("Экранная")
		self.tiles[7].sub.set_text("На 90°")
		grid = Gtk.Grid(row_spacing=10, column_spacing=10, column_homogeneous=True)
		for i, tile in enumerate(self.tiles):
			grid.attach(tile, i % 2, i // 2, 1, 1)
		root.pack_start(grid, False, False, 0)

		self.bright = Slider("display-brightness-symbolic", brightness_set)
		self.volume = Slider("audio-volume-high-symbolic", volume_set, self.mute)
		root.pack_start(self.bright, False, False, 0)
		root.pack_start(self.volume, False, False, 0)

		actions = Gtk.Box(spacing=0, homogeneous=True)
		for icon, label, cmd in (
			("applets-screenshooter-symbolic", "Снимок", ("xfce4-screenshooter", "-f", "-d", "1")),
			("preferences-system-symbolic", "Настройки", ("xfce4-settings-manager",)),
			("system-lock-screen-symbolic", "Блокировка", ("xflock4",)),
			("weather-clear-night-symbolic", "Сон", ("systemctl", "suspend")),
			("system-shutdown-symbolic", "Выключить", ("xfce4-session-logout",)),
		):
			col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
			btn = Gtk.Button(halign=Gtk.Align.CENTER)
			btn.get_style_context().add_class("action")
			btn.add(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.LARGE_TOOLBAR))
			btn.connect("clicked", lambda _b, c=cmd: self.launch(*c))
			lab = Gtk.Label(label=label)
			lab.get_style_context().add_class("action-label")
			col.pack_start(btn, False, False, 0)
			col.pack_start(lab, False, False, 0)
			actions.pack_start(col, True, True, 0)
		root.pack_end(actions, False, False, 0)

		root.show_all()
		GLib.timeout_add_seconds(1, self.tick)

	def show(self):
		display = Gdk.Display.get_default()
		mon = display.get_primary_monitor() or display.get_monitor(0)
		area = mon.get_workarea()
		self.win.set_size_request(WIDTH, area.height)
		self.win.resize(WIDTH, area.height)
		self.win.move(area.x + area.width - WIDTH, area.y)
		self.tick()
		self.win.present()
		# fill in the states once the window is on screen: nmcli and friends take a moment
		GLib.idle_add(self.refresh_once)

	def tick(self):
		if self.win.get_visible() or self.clock.get_text() == "":
			self.clock.set_text(time.strftime("%H:%M"))
			self.date.set_text(time.strftime("%A, %-d %B").capitalize())
			self.batt.set_text(battery())
		return True

	def refresh(self):
		for tile in self.tiles:
			tile.refresh()
		b = brightness_get()
		self.bright.set_visible(b is not None)
		if b is not None:
			self.bright.set(b)
		v, muted = volume_get()
		self.volume.set_visible(v is not None)
		if v is not None:
			self.volume.set(0 if muted else v)
			self.volume.icon.set_from_icon_name(
				"audio-volume-muted-symbolic" if muted or v == 0 else "audio-volume-high-symbolic",
				Gtk.IconSize.LARGE_TOOLBAR)

	def refresh_once(self):
		self.refresh()
		return False

	def mute(self, _btn):
		run("wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle")
		self.refresh()

	def launch(self, *cmd):
		self.win.hide()
		spawn(*cmd)


if __name__ == "__main__":
	locale.setlocale(locale.LC_ALL, "")
	sys.exit(Panel("--hidden" in sys.argv).run([sys.argv[0]]))
