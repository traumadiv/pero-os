// Pero OS: Firefox ESR on a 4 GB Cherry Trail tablet.
// Shipped in place (config/includes.chroot), so pero-update brings changes too.
pref("intl.locale.requested", "ru,en-US");
pref("apz.allow_zooming", true);
pref("apz.gtk.kinetic_scroll.enabled", true);
pref("browser.gesture.pinch.in", "");
pref("browser.gesture.pinch.out", "");
pref("dom.ipc.processCount", 2);
pref("browser.tabs.unloadOnLowMemory", true);
pref("layout.css.devPixelsPerPx", "-1.0");
pref("browser.toolbars.bookmarks.visibility", "never");
pref("datareporting.policy.firstRunURL", "");
pref("datareporting.policy.dataSubmissionPolicyBypassNotification", true);
pref("browser.aboutwelcome.enabled", false);

// Video: decode on the GPU through VA-API (i965 driver). Cherry Trail decodes
// H.264 in hardware but not VP9 or AV1, which YouTube prefers and the Atom then
// decodes in software at a few frames per second. Without VP9/AV1 on offer
// YouTube serves H.264.
pref("media.ffmpeg.vaapi.enabled", true);
pref("media.hardware-video-decoding.force-enabled", true);
pref("media.av1.enabled", false);
pref("media.mediasource.vp9.enabled", false);
pref("gfx.webrender.all", true);
// Decoded frames stay on the GPU (DMA-BUF through EGL): copying every 1080p
// frame through the Atom's memory was the other half of the stutter
pref("widget.dmabuf.force-enabled", true);
pref("gfx.x11-egl.force-enabled", true);
// Play and pause go out over MPRIS: pero-media-boost raises the clocks on play
pref("media.hardwaremediakeys.enabled", true);
