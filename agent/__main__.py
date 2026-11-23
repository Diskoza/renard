"""Server entry point: python -m agent   (preferred over `-m agent.main`).

Why: Windows multiprocessing (spawn) re-imports the parent's main module in every child. For `-m agent.main`
that meant the STT / wake-word workers imported FastAPI, aiogram, all tools... (~250 MB each).
A package `__main__` is skipped by spawn, so the workers stay small.
"""
from .main import main

main()
