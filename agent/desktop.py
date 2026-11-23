"""Desktop window (like Claude/Codex app): python -m agent.desktop   (or pc-window.cmd)

- native window (WebView2) over the same web UI, server runs in background
- tray icon: show/hide, free VRAM, quit
- global hotkey Ctrl+Alt+Space: show/hide the window; Ctrl+Alt+V: voice (start/stop recording)
- closing the window hides it to tray (the agent keeps running)
"""
import ctypes
import os
import threading

import httpx
import pystray
import webview
from PIL import Image, ImageDraw

from . import logs
from .launcher import BASE, ensure_server
from .logs import quiet

log = logs.log

APP_ID = "Renard.Agent"
MUTEX_NAME, SHOW_EVENT, MIC_EVENT = "Local\\RENARD_desktop_single", "Local\\RENARD_desktop_show", "Local\\RENARD_desktop_mic"
HOTKEY_ID, VOICE_HOTKEY_ID = 1, 2
MOD_ALT, MOD_CONTROL, VK_SPACE, VK_V, WM_HOTKEY = 0x0001, 0x0002, 0x20, 0x56, 0x0312


from .config import WEB_DIR

ASSETS = WEB_DIR / "assets"


def make_icon(sleeping: bool = False) -> Image.Image:
    """Fox logo for the tray: awake (circle icon) or sleeping (when no model is loaded)."""
    f = ASSETS / ("renard_sleep_256.png" if sleeping else "renard_icon_512.png")
    if f.exists():
        return Image.open(f).convert("RGBA").resize((64, 64), Image.LANCZOS)
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse((4, 4, 60, 60), fill=(217, 119, 87, 255))
    return img


def single_instance() -> bool:
    """True if we are the first desktop process. Otherwise ask the running one to show its window."""
    if os.name != "nt":
        return True
    k32 = ctypes.windll.kernel32
    k32.CreateMutexW.restype = ctypes.c_void_p
    Desktop._mutex = k32.CreateMutexW(None, False, MUTEX_NAME)
    if k32.GetLastError() != 183:
        return True
    k32.OpenEventW.restype = ctypes.c_void_p
    h = k32.OpenEventW(0x0002, False, SHOW_EVENT)
    if h:
        k32.SetEvent(ctypes.c_void_p(h))
        k32.CloseHandle(ctypes.c_void_p(h))
    return False


MODS = {"ctrl": 0x0002, "control": 0x0002, "alt": 0x0001, "shift": 0x0004, "win": 0x0008}


def parse_combo(combo: str) -> tuple[int, int]:
    """'ctrl+alt+y' -> (MOD_CONTROL|MOD_ALT, VK_Y)"""
    from .winput import _vk
    mods, vk = 0, 0
    for k in combo.lower().replace(" ", "").split("+"):
        if k in MODS:
            mods |= MODS[k]
        elif k:
            try:
                vk = _vk(k)
            except Exception:
                vk = 0
    return mods, vk


class Desktop:
    _mutex = None

    def __init__(self, start_hidden: bool = False):
        self.window = None
        self.visible = not start_hidden
        self.quitting = False
        self.tray = None

    def show(self):
        if self.window:
            self.window.show()
            self.window.restore()
            self.visible = True
            threading.Thread(target=self.check_ui_after_show, daemon=True).start()

    def ui_age(self):
        """Seconds since the page last asked /api/status (it does every 3 s while visible). None = server down."""
        try:
            r = httpx.get(BASE + "/api/ping", timeout=4).json()
            return r.get("ui_age") if r.get("ui_age") is not None else 9999
        except Exception:
            return None

    def reload_page(self, why: str):
        log.warning(f"window reload: {why}")
        try:
            self.window.load_url(BASE)
        except Exception as e:
            log.error(f"window reload failed: {e}")

    def check_ui_after_show(self):
        """The window was hidden in the tray for hours (autostart): if its page is stuck, reload it right away."""
        import time
        time.sleep(4)
        age = self.ui_age()
        if age is not None and age > 8:
            self.reload_page(f"page silent {age:.0f}s after the window was shown")

    def ui_watch_loop(self):
        import time
        last_reload, down_since = 0.0, None
        while not self.quitting:
            time.sleep(15)
            age = self.ui_age()
            if age is None:
                if down_since is None:
                    down_since = time.time()
                    log.warning("server does not answer /api/ping")
                elif time.time() - down_since > 25:
                    log.warning("server down > 25 s -> starting it again")
                    try:
                        if ensure_server(120):
                            log.info("server restarted by the desktop watchdog")
                    except Exception as e:
                        log.error(f"server restart failed: {e}")
                continue
            if down_since is not None:
                gone = time.time() - down_since
                down_since = None
                log.info(f"server answers again after {gone:.0f}s")
                if gone > 20 and self.visible:
                    self.reload_page("server was restarted")
                    last_reload = time.time()
                continue
            if self.visible and age > 150 and time.time() - last_reload > 300:
                self.reload_page(f"page silent {age:.0f}s while the server is alive")
                last_reload = time.time()

    def hide(self):
        if self.window:
            self.window.hide()
            self.visible = False

    def toggle(self):
        self.hide() if self.visible else self.show()

    def voice_click(self):
        self.show()
        try:
            self.window.evaluate_js("window.renardMic && window.renardMic()")
        except Exception:
            quiet()

    def on_closing(self):
        if self.quitting:
            return True
        self.hide()
        return False

    def show_event_loop(self):
        """Second launch of the shortcut sets this event -> show the existing window instead of a new process."""
        k32 = ctypes.windll.kernel32
        k32.CreateEventW.restype = ctypes.c_void_p
        h = ctypes.c_void_p(k32.CreateEventW(None, False, False, SHOW_EVENT))
        hm = ctypes.c_void_p(k32.CreateEventW(None, False, False, MIC_EVENT))
        arr = (ctypes.c_void_p * 2)(h.value, hm.value)
        while not self.quitting:
            r = k32.WaitForMultipleObjects(2, arr, False, 1000)
            if r == 1:
                self.voice_click()
            elif r == 0:
                self.show()
                try:
                    self.window.native.Invoke(__import__("System").Action(lambda: self.window.native.Activate()))
                except Exception:
                    quiet()

    def set_icon(self):
        """Fox icon on the window / taskbar button (WinForms keeps python's icon otherwise)."""
        try:
            from System import Action
            from System.Drawing import Icon
            form = self.window.native
            ico = str(ASSETS / "renard.ico")
            form.Invoke(Action(lambda: setattr(form, "Icon", Icon(ico))))
        except Exception as e:
            print("window icon:", e)
        try:
            import pythoncom
            from win32com.propsys import propsys, pscon
            hwnd = int(str(self.window.native.Handle))
            st = propsys.SHGetPropertyStoreForWindow(hwnd, propsys.IID_IPropertyStore)
            st.SetValue(pscon.PKEY_AppUserModel_ID, propsys.PROPVARIANTType(APP_ID, pythoncom.VT_LPWSTR))
            st.Commit()
        except Exception as e:
            print("window AUMID:", e)

    def grant_mic(self):
        """WebView2 asks 'allow microphone?' on every start. Auto-allow it for http://127.0.0.1:<port> only."""
        try:
            form = self.window.native
            from Microsoft.Web.WebView2.Core import CoreWebView2PermissionKind, CoreWebView2PermissionState
            from System import Action

            def on_perm(sender, args):
                if args.Uri.startswith(BASE) and args.PermissionKind == CoreWebView2PermissionKind.Microphone:
                    args.State = CoreWebView2PermissionState.Allow

            def attach():
                form.browser.webview.CoreWebView2.PermissionRequested += on_perm

            form.Invoke(Action(attach))
            self._perm_handler = on_perm
        except Exception as e:
            print("mic auto-permission not available:", e)

    def free_vram(self):
        try:
            httpx.post(BASE + "/api/unload", timeout=30)
        except Exception:
            quiet()

    def quit(self):
        self.quitting = True
        if self.tray:
            self.tray.stop()
        if self.window:
            self.window.destroy()

    def run_tray(self):
        menu = pystray.Menu(
            pystray.MenuItem("Показать / скрыть  (Ctrl+Alt+Space)", lambda: self.toggle(), default=True),
            pystray.MenuItem("Голос: начать/закончить  (Ctrl+Alt+V)", lambda: self.voice_click()),
            pystray.MenuItem("Освободить видеопамять", lambda: self.free_vram()),
            pystray.MenuItem("Выход (сервер агента продолжит работать)", lambda: self.quit()),
        )
        self.tray = pystray.Icon("renard", make_icon(), "Renard", menu)
        self.tray.run_detached()
        threading.Thread(target=self.tray_state_loop, daemon=True).start()

    def tray_state_loop(self):
        """Sleeping fox in the tray while VRAM is free, awake fox while a model / STT is loaded."""
        import time
        awake_img, sleep_img, state = make_icon(False), make_icon(True), None
        while not self.quitting:
            try:
                s = httpx.get(BASE + "/api/status", timeout=3).json()
                awake = bool(s.get("loaded")) or bool(s.get("stt_loaded"))
            except Exception:
                awake = False
            if awake != state and self.tray:
                state = awake
                self.tray.icon = awake_img if awake else sleep_img
                self.tray.title = "Renard — " + ("работает" if awake else "спит (VRAM свободна)")
            time.sleep(5)

    def hotkey_loop(self):
        if os.name != "nt":
            return
        import time
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        user32.RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL | MOD_ALT, VK_SPACE)
        user32.RegisterHotKey(None, VOICE_HOTKEY_ID, MOD_CONTROL | MOD_ALT, VK_V)
        cmd_ids, last_sync, sig = {}, 0.0, None
        msg = wintypes.MSG()
        while not self.quitting:
            if time.time() - last_sync > 10:
                last_sync = time.time()
                try:
                    hk = httpx.get(BASE + "/api/commands_hotkeys", timeout=3).json()["hotkeys"]
                except Exception:
                    hk = None
                if hk is not None and repr(hk) != sig:
                    sig = repr(hk)
                    for i in list(cmd_ids):
                        user32.UnregisterHotKey(None, i)
                    cmd_ids = {}
                    for n, h in enumerate(hk):
                        mods, vk = parse_combo(h["combo"])
                        if vk and user32.RegisterHotKey(None, 100 + n, mods | 0x4000, vk):
                            cmd_ids[100 + n] = h
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                if msg.message != WM_HOTKEY:
                    continue
                if msg.wParam == HOTKEY_ID:
                    self.toggle()
                elif msg.wParam == VOICE_HOTKEY_ID:
                    self.show()
                    try:
                        self.window.evaluate_js("window.renardMic && window.renardMic()")
                    except Exception:
                        quiet()
                elif msg.wParam in cmd_ids:
                    h = cmd_ids[msg.wParam]
                    threading.Thread(target=lambda h=h: httpx.post(f"{BASE}/api/commands/{h['command']}/run",
                                                                   params={"node": h["node"]}, timeout=600), daemon=True).start()
            time.sleep(0.05)
        user32.UnregisterHotKey(None, HOTKEY_ID)
        user32.UnregisterHotKey(None, VOICE_HOTKEY_ID)
        for i in cmd_ids:
            user32.UnregisterHotKey(None, i)

    def companion_loop(self):
        """Desktop companion = separate process (agent/companion.py). Started here when prefs.companion.desktop is on;
        it leaves by itself when switched off / settings change / this app quits, and is started again if needed."""
        import subprocess
        import sys
        import time
        from .config import ROOT
        k32 = ctypes.windll.kernel32
        k32.OpenMutexW.restype = ctypes.c_void_p
        last_start = 0.0
        while not self.quitting:
            try:
                c = httpx.get(BASE + "/api/prefs", timeout=3).json().get("companion", {})
                want = bool(c.get("desktop")) and bool(c.get("enabled", True))
            except Exception:
                want = False
            h = k32.OpenMutexW(0x00100000, False, "Local\\RENARD_companion_single")
            running = bool(h)
            if h:
                k32.CloseHandle(ctypes.c_void_p(h))
            if want and not running and time.time() - last_start > 8:
                last_start = time.time()
                env = os.environ.copy()
                if "remote-debugging-port" in env.get("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", ""):
                    env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = "--remote-debugging-port=9334"
                try:
                    subprocess.Popen([sys.executable, "-m", "agent.companion"], cwd=str(ROOT), env=env,
                                     creationflags=0x08000000)
                except Exception as e:
                    print("companion:", e)
            time.sleep(3)

    def run(self):
        import ctypes.wintypes
        from .launcher import server_alive
        ready = server_alive()
        self.window = webview.create_window("Renard", BASE if ready else None, html=None if ready else SPLASH,
                                            width=1280, height=820, min_size=(520, 400),
                                            background_color="#1F1E1D", text_select=True, hidden=not self.visible)
        self.window.events.closing += self.on_closing
        self.window.events.loaded += lambda: (self.grant_mic(), self.set_icon())
        if not ready:
            def boot():
                if ensure_server(180):
                    self.window.load_url(BASE)
                else:
                    self.window.load_html(SPLASH_FAIL)
            threading.Thread(target=boot, daemon=True).start()
        self.run_tray()
        threading.Thread(target=self.hotkey_loop, daemon=True).start()
        threading.Thread(target=self.show_event_loop, daemon=True).start()
        threading.Thread(target=self.companion_loop, daemon=True).start()
        threading.Thread(target=self.ui_watch_loop, daemon=True).start()
        webview.start(private_mode=False)
        if self.tray:
            self.tray.stop()


SPLASH = """<html><body style="margin:0;height:100vh;display:grid;place-items:center;background:#141312;color:#9A968F;
font:15px 'Segoe UI',sans-serif"><div style="text-align:center"><div style="width:64px;height:64px;margin:0 auto 18px;
border-radius:50%;border:3px solid #3A2A26;border-top-color:#D97757;animation:s 1s linear infinite"></div>
<b style="color:#ECEAE6;letter-spacing:3px">Renard</b><br>запускаю сервер и модель…</div>
<style>@keyframes s{to{transform:rotate(360deg)}}</style></body></html>"""
SPLASH_FAIL = """<html><body style="margin:0;height:100vh;display:grid;place-items:center;background:#141312;color:#ECEAE6;
font:15px 'Segoe UI',sans-serif"><div style="text-align:center;max-width:460px"><h3>Сервер Renard не запустился за 3 минуты</h3>
<p style="color:#9A968F">Подробности в журнале data\\logs\\renard.log. Попробуй закрыть Renard в трее и открыть ярлык снова.</p></div></body></html>"""


def main():
    import sys
    if os.name == "nt":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    if not single_instance():
        return
    logs.setup("desktop")
    Desktop(start_hidden="--tray" in sys.argv).run()


if __name__ == "__main__":
    main()
