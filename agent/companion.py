"""Desktop companion: the avatar lives on the taskbar in its own transparent always-on-top window.

Run as a separate process:  pythonw -m agent.companion   (agent.desktop starts / stops it following prefs.companion)

How the transparency works on Windows 11: pywebview's own window can't be see-through with WebView2, so the WebView2
control is re-parented into our own top-level window created with WS_EX_NOREDIRECTIONBITMAP (no GDI surface -> only the
web page's DirectComposition pixels are visible, with real per-pixel alpha).

Python owns the body (everything in PHYSICAL pixels, display scaling handled here):
  - floor = top edge of the taskbar (bottom of the monitor work area); the avatar stands or sits on it
  - walking along the taskbar, dragging with the mouse, falling down with gravity after a drop
  - click-through: the window is wide (a dance or a raised arm never hits its edge) and layered; it lets the mouse
    through (WS_EX_TRANSPARENT) unless the cursor is over the character / bubble / menu — nothing is clipped
  - hidden while a fullscreen app / game is in front, no taskbar button, never steals focus
JS (web/app/companion.js) is the brain and the animation; it calls the methods of CompanionAPI.
"""
import ctypes
import os
import random
import threading
import time
from ctypes import wintypes
from .logs import quiet

u32, gdi, k32 = ctypes.windll.user32, ctypes.windll.gdi32, ctypes.windll.kernel32
u32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
u32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
u32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
u32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
u32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HANDLE, wintypes.BOOL]
u32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
u32.MonitorFromPoint.restype = wintypes.HANDLE
u32.GetForegroundWindow.restype = wintypes.HWND
u32.GetDpiForWindow.argtypes = [wintypes.HWND]
u32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
u32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
u32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
u32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
u32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
u32.DefWindowProcW.restype = ctypes.c_ssize_t
u32.CreateWindowExW.restype = wintypes.HWND
u32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
u32.LoadCursorW.restype = wintypes.HANDLE
k32.GetModuleHandleW.restype = wintypes.HMODULE
k32.OpenEventW.restype = wintypes.HANDLE
k32.OpenMutexW.restype = wintypes.HANDLE
k32.CreateMutexW.restype = wintypes.HANDLE
gdi.CreateRectRgn.restype = wintypes.HANDLE
gdi.CombineRgn.argtypes = [wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE, ctypes.c_int]
gdi.DeleteObject.argtypes = [wintypes.HANDLE]

HWND_TOPMOST, HWND_NOTOPMOST, HWND_TOP = wintypes.HWND(-1), wintypes.HWND(-2), wintypes.HWND(0)
u32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
u32.GetWindow.restype = wintypes.HWND
GW_HWNDPREV = 3
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_NOACTIVATE = 0x1, 0x2, 0x4, 0x10
WS_EX_TOPMOST, WS_EX_TOOLWINDOW, WS_EX_APPWINDOW, WS_EX_NOACTIVATE, WS_EX_NOREDIRECTIONBITMAP = 0x8, 0x80, 0x40000, 0x08000000, 0x00200000
WS_POPUP, WS_VISIBLE = 0x80000000, 0x10000000
W_CSS, H_CSS = 520, 440
WS_EX_LAYERED, WS_EX_TRANSPARENT = 0x80000, 0x20
u32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_ubyte, wintypes.DWORD]
MUTEX = "Local\\RENARD_companion_single"
DESKTOP_MUTEX, SHOW_EVENT, MIC_EVENT = "Local\\RENARD_desktop_single", "Local\\RENARD_desktop_show", "Local\\RENARD_desktop_mic"

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


u32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]


def monitor_at(x: float, y: float) -> tuple[tuple, tuple]:
    """(monitor rect, work-area rect) of the monitor nearest to a physical point."""
    mi = MONITORINFO(); mi.cbSize = ctypes.sizeof(MONITORINFO)
    u32.GetMonitorInfoW(u32.MonitorFromPoint(wintypes.POINT(int(x), int(y)), 2), ctypes.byref(mi))
    m, w = mi.rcMonitor, mi.rcWork
    return (m.left, m.top, m.right, m.bottom), (w.left, w.top, w.right, w.bottom)


def cursor() -> tuple[int, int]:
    p = wintypes.POINT(); u32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


dwm = ctypes.windll.dwmapi
for _f in ("IsWindow", "IsWindowVisible", "IsIconic", "IsZoomed"):
    getattr(u32, _f).argtypes = [wintypes.HWND]
u32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
SKIP_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "RenardCompanionHost",
                "Windows.UI.Core.CoreWindow", "XamlExplorerHostIslandWindow", "TopLevelWindowForOverflowXamlIsland"}
OWN_PID = os.getpid()


def frame_rect(h) -> tuple[int, int, int, int]:
    """Visible frame of a window (without the invisible resize borders of Windows 10/11)."""
    r = wintypes.RECT()
    if dwm.DwmGetWindowAttribute(h, 9, ctypes.byref(r), ctypes.sizeof(r)) != 0:
        u32.GetWindowRect(h, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def perchable(h, scale: float) -> bool:
    """A normal app window with room above its frame: visible, not minimized / maximized / fullscreen, not ours."""
    try:
        if not h or not u32.IsWindow(h) or not u32.IsWindowVisible(h) or u32.IsIconic(h) or u32.IsZoomed(h):
            return False
        if u32.GetWindowTextLengthW(h) == 0 or u32.GetWindowLongPtrW(h, -20) & WS_EX_TOOLWINDOW:
            return False
        cls = ctypes.create_unicode_buffer(64); u32.GetClassNameW(h, cls, 64)
        if cls.value in SKIP_CLASSES:
            return False
        pid = wintypes.DWORD(); u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if pid.value == OWN_PID:
            return False
        v = ctypes.c_int(0); dwm.DwmGetWindowAttribute(h, 14, ctypes.byref(v), 4)
        if v.value:
            return False
        l, t, r, b = frame_rect(h)
        if r - l < 320 * scale or b - t < 150 * scale:
            return False
        mon, work = monitor_at((l + r) / 2, (t + b) / 2)
        if l <= mon[0] and t <= mon[1] and r >= mon[2] and b >= mon[3]:
            return False
        return t >= work[1] + 110 * scale
    except Exception:
        return False


def windows_z(scale: float) -> list:
    """Perchable windows, topmost first."""
    out = []

    def cb(h, _):
        if perchable(h, scale):
            out.append(h)
        return True
    u32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def _host_proc(h, m, wp, lp):
    if m == 0x0014:
        return 1
    if m == 0x0021:
        return 3
    return u32.DefWindowProcW(h, m, wp, lp)


_HOST_PROC = WNDPROC(_host_proc)


class Body:
    def __init__(self, size: float = 1.0, hide_fullscreen: bool = True):
        self.size, self.hide_fs = size, hide_fullscreen
        self.win = self.hwnd = None
        self.x = self.y = 0.0
        self.w = self.h = 0
        self.scale = 1.0
        self.anchor = H_CSS - 34
        self.ax = W_CSS / 2
        self.margin = 95
        self.perch = {"kind": "floor"}
        self.auto = False
        self.fg_seen, self.fg_since, self.last_hop = None, 0.0, 0.0
        self.hop = None
        self.drop_wins: list = []
        self.mode = "ground"
        self.target = self.speed = 0.0
        self.vy = self.vx = 0.0
        self.grab = (0, 0)
        self.hidden = False
        self.alive = True
        self.topmost = True
        self.wrel = None
        self.prev_fr, self.wob_t, self.flips = None, 0.0, []
        self.hit: list = []
        self.menu_on = False
        self.passthru = None
        self.btn_prev = 0
        self.api = CompanionAPI(self)

    def create(self):
        import webview
        from .launcher import BASE
        w, h = int(W_CSS * self.size), int(H_CSS * self.size)
        self.win = webview.create_window("Renard companion src", BASE + "/app/companion.html", width=w, height=h, x=0, y=0,
                                         frameless=True, on_top=False, transparent=True, easy_drag=False, focus=False,
                                         resizable=False, js_api=self.api, background_color="#000000")
        self.win.events.shown += lambda: threading.Thread(target=self._attach, daemon=True).start()
        return self.win

    def _host_thread(self, ready: threading.Event):
        inst = k32.GetModuleHandleW(None)
        wc = WNDCLASSW(); wc.lpfnWndProc = _HOST_PROC; wc.lpszClassName = "RenardCompanionHost"; wc.hInstance = inst
        wc.hCursor = u32.LoadCursorW(None, 32512)
        u32.RegisterClassW(ctypes.byref(wc))
        ex = WS_EX_NOREDIRECTIONBITMAP | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_LAYERED | WS_EX_TRANSPARENT
        self.hwnd = u32.CreateWindowExW(ex, "RenardCompanionHost", "Renard companion", WS_POPUP | WS_VISIBLE,
                                        int(self.x), int(self.y), self.w, self.h, None, None, inst, None)
        u32.SetLayeredWindowAttributes(self.hwnd, 0, 255, 2)
        self.passthru = True
        ready.set()
        msg = wintypes.MSG()
        while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            u32.TranslateMessage(ctypes.byref(msg)); u32.DispatchMessageW(ctypes.byref(msg))

    def _attach(self):
        """Move the WebView2 control from pywebview's (opaque) form into our see-through host window."""
        from System import Action
        from System.Drawing import Color
        form = self.win.native
        form_h = wintypes.HWND(int(str(form.Handle)))
        try:
            self.scale = (u32.GetDpiForWindow(form_h) or 96) / 96
        except Exception:
            self.scale = 1.0
        self.w, self.h = int(W_CSS * self.size * self.scale), int(H_CSS * self.size * self.scale)
        _, work = monitor_at(u32.GetSystemMetrics(0) // 2, u32.GetSystemMetrics(1) // 2)
        self.x = work[2] - self.w - 60 * self.scale
        self.y = work[3] - self.anchor * self.scale
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
        threading.Thread(target=self._host_thread, args=(ready,), daemon=True).start()
        ready.wait(5)
        wv_h = wintypes.HWND(info["wv"])
        u32.SetParent(wv_h, self.hwnd)

        def grow():
            from System.Drawing import Point, Size
            from System.Windows.Forms import DockStyle
            wv = form.browser.webview
            wv.Dock = getattr(DockStyle, "None")
            wv.Location = Point(0, 0)
            wv.Size = Size(self.w, self.h)
        try:
            form.Invoke(Action(grow))
        except Exception as e:
            print("companion grow:", e)
        u32.SetWindowPos(wv_h, None, 0, 0, self.w, self.h, SWP_NOZORDER | SWP_NOACTIVATE)
        ex = u32.GetWindowLongPtrW(form_h, -20)
        u32.SetWindowLongPtrW(form_h, -20, (ex | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW)
        u32.SetWindowPos(form_h, None, -32000, -32000, 0, 0, SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
        self.place()
        self.loop()

    def place(self):
        """Move the window. On a window frame he is part of that window's world: right above it in the z-order, so any
        window you bring in front covers him. On the taskbar / in the corner, while carried or falling: always on top."""
        if not self.hwnd or self.hidden:
            return
        flags = SWP_NOSIZE | SWP_NOACTIVATE
        after = HWND_TOPMOST
        if self.perch["kind"] == "window" and self.mode in ("ground", "walk"):
            after = self.z_after(self.perch["hwnd"])
            if after is None:
                flags |= SWP_NOZORDER
            if self.topmost:
                u32.SetWindowPos(self.hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)
                self.topmost = False
        else:
            self.topmost = True
        u32.SetWindowPos(self.hwnd, after, int(self.x), int(self.y), 0, 0, flags)

    def z_after(self, h):
        """The window that must stay above us so that we sit directly above `h` (None: we already do)."""
        prev = u32.GetWindow(h, GW_HWNDPREV)
        if prev == self.hwnd:
            return None
        if not prev or u32.GetWindowLongPtrW(prev, -20) & WS_EX_TOPMOST:
            return HWND_TOP
        return prev

    def knock(self, vx: float = 0.0, why: str = "shake"):
        """Off the window: shaken, dragged too fast, closed or minimized under him. Falls with the window's momentum and
        may land on another window frame below."""
        old = self.perch.get("hwnd")
        self.perch, self.auto, self.wrel = {"kind": "floor"}, False, None
        self.mode, self.vy, self.vx = "fall", -260 * self.scale, max(-2500.0, min(2500.0, vx * .5))
        self.drop_wins = [w for w in windows_z(self.scale) if w != old]
        self.prev_fr, self.flips = None, []
        self.js(f"window.nxKnocked && nxKnocked('{why}')")

    def js(self, code: str):
        try:
            (getattr(self.win, "run_js", None) or self.win.evaluate_js)(code)
        except Exception:
            quiet()

    def work(self):
        return monitor_at(self.x + self.w / 2, self.y + self.h / 2)[1]

    def floor_y(self):
        return self.work()[3] - self.anchor * self.scale

    def clamp_x(self, x):
        """Window x so that the CHARACTER (ax inside the window) stays on the screen; the empty margin may hang out."""
        l, _, r, _ = self.work()
        a, m = self.ax * self.scale, 50 * self.scale
        return max(l + m - a, min(r - m - a, x))

    def update_hit(self):
        cx, cy = cursor()
        lx, ly = cx - self.x, cy - self.y
        over = any(x <= lx <= x + w and y <= ly <= y + h for x, y, w, h in self.hit)
        catch = over or self.mode == "drag"
        if catch == (not self.passthru) or not self.hwnd:
            pass
        else:
            ex = u32.GetWindowLongPtrW(self.hwnd, -20)
            ex = (ex & ~WS_EX_TRANSPARENT) if catch else (ex | WS_EX_TRANSPARENT)
            u32.SetWindowLongPtrW(self.hwnd, -20, ex)
            self.passthru = not catch
        if self.menu_on:
            btn = (u32.GetAsyncKeyState(0x01) & 0x8000) | (u32.GetAsyncKeyState(0x02) & 0x8000) | \
                  (u32.GetAsyncKeyState(0x04) & 0x8000)
            pressed = btn and not self.btn_prev
            if (pressed and not over) or (u32.GetAsyncKeyState(0x1B) & 0x8000):
                self.menu_on = False
                self.js("window.nxCloseMenu && nxCloseMenu()")
            self.btn_prev = btn
        else:
            self.btn_prev = 0

    def perch_xy(self):
        """Window position for the current perch, None for the free floor or a perch that is gone."""
        p, s = self.perch, self.scale
        if p["kind"] == "window":
            h = p["hwnd"]
            if not perchable(h, s):
                return None
            l, t, r, b = frame_rect(h)
            if p.get("rel") is not None:
                cx = l + p["rel"] * s
            else:
                cx = r - 210 * s if r - l > 560 * s else (l + r) / 2
            cx = max(l + 30 * s, min(r - 30 * s, cx))
            return cx - self.ax * s, t - self.anchor * s
        if p["kind"] == "corner":
            work = self.work()
            return work[2] - (self.margin + self.ax) * s, work[3] - self.anchor * s
        return None

    def perch_to(self, kind: str, hwnd=None, rel=None, hop=True) -> str:
        s = self.scale
        if kind == "window":
            if hwnd is None:
                fg = u32.GetForegroundWindow()
                hwnd = fg if perchable(fg, s) else None
            if hwnd is None:
                kind = "corner"
        self.perch = {"kind": kind, "hwnd": hwnd, "rel": rel} if kind == "window" else {"kind": kind}
        if kind == "floor":
            if self.mode not in ("drag", "walk"):
                self.mode, self.vy = "fall", 0.0
            return kind
        if hop and self.mode not in ("drag",):
            self.hop = {"x0": self.x, "y0": self.y, "t0": time.perf_counter(), "dur": .55, "arc": 110 * s}
            self.mode, self.last_hop = "hop", time.perf_counter()
            self.js(f"window.nxHop && nxHop('{kind}')")
        return kind

    def auto_perch(self, now: float):
        """Auto mode: hop onto the window you work in (after it stays active for a while), corner otherwise."""
        fg = u32.GetForegroundWindow()
        if fg != self.fg_seen:
            self.fg_seen, self.fg_since = fg, now
            return
        if now - self.fg_since < 10 or now - self.last_hop < 60:
            return
        cur = self.perch
        if perchable(fg, self.scale):
            if cur["kind"] != "window" or cur.get("hwnd") != fg:
                self.perch_to("window", fg)
        elif fg and u32.IsZoomed(fg) and cur["kind"] == "window":
            self.perch_to("corner")

    def loop(self):
        last, top_t, fs_t, drag_t, auto_t = time.perf_counter(), 0.0, 0.0, 0.0, 0.0
        while self.alive:
            now = time.perf_counter(); dt = min(.05, now - last); last = now
            moved = False
            if self.mode == "drag":
                if not (u32.GetAsyncKeyState(0x01) & 0x8000):
                    self.mode, self.vy = "fall", 0.0
                    self.drop_wins = windows_z(self.scale)
                    self.js("window.nxDropped && nxDropped()")
                else:
                    cx, cy = cursor(); nx, ny = cx - self.grab[0], cy - self.grab[1]
                    self.vx = self.vx * .7 + ((nx - self.x) / max(dt, .001)) * .3
                    self.x, self.y = nx, ny; moved = True
                    if now - drag_t > .1:
                        drag_t = now; self.js(f"window.nxDrag && nxDrag({self.vx / self.scale:.0f})")
            elif self.mode == "fall":
                s = self.scale
                self.vy += 2600 * s * dt
                foot0 = self.y + self.anchor * s
                self.y += self.vy * dt; moved = True
                if self.vx:
                    self.x = self.clamp_x(self.x + self.vx * dt); self.vx *= max(0.0, 1 - dt * 1.8)
                foot1, cx = self.y + self.anchor * s, self.x + self.ax * s
                landed = None
                for h in self.drop_wins:
                    l, t, r, b = frame_rect(h)
                    if l + 20 * s < cx < r - 20 * s and foot0 <= t <= foot1:
                        landed = (h, l, t)
                        break
                    if l <= cx <= r and t < foot0 < b:
                        break
                fy = self.floor_y()
                if landed:
                    h, l, t = landed
                    self.perch = {"kind": "window", "hwnd": h, "rel": (cx - l) / s}
                    self.y, self.mode, self.vx, self.prev_fr = t - self.anchor * s, "ground", 0.0, None
                    self.js(f"window.nxLanded && nxLanded({self.vy / s:.0f}, 'window')")
                elif self.y >= fy:
                    self.y, self.mode, self.vx = fy, "ground", 0.0
                    self.perch = {"kind": "floor"}
                    self.js(f"window.nxLanded && nxLanded({self.vy / s:.0f}, 'floor')")
            elif self.mode == "hop":
                hp = self.hop
                u = min(1.0, (now - hp["t0"]) / hp["dur"])
                end = self.perch_xy() or (self.x, self.floor_y())
                self.x = hp["x0"] + (end[0] - hp["x0"]) * u
                self.y = hp["y0"] + (end[1] - hp["y0"]) * u - hp["arc"] * __import__("math").sin(3.14159 * u)
                moved = True
                if u >= 1:
                    self.mode = "ground"
                    self.js(f"window.nxLanded && nxLanded(0, '{self.perch['kind']}')")
            elif self.mode == "walk" and self.perch["kind"] == "window":
                p = self.perch
                d = self.wrel - (p.get("rel") or 0)
                step = self.speed * dt
                if abs(d) <= step:
                    p["rel"], self.mode, self.wrel = self.wrel, "ground", None
                    self.js("window.nxArrived && nxArrived()")
                else:
                    p["rel"] = (p.get("rel") or 0) + (step if d > 0 else -step)
                xy = self.perch_xy()
                if xy is None:
                    self.knock(0, "gone")
                else:
                    self.x, self.y = xy; moved = True
                    self.prev_fr = frame_rect(p["hwnd"])
            elif self.mode == "walk":
                step = self.speed * self.scale * dt
                d = self.target - self.x
                if abs(d) <= step:
                    self.x, self.mode = self.target, "ground"
                    self.js("window.nxArrived && nxArrived()")
                else:
                    self.x += step if d > 0 else -step
                self.y += (self.floor_y() - self.y) * min(1, dt * 10)
                moved = True
            elif self.perch["kind"] == "window":
                xy = self.perch_xy()
                if xy is None:
                    self.knock(0, "gone")
                else:
                    fr = frame_rect(self.perch["hwnd"])
                    if self.prev_fr and fr != self.prev_fr and dt > 0:
                        vx = (fr[0] - self.prev_fr[0]) / dt / self.scale
                        vy = (fr[1] - self.prev_fr[1]) / dt / self.scale
                        sp = (vx * vx + vy * vy) ** .5
                        if abs(vx) > 700:
                            self.flips = [f for f in self.flips if now - f[0] < .7]
                            if not self.flips or (self.flips[-1][1] > 0) != (vx > 0):
                                self.flips.append((now, vx))
                        if len(self.flips) >= 3 or sp > 5200:
                            self.knock(vx * self.scale, "shake" if len(self.flips) >= 3 else "fast")
                            continue
                        if sp > 350 and now - self.wob_t > .12:
                            self.wob_t = now
                            self.js(f"window.nxWobble && nxWobble({vx:.0f}, {vy:.0f})")
                    self.prev_fr = fr
                    if abs(xy[0] - self.x) > .5 or abs(xy[1] - self.y) > .5:
                        self.x, self.y = xy; moved = True
            elif self.perch["kind"] != "floor":
                xy = self.perch_xy()
                if xy is None:
                    self.perch_to("corner")
                else:
                    k = min(1.0, dt * 18)
                    if abs(xy[0] - self.x) > .5 or abs(xy[1] - self.y) > .5:
                        self.x += (xy[0] - self.x) * k; self.y += (xy[1] - self.y) * k; moved = True
            else:
                fy = self.floor_y()
                if abs(fy - self.y) > .5:
                    self.y += (fy - self.y) * min(1, dt * 8); moved = True
            if self.auto and self.mode == "ground" and now - auto_t > .5:
                auto_t = now
                self.auto_perch(now)
            if moved:
                self.place()
            if not self.hidden:
                self.update_hit()
            if now - top_t > 1.5 and self.mode != "drag":
                top_t = now; self.place()
            if now - fs_t > 1.0:
                fs_t = now; self.check_fullscreen()
            time.sleep(1 / 60)

    def check_fullscreen(self):
        """Hide over fullscreen apps/games, come back afterwards."""
        if not self.hide_fs:
            return
        fg = u32.GetForegroundWindow()
        full = False
        if fg and fg != self.hwnd:
            cls = ctypes.create_unicode_buffer(64); u32.GetClassNameW(fg, cls, 64)
            if cls.value not in ("Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "RenardCompanionHost"):
                r = wintypes.RECT(); u32.GetWindowRect(fg, ctypes.byref(r))
                mon, _ = monitor_at((r.left + r.right) // 2, (r.top + r.bottom) // 2)
                full = r.left <= mon[0] and r.top <= mon[1] and r.right >= mon[2] and r.bottom >= mon[3]
        if full and not self.hidden:
            self.hidden = True; u32.ShowWindow(self.hwnd, 0)
        elif not full and self.hidden:
            self.hidden = False; u32.ShowWindow(self.hwnd, 4); self.place()


def _signal(name: str) -> bool:
    h = k32.OpenEventW(0x0002, False, name)
    if h:
        k32.SetEvent(wintypes.HANDLE(h)); k32.CloseHandle(wintypes.HANDLE(h))
    return bool(h)


class CompanionAPI:
    """Called from companion.js as window.pywebview.api.<name>(...). Coordinates from JS are css px of the window."""

    def __init__(self, body):
        self._b = body

    def geom(self):
        b = self._b
        work = b.work()
        g = {"dpr": b.scale, "x": b.x, "y": b.y, "w": b.w, "h": b.h, "work": work, "mode": b.mode,
             "perch": b.perch["kind"], "auto": b.auto,
             "room": (b.y + b.anchor * b.scale - work[1]) / b.scale}
        if b.perch["kind"] == "window":
            l, t, r, _ = frame_rect(b.perch["hwnd"])
            g["win_w"] = (r - l) / b.scale
            g["rel"] = b.perch.get("rel") if b.perch.get("rel") is not None else (b.x + b.ax * b.scale - l) / b.scale
        return g

    def jump_down(self, direction=0):
        """Off the window frame he stands on: a little jump, then falls to the taskbar (or onto a window below)."""
        b = self._b
        if b.perch["kind"] != "window" or b.mode not in ("ground", "walk"):
            return False
        old = b.perch.get("hwnd")
        b.perch, b.auto, b.wrel = {"kind": "floor"}, False, None
        b.mode, b.vy, b.vx = "fall", -520 * b.scale, float(direction or 0) * 160 * b.scale
        b.drop_wins = [w for w in windows_z(b.scale) if w != old]
        return True

    def set_anchor(self, a, ax=None, margin=None):
        """a: css y of the floor contact; ax: css x of the character centre; margin: corner distance from the edge."""
        b = self._b
        try:
            b.anchor = max(0.0, min(H_CSS * b.size, float(a)))
            if ax is not None:
                ax = float(ax)
                if b.perch["kind"] == "floor" and b.mode in ("ground", "fall"):
                    b.x += (b.ax - ax) * b.scale
                b.ax = ax
            if margin is not None:
                b.margin = float(margin)
        except (TypeError, ValueError):
            pass
        return True

    def perch(self, kind="auto"):
        """Sit somewhere: corner (above the clock), window (top of the active window), auto, floor."""
        b = self._b
        if b.mode in ("drag", "fall"):
            return {"kind": b.perch["kind"]}
        b.auto = kind == "auto"
        if kind == "auto":
            kind = "window" if perchable(u32.GetForegroundWindow(), b.scale) else "corner"
            b.fg_seen, b.fg_since = u32.GetForegroundWindow(), time.perf_counter()
        cur = b.perch
        if kind == cur["kind"] and (kind != "window" or cur.get("hwnd") == u32.GetForegroundWindow()):
            return {"kind": kind}
        return {"kind": b.perch_to(kind)}

    def walk_to(self, where="random", speed=90):
        b = self._b
        if b.mode in ("drag", "fall", "hop"):
            return {"dir": 0}
        if b.perch["kind"] == "window" and where != "floor":
            h = b.perch["hwnd"]
            l, _, r, _ = frame_rect(h)
            s, width = b.scale, (r - l) / b.scale
            cur = b.perch.get("rel") if b.perch.get("rel") is not None else (b.x + b.ax * s - l) / s
            if where == "left":
                t = cur - random.uniform(120, 320)
            elif where == "right":
                t = cur + random.uniform(120, 320)
            elif where == "cursor":
                t = (cursor()[0] - l) / s
            elif where == "center":
                t = width / 2
            elif where in ("edge_left", "edge_right"):
                t = 30 if where == "edge_left" else width - 30
            elif isinstance(where, (int, float)):
                t = width * float(where)
            else:
                t = random.uniform(40, max(41, width - 40))
            t = max(30, min(width - 30, t))
            if abs(t - cur) < 20:
                return {"dir": 0, "on": "window"}
            b.perch["rel"], b.wrel, b.speed, b.mode = cur, t, float(speed or 90), "walk"
            return {"dir": 1 if t > cur else -1, "dist": abs(t - cur), "on": "window"}
        l, _, r, _ = b.work()
        if where == "left":
            tx = b.x - random.uniform(250, 600) * b.scale
        elif where == "right":
            tx = b.x + random.uniform(250, 600) * b.scale
        elif where == "cursor":
            tx = cursor()[0] - b.ax * b.scale
        elif where == "center":
            tx = (l + r) / 2 - b.ax * b.scale
        elif isinstance(where, (int, float)):
            tx = l + (r - l) * float(where) - b.w / 2
        else:
            tx = random.uniform(l + (r - l) * .35, r - b.w)
        tx = b.clamp_x(tx)
        if abs(tx - b.x) < 30 * b.scale:
            return {"dir": 0}
        b.perch, b.auto = {"kind": "floor"}, False
        b.target, b.speed, b.mode = tx, float(speed or 90), "walk"
        return {"dir": 1 if tx > b.x else -1, "dist": abs(tx - b.x) / b.scale}

    def stop(self):
        if self._b.mode == "walk":
            self._b.mode, self._b.wrel = "ground", None
        return True

    def drag_start(self, gx, gy):
        b = self._b
        b.grab = (float(gx) * b.scale, float(gy) * b.scale)
        b.vx, b.mode, b.auto = 0.0, "drag", False
        b.perch = {"kind": "floor"}
        return True

    def region(self, rects, menu_open=False):
        """Only these css rects [[x, y, w, h], ...] catch the mouse; the rest of the window lets clicks through.
        (It used to be a window region — that also CUT the drawing: a raised arm vanished at the edge.)"""
        b = self._b
        s = b.scale
        b.hit = [(x * s, y * s, w * s, h * s) for x, y, w, h in (rects or [])]
        b.menu_on = bool(menu_open)
        return True

    def debug(self, text=""):
        """State snapshot from companion.js -> data/logs/companion_state.json (live tests read it)."""
        try:
            from .config import DATA_DIR
            import json as _j
            st = _j.loads(text or "{}")
            b = self._b
            st.update({"win": [b.x, b.y, b.w, b.h], "anchor": b.anchor, "ax": b.ax, "perch": b.perch.get("kind"),
                       "mode_py": b.mode, "passthru": b.passthru, "t": time.time()})
            (DATA_DIR / "logs" / "companion_state.json").write_text(_j.dumps(st, ensure_ascii=False), encoding="utf-8")
        except Exception:
            quiet()
        return True

    def cursor(self):
        b = self._b
        cx, cy = cursor()
        return {"x": (cx - b.x) / b.scale, "y": (cy - b.y) / b.scale}

    def open_main(self):
        return _signal(SHOW_EVENT)

    def mic(self):
        return _signal(MIC_EVENT)


def main():
    import httpx
    from .config import DATA_DIR
    from .launcher import BASE
    k32.CreateMutexW(None, False, MUTEX)
    if k32.GetLastError() == 183:
        return
    from . import logs
    logs.setup("companion")
    try:
        c = httpx.get(BASE + "/api/prefs", timeout=5).json().get("companion", {})
    except Exception:
        c = {}
    body = Body(size=float(c.get("size") or 1.0), hide_fullscreen=bool(c.get("hide_fullscreen", True)))
    weather_on, weather_cap = (c.get("weather") or "off") != "off", bool(c.get("weather_capture"))

    def watchdog():
        """Leave when the Renard desktop app quits or the companion is switched off."""
        misses = 0
        while True:
            time.sleep(3)
            h = k32.OpenMutexW(0x00100000, False, DESKTOP_MUTEX)
            if not h:
                os._exit(0)
            k32.CloseHandle(wintypes.HANDLE(h))
            try:
                cc = httpx.get(BASE + "/api/prefs", timeout=3).json().get("companion", {})
                misses = 0
                if not cc.get("desktop") or not cc.get("enabled", True):
                    os._exit(0)
                if float(cc.get("size") or 1.0) != body.size or bool(cc.get("hide_fullscreen", True)) != body.hide_fs:
                    os._exit(0)
                if ((cc.get("weather") or "off") != "off") != weather_on or bool(cc.get("weather_capture")) != weather_cap:
                    os._exit(0)
            except Exception:
                misses += 1
                if misses > 40:
                    os._exit(0)

    threading.Thread(target=watchdog, daemon=True).start()
    import webview
    body.create()
    if weather_on:
        from .weather_layer import WeatherLayer
        WeatherLayer(show_in_screenshots=weather_cap).create()
    shared = not os.environ.get("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS")
    webview.start(private_mode=False, **({} if shared else {"storage_path": str(DATA_DIR / "webview_companion")}))


if __name__ == "__main__":
    main()
