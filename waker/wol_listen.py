"""Self-test for Wake-on-LAN over the internet: listens for magic packets for THIS PC while it is on.

The router forwards a UDP port to the home network; when the phone (on mobile data, outside the home network) sends
the magic packet, it arrives here too — so the whole path (white IP, port forwarding, broadcast) is checked without
switching the PC off. Standard library only; Renard runs it with the system python.exe (allowed by Windows Firewall).

  python wol_listen.py <MAC> <seconds> <out.json> <port> [<port> …]
"""
import json
import select
import socket
import sys
import time


def main():
    mac, seconds, out = sys.argv[1], float(sys.argv[2]), sys.argv[3]
    ports = [int(p) for p in sys.argv[4:]] or [9]
    pattern = b"\xff" * 6 + bytes.fromhex("".join(c for c in mac if c.isalnum())) * 16
    state = {"started": time.time(), "until": time.time() + seconds, "ports": [], "hits": [], "other": 0,
             "done": False, "error": ""}
    socks = []
    for p in ports:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("0.0.0.0", p))
            socks.append(s)
            state["ports"].append(p)
        except OSError as e:
            state["error"] += f"порт {p} занят ({e}); "

    def save():
        with open(out, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)

    save()
    while socks and time.time() < state["until"]:
        r, _, _ = select.select(socks, [], [], 0.5)
        for s in r:
            try:
                data, addr = s.recvfrom(2048)
            except OSError:
                continue
            if pattern in data:
                state["hits"].append({"from": addr[0], "port": s.getsockname()[1], "t": time.time()})
            else:
                state["other"] += 1
            save()
    state["done"] = True
    save()


if __name__ == "__main__":
    main()
