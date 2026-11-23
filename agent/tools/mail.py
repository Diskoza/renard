"""E-mail: read the user's inbox over IMAP (Gmail, Outlook, WP, Onet, O2, Interia, Yandex, Mail.ru, ukr.net, iCloud …).
Credentials live ONLY in data/accounts/mail.json (an app password, never typed into the chat):
  {"accounts": [{"email": "name@gmail.com", "password": "<app password>", "imap": "imap.gmail.com"}]}
Read-only: nothing is sent or deleted (messages stay unread unless he asks to read one)."""
import email
import imaplib
import json
import os
import re
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime

from . import I, S, tool
from ..logs import quiet

HOSTS = {"gmail.com": "imap.gmail.com", "googlemail.com": "imap.gmail.com", "outlook.com": "outlook.office365.com",
         "hotmail.com": "outlook.office365.com", "live.com": "outlook.office365.com", "wp.pl": "imap.wp.pl",
         "o2.pl": "poczta.o2.pl", "onet.pl": "imap.poczta.onet.pl", "op.pl": "imap.poczta.onet.pl",
         "interia.pl": "poczta.interia.pl", "yandex.ru": "imap.yandex.ru", "ya.ru": "imap.yandex.ru",
         "mail.ru": "imap.mail.ru", "bk.ru": "imap.mail.ru", "ukr.net": "imap.ukr.net", "icloud.com": "imap.mail.me.com",
         "yahoo.com": "imap.mail.yahoo.com", "gazeta.pl": "imap.gazeta.pl"}
WEB = {"gmail.com": "https://mail.google.com", "outlook.com": "https://outlook.live.com/mail", "wp.pl": "https://poczta.wp.pl",
       "o2.pl": "https://poczta.o2.pl", "onet.pl": "https://poczta.onet.pl", "interia.pl": "https://poczta.interia.pl",
       "ukr.net": "https://mail.ukr.net", "yandex.ru": "https://mail.yandex.ru", "mail.ru": "https://e.mail.ru"}


def _cfg_path():
    from ..config import DATA_DIR
    return DATA_DIR / "accounts" / "mail.json"


def _accounts() -> list[dict]:
    p = _cfg_path()
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        ex = p.with_name("mail.example.json")
        if not ex.exists():
            ex.write_text(json.dumps({"accounts": [{"email": "твой_адрес@gmail.com", "password": "пароль приложения (16 букв)",
                                                    "imap": "imap.gmail.com"}]}, ensure_ascii=False, indent=2),
                          encoding="utf-8")
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception:
        return []
    accs = data.get("accounts", data if isinstance(data, list) else [data])
    out = []
    for a in accs:
        if a.get("email") and a.get("password"):
            dom = a["email"].split("@")[-1].lower()
            a.setdefault("imap", HOSTS.get(dom, "imap." + dom))
            out.append(a)
    return out


def _setup_text() -> str:
    p = _cfg_path()
    return ("Почта ещё не подключена — мне нужен доступ к ящику по IMAP (только чтение). Сделай один раз:\n"
            "1) Gmail: включи двухэтапную проверку, затем открой https://myaccount.google.com/apppasswords → создай пароль "
            "приложения «Renard» (16 букв). Для WP/Onet/O2/Interia: в настройках почты включи доступ IMAP.\n"
            f"2) Создай файл {p} по образцу {p.with_name('mail.example.json')} — впиши адрес и этот пароль "
            "(в чат пароль не пиши).\n3) Скажи «проверь почту» ещё раз.\n"
            "Пока могу открыть почту в браузере: mail(action=\"open\").")


def _dec(s) -> str:
    try:
        return str(make_header(decode_header(s or "")))
    except Exception:
        return s or ""


def _body(msg) -> str:
    text, html = "", ""
    for part in (msg.walk() if msg.is_multipart() else [msg]):
        ct = part.get_content_type()
        if part.get_content_disposition() == "attachment":
            continue
        try:
            payload = part.get_payload(decode=True) or b""
            s = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        except Exception:
            continue
        if ct == "text/plain" and not text:
            text = s
        elif ct == "text/html" and not html:
            html = s
    if not text and html:
        text = re.sub(r"(?is)<(script|style).*?</\1>", "", html)
        text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", text)
        text = re.sub(r"<[^>]+>", "", text)
        import html as _h
        text = _h.unescape(text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def _attachments(msg) -> list[str]:
    return [_dec(p.get_filename()) for p in msg.walk() if p.get_content_disposition() == "attachment" and p.get_filename()]


def _connect(a: dict):
    m = imaplib.IMAP4_SSL(a["imap"], int(a.get("port", 993)), timeout=20)
    m.login(a["email"], a["password"].replace(" ", ""))
    return m


def _line(uid, msg, acc_n) -> str:
    try:
        dt = parsedate_to_datetime(msg.get("Date")).astimezone().strftime("%d.%m %H:%M")
    except Exception:
        dt = "?"
    frm = _dec(msg.get("From"))
    frm = re.sub(r"\s*<[^>]+>", "", frm).strip('" ') or frm
    return f"[{acc_n}:{uid.decode() if isinstance(uid, bytes) else uid}] {dt} — {frm[:40]}: {_dec(msg.get('Subject'))[:90]}"


@tool("mail", "Почта пользователя (только чтение, IMAP): action = check (новые/непрочитанные письма), list (последние), "
              "search (query — текст/отправитель), read (id из списка, вида '1:1234' — полный текст письма), "
              "open (открыть почту в браузере). Если не подключена — инструмент сам вернёт инструкцию, перескажи её.",
      {"action": S, "query": S, "id": S, "limit": I}, [])
def mail(action: str = "check", query: str = "", id: str = "", limit: int = 10) -> str:
    action = (action or "check").lower()
    accs = _accounts()
    if action == "open":
        dom = (accs[0]["email"].split("@")[-1].lower() if accs else "gmail.com")
        url = WEB.get(dom, "https://mail.google.com")
        os.startfile(url)
        return f"Открыл почту в браузере: {url}"
    if not accs:
        return _setup_text()
    limit = max(1, min(int(limit or 10), 30))
    out, errors = [], []
    for n, a in enumerate(accs, 1):
        if action == "read" and id and not id.startswith(f"{n}:") and ":" in id:
            continue
        try:
            m = _connect(a)
        except imaplib.IMAP4.error as e:
            errors.append(f"{a['email']}: вход не удался ({str(e)[:120]}). Нужен ПАРОЛЬ ПРИЛОЖЕНИЯ (не обычный) и включённый IMAP.")
            continue
        except Exception as e:
            errors.append(f"{a['email']}: нет связи с {a['imap']} ({type(e).__name__}: {str(e)[:100]})")
            continue
        try:
            m.select("INBOX", readonly=(action != "read"))
            if action == "read":
                uid = id.split(":")[-1].strip()
                typ, data = m.uid("fetch", uid, "(RFC822)")
                if not data or not data[0]:
                    errors.append(f"Письма {id} нет.")
                    continue
                msg = email.message_from_bytes(data[0][1])
                att = _attachments(msg)
                body = _body(msg)
                out.append(f"От: {_dec(msg.get('From'))}\nТема: {_dec(msg.get('Subject'))}\nДата: {msg.get('Date')}\n"
                           + (f"Вложения: {', '.join(att)}\n" if att else "") + "\n" + body[:6000]
                           + ("\n…(обрезано)" if len(body) > 6000 else ""))
                continue
            if action == "check":
                typ, data = m.uid("search", None, "UNSEEN")
            elif action == "search" and query:
                q = query.replace('"', "")
                try:
                    typ, data = m.uid("search", "CHARSET", "UTF-8", "TEXT", f'"{q}"'.encode("utf-8"))
                except Exception:
                    typ, data = m.uid("search", None, "OR", "FROM", f'"{q}"', "SUBJECT", f'"{q}"')
            else:
                typ, data = m.uid("search", None, "ALL")
            uids = (data[0] or b"").split()
            total = len(uids)
            uids = uids[-limit:][::-1]
            lines = []
            if uids:
                typ, rows = m.uid("fetch", b",".join(uids), "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
                for r in rows:
                    if isinstance(r, tuple):
                        um = re.search(rb"UID (\d+)", r[0])
                        lines.append(_line(um.group(1) if um else b"?", email.message_from_bytes(r[1]), n))
            head = {"check": f"{a['email']}: непрочитанных {total}", "search": f"{a['email']}: найдено {total} по «{query}»",
                    }.get(action, f"{a['email']}: последние письма")
            out.append(head + (":\n" + "\n".join(lines) if lines else "."))
        finally:
            try:
                m.logout()
            except Exception:
                quiet()
    res = "\n\n".join(out + errors) or "Ничего не нашёл."
    if action in ("check", "list", "search") and out:
        res += "\n(Открыть письмо целиком: mail(action=\"read\", id=\"N:UID\").)"
    return res
