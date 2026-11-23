---
name: minecraft-mod-analysis
description: Разобрать мод Minecraft (.jar) или папку mods — загрузчик, версия игры, зависимости, миксины, возможные конфликты.
version: 1.0.0
author: Renard
license: MIT
platforms: [windows]
---

# Анализ модов Minecraft

Используй, когда просят «разбери мод», «почему крашится сборка», «какие моды конфликтуют», «на какую версию этот мод».

## Шаги

1. Найди файлы: `search_files(folder=<папка>, name="*.jar")`. Если дан один .jar — работай с ним.
2. Для каждого .jar извлеки метаданные через `run_python` (jar — это zip):

```python
import zipfile, json, sys
p = r"<путь к .jar>"
z = zipfile.ZipFile(p)
names = z.namelist()
for meta in ("fabric.mod.json", "quilt.mod.json", "META-INF/mods.toml", "META-INF/neoforge.mods.toml", "mcmod.info"):
    if meta in names:
        print("==", meta); print(z.read(meta).decode("utf-8", "replace")[:3000])
print("mixins:", [n for n in names if n.endswith(".mixins.json")][:10])
print("classes:", sum(n.endswith(".class") for n in names), "files:", len(names))
```

3. Из метаданных выпиши: **загрузчик** (Fabric / Quilt / Forge / NeoForge), **id и версию мода**, **версию Minecraft**,
   **зависимости** (`depends` / `[[dependencies]]`), **миксины** (какие классы игры меняет).
4. Для папки mods: сведи в таблицу; ищи конфликты:
   - разные загрузчики в одной папке (Fabric + Forge) — гарантированный краш;
   - разные версии Minecraft;
   - отсутствующая зависимость (мод требует `fabric-api`, а его нет);
   - два мода с одинаковым id или две версии одного мода;
   - несколько модов с миксинами в одни и те же классы игры (кандидаты на конфликт).
5. Если есть `crash-report`/`latest.log` — прочитай последние 200 строк, найди `Caused by:` и имя мода в стеке.

## Формат ответа

Короткая таблица модов (имя · версия · загрузчик · MC · зависимости), затем «Проблемы» по пунктам с конкретным
действием (удалить / обновить / добавить зависимость X).
