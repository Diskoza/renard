#!/data/data/com.termux/files/usr/bin/bash
LOG=~/waker/button.log
ok=1
for try in 1 2 3; do
  out=$(timeout 25 python ~/waker/renard_waker.py ~/waker/waker.json --wake 2>&1) && { ok=0; break; }
  sleep 3
done
echo "$(date '+%F %T') try=$try ok=$ok $out" >> "$LOG"
tail -n 50 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
if command -v termux-toast >/dev/null 2>&1; then
  if [ $ok -eq 0 ]; then
    termux-vibrate -d 70 >/dev/null 2>&1
    termux-toast -g bottom "⚡ Renard: сигнал отправлен, ПК включается" >/dev/null 2>&1
  else
    termux-toast -g bottom "⚠ Renard: не отправилось — нет интернета?" >/dev/null 2>&1
  fi
fi
