"""HTTP for 👍/👎 and the lessons list (mount: app.include_router(api_feedback.router))."""
from fastapi import APIRouter
from pydantic import BaseModel

from . import feedback

router = APIRouter()


class Feedback(BaseModel):
    rating: int
    user: str = ""
    answer: str = ""
    reason: str = ""
    session: str = ""
    msg: str = ""
    tools: list[str] = []


@router.post("/api/feedback")
async def post_feedback(f: Feedback):
    return await feedback.record(f.rating, f.user, f.answer, f.reason, f.session, f.msg, f.tools)


@router.post("/api/feedback/undo")
async def undo_feedback(rec: dict):
    return feedback.undo(rec)


@router.post("/api/lessons")
async def save_lesson(lesson: dict):
    return {"ok": True, "lesson": feedback.save_draft(lesson)}


@router.get("/api/lessons")
async def get_lessons():
    return {"lessons": feedback.load_lessons()}


@router.post("/api/lessons/{lesson_id}")
async def edit_lesson(lesson_id: str, fields: dict):
    l = feedback.update_lesson(lesson_id, fields)
    return {"ok": bool(l), "lesson": l}


@router.delete("/api/lessons/{lesson_id}")
async def del_lesson(lesson_id: str):
    return {"ok": feedback.delete_lesson(lesson_id)}
