"""Chess with Renard (Astra plugin «Шахматы»): python-chess rules + Stockfish (data/engines) with a skill level, or a
small built-in engine if Stockfish is missing. Renard comments the game (blunders, checks, the result)."""
import asyncio
import json
import random
import time

import chess
import chess.engine

from .config import DATA_DIR
from .logs import quiet

SAVE = DATA_DIR / "chess.json"
LEVELS = {1: ("новичок", 0, 0.05), 2: ("любитель", 3, 0.1), 3: ("клубный", 8, 0.25), 4: ("сильный", 14, 0.5), 5: ("максимум", 20, 1.0)}
PIECE_RU = {chess.PAWN: "пешку", chess.KNIGHT: "коня", chess.BISHOP: "слона", chess.ROOK: "ладью", chess.QUEEN: "ферзя"}
VAL = {chess.PAWN: 100, chess.KNIGHT: 300, chess.BISHOP: 320, chess.ROOK: 500, chess.QUEEN: 900, chess.KING: 0}


def stockfish() -> str | None:
    found = sorted((DATA_DIR / "engines").rglob("stockfish*.exe"))
    return str(found[0]) if found else None


class Game:
    def __init__(self):
        self.board, self.user_white, self.level, self.comment, self.last_eval = chess.Board(), True, 2, "", 0
        self.engine: chess.engine.SimpleEngine | None = None
        self.lock = asyncio.Lock()
        self._load()

    def _load(self):
        try:
            d = json.loads(SAVE.read_text(encoding="utf-8"))
            self.board = chess.Board()
            for u in d.get("moves", []):
                self.board.push_uci(u)
            self.user_white, self.level = d.get("user_white", True), d.get("level", 2)
        except Exception:
            quiet()

    def _save(self):
        SAVE.write_text(json.dumps({"moves": [m.uci() for m in self.board.move_stack], "user_white": self.user_white,
                                    "level": self.level, "ts": time.time()}), encoding="utf-8")

    def _eng(self):
        if self.engine is None and stockfish():
            self.engine = chess.engine.SimpleEngine.popen_uci(stockfish(), creationflags=0x08000000)
            self.engine.configure({"Threads": 2, "Hash": 64})
        return self.engine

    def _eval(self) -> int:
        """Score in centipawns from the user's side (+ = he is better)."""
        e = self._eng()
        if e:
            info = e.analyse(self.board, chess.engine.Limit(time=0.12))
            s = info["score"].pov(chess.WHITE if self.user_white else chess.BLACK).score(mate_score=10000)
            return int(s or 0)
        mat = sum(VAL[p.piece_type] * (1 if p.color == chess.WHITE else -1) for p in self.board.piece_map().values())
        return mat if self.user_white else -mat

    def _engine_move(self) -> chess.Move:
        name, skill, t = LEVELS.get(self.level, LEVELS[2])
        e = self._eng()
        if e:
            e.configure({"Skill Level": skill})
            return e.play(self.board, chess.engine.Limit(time=t)).move
        return self._mini_move(depth=1 if self.level <= 2 else 2)

    def _mini_move(self, depth: int) -> chess.Move:
        """Without Stockfish: material minimax with a bit of randomness (a weak but legal opponent)."""
        me = self.board.turn

        def score(b):
            if b.is_checkmate():
                return -99999 if b.turn == me else 99999
            return sum(VAL[p.piece_type] * (1 if p.color == me else -1) for p in b.piece_map().values())

        def mm(b, d, maxi):
            if d == 0 or b.is_game_over():
                return score(b)
            vals = []
            for mv in b.legal_moves:
                b.push(mv); vals.append(mm(b, d - 1, not maxi)); b.pop()
            return max(vals) if maxi else min(vals)
        best, bv = [], -10 ** 9
        for mv in self.board.legal_moves:
            self.board.push(mv)
            v = mm(self.board, depth, False) + random.randint(0, 30)
            self.board.pop()
            if v > bv:
                best, bv = [mv], v
            elif v == bv:
                best.append(mv)
        return random.choice(best)

    def state(self) -> dict:
        b = self.board
        res = b.result(claim_draw=True) if b.is_game_over(claim_draw=True) else ""
        return {"fen": b.fen(), "user_white": self.user_white, "level": self.level, "level_name": LEVELS[self.level][0],
                "turn_user": (b.turn == chess.WHITE) == self.user_white and not res, "result": res,
                "moves": [m.uci() for m in b.move_stack], "san": self._san_list(), "check": b.is_check(),
                "comment": self.comment, "engine": "Stockfish" if stockfish() else "встроенный",
                "legal": [m.uci() for m in b.legal_moves], "last": b.move_stack[-1].uci() if b.move_stack else ""}

    def _san_list(self) -> list[str]:
        tmp, out = chess.Board(), []
        for m in self.board.move_stack:
            out.append(tmp.san(m)); tmp.push(m)
        return out

    def _over_text(self) -> str:
        b = self.board
        if b.is_checkmate():
            won = (b.turn == chess.WHITE) != self.user_white
            return "Мат! Ты победил, поздравляю 🎉" if won else "Мат. В этот раз я выиграл — реванш?"
        if b.is_stalemate():
            return "Пат — ничья."
        return "Ничья."

    def new(self, white: bool = True, level: int = 2) -> dict:
        self.board, self.user_white, self.level, self.comment = chess.Board(), white, max(1, min(5, level)), ""
        self.comment = f"Играем! Ты {'белыми — твой ход' if white else 'чёрными, я хожу первым'}. Уровень: {LEVELS[self.level][0]}."
        if not white:
            self.board.push(self._engine_move())
        self.last_eval = 0
        self._save()
        return self.state()

    def move(self, uci: str) -> dict:
        b = self.board
        if b.is_game_over() or (b.turn == chess.WHITE) != self.user_white:
            return {**self.state(), "error": "сейчас не твой ход"}
        try:
            mv = chess.Move.from_uci(uci)
            if mv not in b.legal_moves and len(uci) == 4:
                mv = chess.Move.from_uci(uci + "q")
        except ValueError:
            return {**self.state(), "error": "не понял ход"}
        if mv not in b.legal_moves:
            return {**self.state(), "error": "так ходить нельзя"}
        before = self.last_eval
        cap = b.piece_at(mv.to_square)
        b.push(mv)
        lines = []
        if b.is_game_over():
            self.comment = self._over_text(); self._save()
            return {**self.state(), "mood": "happy" if "победил" in self.comment else "relaxed"}
        after = self._eval()
        mood = ""
        if after - before < -250:
            lines.append(random.choice(["Хм, а это точно лучший ход?", "Ой. Кажется, ты что-то упустил…", "Смелое решение. Посмотрим!"]))
            mood = "surprised"
        elif after - before > 150 and len(b.move_stack) > 6:
            lines.append(random.choice(["Сильный ход!", "Ого, хорошо придумано.", "Неплохо, неплохо…"]))
            mood = "happy"
        reply = self._engine_move()
        took = b.piece_at(reply.to_square)
        san = b.san(reply)
        b.push(reply)
        if took and took.piece_type in PIECE_RU and took.piece_type != chess.PAWN:
            lines.append(f"Забираю {PIECE_RU[took.piece_type]}.")
        if b.is_check():
            lines.append("Шах!")
        if b.is_game_over():
            lines.append(self._over_text()); mood = "happy" if "выиграл" in lines[-1] else "relaxed"
        self.last_eval = self._eval() if not b.is_game_over() else after
        if cap and not lines and cap.piece_type in (chess.QUEEN, chess.ROOK):
            lines.append(f"Эх, мой {'ферзь' if cap.piece_type == chess.QUEEN else 'ладья'}…"); mood = mood or "sad"
        self.comment = f"Мой ход: {san}. " + " ".join(lines)
        self._save()
        return {**self.state(), "reply": reply.uci(), "mood": mood}

    def undo(self) -> dict:
        if len(self.board.move_stack) >= 2:
            self.board.pop(); self.board.pop()
            self.comment = "Ладно, переходи 🙂"
            self._save()
        return self.state()

    def hint(self) -> dict:
        e = self._eng()
        if not e or self.board.is_game_over():
            return {**self.state(), "hint": ""}
        mv = e.play(self.board, chess.engine.Limit(time=0.3)).move
        return {**self.state(), "hint": mv.uci(), "comment": f"Подсказка: попробуй {self.board.san(mv)}."}

    def close(self):
        if self.engine:
            try:
                self.engine.quit()
            except Exception:
                quiet()
            self.engine = None


import re
CHESS_RX = re.compile(r"(?i)(сыгра\w*|поигра\w*|игра\w*|партию|давай)\s+(со\s+мной\s+|с\s+тобой\s+)?(в\s+)?шахмат|^шахматы\W*$|"
                      r"(открой|включи|запусти)\s+шахмат")


async def route(text: str, agent) -> dict | None:
    if not CHESS_RX.search(text):
        return None
    from .tools.browser_ctl import show_renard
    shown = show_renard()
    try:
        await agent.command_runner.broadcast({"type": "open_page", "page": "chess"})
    except Exception:
        quiet()
    g = game()
    st = g.state()
    going = bool(st["moves"]) and not st["result"]
    return {"tool": "chess", "text": ("Открыл доску — продолжаем нашу партию!" if going else
                                      "Открыл шахматы! Выбери цвет и уровень и жми «Играть».")
            + ("" if shown else " (окно Renard: вкладка «Шахматы» — #/chess)"),
            "speech": "Продолжаем партию!" if going else "Давай сыграем! Выбери цвет и уровень."}


GAME: Game | None = None


def game() -> Game:
    global GAME
    if GAME is None:
        GAME = Game()
    return GAME
