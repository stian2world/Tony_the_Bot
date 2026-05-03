import sqlite3
from datetime import datetime
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Optional, List


@dataclass
class Question:
    id: int
    student_name: str
    student_id: int
    question_text: str
    timestamp: str
    answer_text: Optional[str]
    teacher_name: Optional[str]
    answered_at: Optional[str]


class QAStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS questions (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_name TEXT    NOT NULL,
                    student_id   INTEGER NOT NULL,
                    question_text TEXT   NOT NULL,
                    timestamp    TEXT    NOT NULL,
                    answer_text  TEXT,
                    teacher_name TEXT,
                    answered_at  TEXT
                )
            """)

    def add_question(self, student_name: str, student_id: int, question_text: str) -> int:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO questions (student_name, student_id, question_text, timestamp) VALUES (?, ?, ?, ?)",
                (student_name, student_id, question_text, ts),
            )
            return cur.lastrowid

    def answer_question(self, question_id: int, answer_text: str, teacher_name: str) -> bool:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE questions SET answer_text=?, teacher_name=?, answered_at=? "
                "WHERE id=? AND answer_text IS NULL",
                (answer_text, teacher_name, ts, question_id),
            )
            return cur.rowcount > 0

    def get_pending(self) -> List[Question]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM questions WHERE answer_text IS NULL ORDER BY timestamp ASC"
            ).fetchall()
            return [Question(**dict(r)) for r in rows]

    def get_question(self, question_id: int) -> Optional[Question]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM questions WHERE id=?", (question_id,)
            ).fetchone()
            return Question(**dict(row)) if row else None

    def find_similar(self, question_text: str, threshold: float = 0.55) -> Optional["Question"]:
        """Return the most similar answered question, or None if none exceed the threshold."""
        answered = [q for q in self.get_all(limit=100) if q.answer_text]
        if not answered:
            return None
        q_lower = question_text.lower()
        best_score, best_q = 0.0, None
        for q in answered:
            score = SequenceMatcher(None, q_lower, q.question_text.lower()).ratio()
            if score > best_score:
                best_score, best_q = score, q
        return best_q if best_score >= threshold else None

    def get_all(self, limit: int = 10) -> List[Question]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM questions ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
            return [Question(**dict(r)) for r in rows]
