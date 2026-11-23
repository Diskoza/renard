"""Eyes outside the screen (like Project Astra): «посмотри в камеру — что у меня в руке», «как я выгляжу», «прочитай,
что написано на коробке». One photo from the webcam, only when he asks; the camera is released right after the shot
(the light goes out). The frame stays local (workspace/camera) and is looked at by the local vision model.
"""
import asyncio
import time
from pathlib import Path

from . import S, tool
from ..config import SETTINGS


def _grab(index: int = 0, warm: int = 8):
    import cv2
    cap = None
    for api in (cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY):
        cap = cv2.VideoCapture(index, api)
        if cap.isOpened():
            break
        cap.release()
    try:
        if not cap.isOpened():
            return None, ("веб-камеры на этом ПК не видно (или её держит Discord / OBS / браузер). Можно сфоткать на "
                          "телефон и прислать фото боту Renard в Telegram — посмотрю его")
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280); cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        frame = None
        for _ in range(warm):
            ok, f = cap.read()
            if ok:
                frame = f
            time.sleep(0.05)
        if frame is None:
            return None, "камера не отдала кадр"
        if float(frame.mean()) < 6:
            return None, "кадр совсем чёрный — камера закрыта шторкой или выключена"
        return frame, ""
    finally:
        cap.release()


@tool("look_at_camera", "Посмотреть через веб-камеру (одно фото, только по просьбе): что у пользователя в руке, как он "
      "выглядит, прочитать надпись на предмете, который он показывает. question — что именно понять",
      {"question": S}, [])
async def look_at_camera(question: str = "", ctx: dict | None = None) -> str:
    from PIL import Image
    from .extra import _ask_vision, _img_b64
    frame, err = await asyncio.to_thread(_grab, int(SETTINGS.get("camera_index", 0) or 0))
    if frame is None:
        return f"Не получилось посмотреть в камеру: {err}."
    img = Image.fromarray(frame[:, :, ::-1])
    out = Path(SETTINGS.get("workspace", "workspace")) / "camera"
    out.mkdir(parents=True, exist_ok=True)
    f = out / time.strftime("camera_%Y%m%d_%H%M%S.jpg")
    img.save(f, quality=88)
    q = (question or "Что видно? Если человек что-то показывает в руке — что это.") + \
        " (Это кадр с веб-камеры пользователя: он смотрит в камеру и, возможно, что-то показывает.)"
    ans = await _ask_vision(ctx or {}, _img_b64(img, 1280), q)
    return f"{ans}\n(кадр с камеры: {f})"
