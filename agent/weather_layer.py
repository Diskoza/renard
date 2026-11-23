"""Weather on the desktop (like Snowhush, but part of Renard): a full-screen, fully click-through layer where snow or rain
falls, piles up on the visible top edges of windows and on the taskbar, falls off a window you move or close, is
pushed aside by the cursor and melts when the real snowfall stops. The companion sees it too (catches snowflakes…).

Runs inside the companion process (python -m agent.companion) as a second WebView2 page, /app/weather.html.
Safety first: the layer must never catch the mouse. Right after it appears the point under the screen centre is
checked; if the layer would get the clicks, it is destroyed at once.
"""
import ctypes
import threading
import time
from ctypes import wintypes

from .companion import (HWND_TOPMOST, SWP_NOACTIVATE, SWP_NOSIZE, SWP_NOZORDER, WNDCLASSW, WNDPROC, WS_EX_NOACTIVATE,
                        WS_EX_NOREDIRECTIONBITMAP, WS_EX_TOOLWINDOW, WS_EX_TOPMOST, WS_POPUP, WS_VISIBLE, SKIP_CLASSES,
                        OWN_PID, WNDENUMPROC, cursor, dwm, frame_rect, k32, monitor_at, u32)
from .logs import quiet

WS_EX_LAYERED, WS_EX_TRANSPARENT = 0x80000, 0x20
u32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_ubyte, wintypes.DWORD]
u32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
u32.WindowFromPoint.argtypes = [wintypes.POINT]
u32.WindowFromPoint.restype = wintypes.HWND
u32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
u32.GetAncestor.restype = wintypes.HWND


def _proc(h, m, wp, lp):
    if m == 0x0084:
        return -1
    if m == 0x0021:
        return 3
    if m == 0x0014:
        return 1
    return u32.DefWindowProcW(h, m, wp, lp)


_PROC = WNDPROC(_proc)


def snow_windows(scale: float):
    """Normal visible windows, topmost first: (hwnd, l, t, r, b) in physical px."""
    out = []

    def cb(h, _):
        try:
            if not u32.IsWindowVisible(h) or u32.IsIconic(h) or u32.GetWindowTextLengthW(h) == 0:
                return True
            if u32.GetWindowLongPtrW(h, -20) & WS_EX_TOOLWINDOW:
                return True
            cls = ctypes.create_unicode_buffer(64); u32.GetClassNameW(h, cls, 64)
            if cls.value in SKIP_CLASSES or cls.value == "RenardWeatherHost":
                return True
            pid = wintypes.DWORD(); u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
            if pid.value == OWN_PID:
                return True
            v = ctypes.c_int(0); dwm.DwmGetWindowAttribute(h, 14, ctypes.byref(v), 4)
            if v.value:
                return True
            l, t, r, b = frame_rect(h)
            if r - l >= 160 * scale and b - t >= 80 * scale:
                out.append((h, l, t, r, b, bool(u32.IsZoomed(h))))
        except Exception:
            quiet()
        return True
    u32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def visible_tops(wins):
    """For every window, the parts of its top edge not covered by a window above it."""
    segs = []
    under_max = False
    for i, (h, l, t, r, b, zoomed) in enumerate(wins):
        if zoomed or under_max:
            parts = []
        else:
            parts = [(l, r)]
            for (_, l2, t2, r2, b2, _z) in wins[:i]:
                if t2 <= t <= b2:
                    nxt = []
                    for a, c in parts:
                        if r2 <= a or l2 >= c:
                            nxt.append((a, c))
                        else:
                            if l2 > a:
                                nxt.append((a, l2))
                            if r2 < c:
                                nxt.append((r2, c))
                    parts = nxt
                if not parts:
                    break
        segs.append((h, l, t, r, parts))
        under_max = under_max or zoomed
    return segs


class WeatherAPI:
    def __init__(self, layer):
        self._l = layer

    def scene(self):
        """Everything the page needs, in its css px: window tops (with the visible parts), the taskbar line, the cursor."""
        L = self._l
        s, (ml, mt, mr, mb) = L.scale, L.mon
        wins = snow_windows(s)
        out = []
        for h, l, t, r, parts in visible_tops(wins):
            if t <= mt + 2:
                continue
            out.append({"id": int(h), "l": (l - ml) / s, "r": (r - ml) / s, "y": (t - mt) / s,
                        "vis": [[(a - ml) / s, (c - ml) / s] for a, c in parts]})
        cx, cy = cursor()
        _, work = monitor_at((ml + mr) / 2, (mt + mb) / 2)
        return {"w": (mr - ml) / s, "h": (mb - mt) / s, "floor": (work[3] - mt) / s, "wins": out,
                "cursor": [(cx - ml) / s, (cy - mt) / s], "down": bool(u32.GetAsyncKeyState(0x01) & 0x8000), "hidden": L.hidden}


class WeatherLayer:
    def __init__(self, show_in_screenshots: bool = False):
        self.win = self.hwnd = None
        self.scale = 1.0
        self.mon = (0, 0, 1920, 1080)
        self.hidden = False
        self.capture = show_in_screenshots
        self.api = WeatherAPI(self)

    def create(self):
        import webview
        from .launcher import BASE
        self.win = webview.create_window("Renard weather src", BASE + "/app/weather.html", width=400, height=300, x=0, y=0,
                                         frameless=True, on_top=False, transparent=True, easy_drag=False, focus=False,
                                         resizable=False, js_api=self.api, background_color="#000000")
        self.win.events.shown += lambda: threading.Thread(target=self._attach, daemon=True).start()

    def _host(self, ready):
        inst = k32.GetModuleHandleW(None)
        wc = WNDCLASSW(); wc.lpfnWndProc = _PROC; wc.lpszClassName = "RenardWeatherHost"; wc.hInstance = inst
        u32.RegisterClassW(ctypes.byref(wc))
        l, t, r, b = self.mon
        ex = WS_EX_NOREDIRECTIONBITMAP | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_LAYERED | WS_EX_TRANSPARENT
        self.hwnd = u32.CreateWindowExW(ex, "RenardWeatherHost", "Renard weather", WS_POPUP | WS_VISIBLE, l, t, r - l, b - t,
                                        None, None, inst, None)
        u32.SetLayeredWindowAttributes(self.hwnd, 0, 255, 2)
        ready.set()
        msg = wintypes.MSG()
        while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            u32.TranslateMessage(ctypes.byref(msg)); u32.DispatchMessageW(ctypes.byref(msg))

    def _attach(self):
        from System import Action
        from System.Drawing import Color
        form = self.win.native
        form_h = wintypes.HWND(int(str(form.Handle)))
        self.scale = (u32.GetDpiForWindow(form_h) or 96) / 96
        mon, _ = monitor_at(u32.GetSystemMetrics(0) // 2, u32.GetSystemMetrics(1) // 2)
        self.mon = mon
        info = {}
        for _ in range(40):
            def probe():
                wv = form.browser.webview
                info["ok"] = wv.CoreWebView2 is not None
                if info["ok"]:
                    wv.DefaultBackgroundColor = Color.FromArgb(0, 0, 0, 0)
                    info["wv"] = int(str(wv.Handle))
            form.Invoke(Action(probe))
            if info.get("ok"):
                break
            time.sleep(.25)
        ready = threading.Event()
        threading.Thread(target=self._host, args=(ready,), daemon=True).start()
        ready.wait(5)
        wv_h = wintypes.HWND(info["wv"])
        l, t, r, b = self.mon
        u32.SetParent(wv_h, self.hwnd)

        def grow():
            from System.Drawing import Point, Size
            from System.Windows.Forms import DockStyle
            wv = form.browser.webview
            wv.Dock = getattr(DockStyle, "None")
            wv.Location = Point(0, 0)
            wv.Size = Size(r - l, b - t)
        form.Invoke(Action(grow))
        u32.SetWindowPos(wv_h, None, 0, 0, r - l, b - t, SWP_NOZORDER | SWP_NOACTIVATE)
        ex = u32.GetWindowLongPtrW(form_h, -20)
        u32.SetWindowLongPtrW(form_h, -20, (ex | WS_EX_TOOLWINDOW) & ~0x40000)
        u32.SetWindowPos(form_h, None, -32000, -32000, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
        if not self.capture:
            u32.SetWindowDisplayAffinity(self.hwnd, 0x11)
        time.sleep(1.5)
        if not self.clicks_pass():
            print("weather layer: it would catch the mouse — switched off")
            self.destroy()
            return
        self.loop()

    def clicks_pass(self) -> bool:
        """The point under the screen centre (and two more) must belong to some other window, never to the layer."""
        l, t, r, b = self.mon
        for fx, fy in ((.5, .5), (.25, .3), (.8, .7)):
            h = u32.WindowFromPoint(wintypes.POINT(int(l + (r - l) * fx), int(t + (b - t) * fy)))
            top = u32.GetAncestor(h, 2) if h else None
            if h and (top == self.hwnd or h == self.hwnd):
                return False
        return True

    def destroy(self):
        if self.hwnd:
            u32.ShowWindow(self.hwnd, 0)
            u32.PostMessageW(self.hwnd, 0x0010, 0, 0)
        self.hwnd = None

    def loop(self):
        """Stay on top; hide over fullscreen apps and games; re-check the click-through now and then."""
        k = 0
        while self.hwnd:
            fg = u32.GetForegroundWindow()
            full = False
            if fg:
                cls = ctypes.create_unicode_buffer(64); u32.GetClassNameW(fg, cls, 64)
                if cls.value not in ("Progman", "WorkerW", "Shell_TrayWnd", "RenardCompanionHost", "RenardWeatherHost"):
                    r = wintypes.RECT(); u32.GetWindowRect(fg, ctypes.byref(r))
                    m = self.mon
                    full = r.left <= m[0] and r.top <= m[1] and r.right >= m[2] and r.bottom >= m[3] and not u32.IsZoomed(fg)
            if full != self.hidden:
                self.hidden = full
                u32.ShowWindow(self.hwnd, 0 if full else 4)
            if not self.hidden:
                u32.SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOSIZE | 0x2 | SWP_NOACTIVATE)
            k += 1
            if k % 30 == 0 and not self.hidden and not self.clicks_pass():
                print("weather layer: caught the mouse — switched off"); self.destroy(); return
            time.sleep(1.0)
