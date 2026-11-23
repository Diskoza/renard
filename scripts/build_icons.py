"""Render web/assets/*.svg -> PNG (512, Telegram avatar 640) and renard.ico (16..256). Uses installed Chrome via Playwright.
Usage: .venv\\Scripts\\python scripts\\build_icons.py"""
import asyncio
import base64
from pathlib import Path

from PIL import Image
from playwright.async_api import async_playwright

A = Path(__file__).resolve().parent.parent / "web" / "assets"


async def render(page, svg: Path, out: Path, size: int):
    b64 = base64.b64encode(svg.read_bytes()).decode()
    await page.set_viewport_size({"width": size, "height": size})
    await page.set_content(f"<html><body style='margin:0;background:transparent'>"
                           f"<img src='data:image/svg+xml;base64,{b64}' "
                           f"style='width:{size}px;height:{size}px;display:block;object-fit:contain'></body></html>")
    await page.wait_for_timeout(300)
    await page.screenshot(path=str(out), omit_background=True)


async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(channel="chrome", headless=True)
        p = await b.new_page()
        await render(p, A / "renard_icon.svg", A / "renard_icon_512.png", 512)
        await render(p, A / "renard_tg.svg", A / "telegram_avatar_640.png", 640)
        await render(p, A / "renard_corner.svg", A / "renard_corner_256.png", 256)
        await render(p, A / "renard_sleep.svg", A / "renard_sleep_256.png", 256)
        await b.close()
    Image.open(A / "renard_icon_512.png").convert("RGBA").save(
        A / "renard.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    Image.open(A / "renard_sleep_256.png").convert("RGBA").save(A / "renard_sleep.ico", sizes=[(16, 16), (32, 32), (64, 64)])
    for f in sorted(A.iterdir()):
        print(f.name, f.stat().st_size)


asyncio.run(main())
