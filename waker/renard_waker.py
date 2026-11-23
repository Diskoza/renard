"""Renard Waker — switches the PC on from Telegram while the PC itself is off.

Runs on any device at home that stays on: an old Android phone (Termux), a Raspberry Pi, a NAS, a router with
Python. Only the Python standard library is used. It is a separate small Telegram bot (its own token from @BotFather):
while the PC is off, Renard cannot answer, so this one does.

  /on      — send the Wake-on-LAN «magic packet» to the PC
  /status  — is the PC on? (checks TCP ports of the PC on the home network)
  /help

Config: waker.json next to this file (Renard → Настройки → «Включение по сети» creates it):
  {"token": "123:ABC", "allowed": [12345678], "mac": "AA:BB:CC:DD:EE:FF", "ip": "192.168.0.10",
   "broadcast": "192.168.0.255", "check_port": 445}
Run: python3 renard_waker.py      (Termux: pkg install python; then the same)
One-shot test without Telegram: python3 renard_waker.py waker.json --wake
"""
import json
import socket
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CFG_PATH = Path(next((a for a in sys.argv[1:] if not a.startswith("--")), HERE / "waker.json"))


def magic_packet(mac: str) -> bytes:
    hexmac = "".join(c for c in mac if c.isalnum())
    if len(hexmac) != 12:
        raise ValueError(f"bad MAC address: {mac}")
    return b"\xff" * 6 + bytes.fromhex(hexmac) * 16


def wake(mac: str, broadcast: str = "255.255.255.255", ports=(9, 7), wan_host: str = "", wan_port: int = 0) -> None:
    """Home network: broadcast. From anywhere: also to the home router's public address (wan_host:wan_port), which
    forwards the UDP port to the home network. Sent 3 times — UDP may be lost."""
    pkt = magic_packet(mac)
    targets = [(a, p) for a in dict.fromkeys([broadcast, "255.255.255.255"]) for p in ports]
    if wan_host and wan_port:
        targets.insert(0, (wan_host, int(wan_port)))
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for _ in range(3):
            for addr, port in targets:
                try:
                    s.sendto(pkt, (addr, port))
                except OSError as e:
                    if addr == wan_host:
                        print("send to", addr, port, "failed:", e, flush=True)
            time.sleep(0.2)


def at_home(ip: str) -> bool:
    """Is this device on the PC's network (then /status can check the PC directly)?"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect((ip, 9))
            return s.getsockname()[0].rsplit(".", 1)[0] == ip.rsplit(".", 1)[0]
    except OSError:
        return False


def wake_cfg(cfg: dict) -> None:
    host = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--host=")), cfg.get("wan_host", ""))
    port = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--port=")), cfg.get("wan_port", 0))
    wake(cfg["mac"], cfg.get("broadcast", "255.255.255.255"), wan_host=host, wan_port=int(port or 0))


def pc_is_on(ip: str, ports=(445, 135, 3389), timeout: float = 1.5) -> bool:
    """A switched-off PC does not answer at all; a running one answers or refuses (a firewall may also stay silent,
    so «off» can be «on behind a firewall» — Renard confirms by writing to Telegram when it starts)."""
    for p in ports:
        try:
            with socket.create_connection((ip, p), timeout=timeout):
                return True
        except ConnectionRefusedError:
            return True
        except OSError:
            continue
    return False


class Bot:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.base = cfg.get("api_base", "https://api.telegram.org").rstrip("/") + f"/bot{cfg['token']}/"
        self.offset = 0

    def api(self, method: str, http_timeout: float = 45, **params):
        data = urllib.parse.urlencode(params).encode()
        with urllib.request.urlopen(self.base + method, data=data, timeout=http_timeout) as r:
            return json.loads(r.read().decode())

    def say(self, chat: int, text: str):
        try:
            self.api("sendMessage", http_timeout=15, chat_id=chat, text=text)
        except Exception as e:
            print("send failed:", e, flush=True)

    def on(self) -> bool:
        return pc_is_on(self.cfg["ip"], self.cfg.get("check_ports", [445, 135, 3389]))

    def handle(self, msg: dict):
        chat, uid = msg["chat"]["id"], msg.get("from", {}).get("id")
        text = (msg.get("text") or "").strip().lower()
        if uid not in self.cfg.get("allowed", []):
            self.say(chat, "Нет доступа.")
            return
        cmd = text.split("@")[0]
        if cmd in ("/on", "/wake", "включи", "включи пк", "включи компьютер", "разбуди", "разбуди пк", "wake", "włącz"):
            home = at_home(self.cfg["ip"])
            if home and self.on():
                self.say(chat, "ПК уже включён. Пиши основному боту Renard.")
                return
            wake_cfg(self.cfg)
            self.say(chat, "⚡ Отправил сигнал включения. Когда Windows загрузится, Renard сам напишет «ПК включён».")
            if not home:
                return
            for _ in range(int(self.cfg.get("wait_s", 120)) // 10):
                time.sleep(10)
                if self.on():
                    self.say(chat, "✅ ПК появился в сети.")
                    return
            self.say(chat, "ПК пока не отвечает в сети. Если Renard не написал за пару минут — проверь в BIOS "
                           "«Power On By PCI-E» = Enabled и «ErP Ready» = Disabled (после пропадания питания некоторые "
                           "платы не просыпаются, пока ПК не включат кнопкой). Ещё раз: /on")
        elif cmd in ("/status", "статус", "пк включён?", "пк включен?", "status"):
            if not at_home(self.cfg["ip"]):
                self.say(chat, "Я не в домашней сети, поэтому проверить ПК не могу. Включённый ПК отвечает основному боту Renard.")
                return
            self.say(chat, "🟢 ПК включён." if self.on() else "⚫ ПК не отвечает в сети — выключен или спит. Включить: /on")
        else:
            self.say(chat, "Я будильник Renard.\n/on — включить ПК\n/status — включён ли он\n"
                           "Выключить ПК: основному боту Renard «выключи пк».")

    def run(self):
        print("Renard Waker: waiting for /on …", flush=True)
        while True:
            try:
                r = self.api("getUpdates", http_timeout=45, offset=self.offset, timeout=30,
                             allowed_updates='["message"]')
                for u in r.get("result", []):
                    self.offset = u["update_id"] + 1
                    if "message" in u:
                        self.handle(u["message"])
            except KeyboardInterrupt:
                return
            except Exception as e:
                print("poll error:", e, flush=True)
                time.sleep(5)


def main():
    cfg = json.loads(CFG_PATH.read_text(encoding="utf-8"))
    if "--wake" in sys.argv:
        wake_cfg(cfg)
        print("magic packet sent to", cfg["mac"], ("via " + f"{cfg.get('wan_host')}:{cfg.get('wan_port')}") if cfg.get("wan_host") else "")
        return
    if not cfg.get("token"):
        print("No bot token in waker.json: only the --wake button mode is available.")
        return
    Bot(cfg).run()


if __name__ == "__main__":
    main()
