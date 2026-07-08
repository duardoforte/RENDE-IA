"""
Controle de limite de tentativas REAIS ao Gemini POR USUÁRIO/SESSÃO.

Persistência em SQLite próprio (gemini_usage.db) — NÃO toca o banco financeiro
(tesouro_direto.db). O limite é por session_id, com janela deslizante: ao expirar a
janela, as tentativas resetam. Não armazena API key, prompt nem dados sensíveis.

Tabela:
    gemini_usage_limits(session_id PK, window_start, attempts_count, last_attempt_at)
"""
import os
import sqlite3
import time

# Caminho do banco de uso (sobrescrevível em testes via usage_limits.DB_PATH = ...).
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gemini_usage.db")


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=5)
    con.isolation_level = None  # autocommit; controlamos transações manualmente
    con.execute(
        """CREATE TABLE IF NOT EXISTS gemini_usage_limits (
               session_id      TEXT PRIMARY KEY,
               window_start    INTEGER NOT NULL,
               attempts_count  INTEGER NOT NULL,
               last_attempt_at INTEGER
           )"""
    )
    return con


def status(session_id: str, window: int) -> dict:
    """Estado atual SEM consumir tentativa (considera reset de janela)."""
    now = int(time.time())
    con = _conn()
    try:
        row = con.execute(
            "SELECT window_start, attempts_count FROM gemini_usage_limits WHERE session_id=?",
            (session_id,),
        ).fetchone()
    finally:
        con.close()
    if row is None or now - row[0] >= window:
        return {"attempts": 0, "window_start": now, "expirada": True}
    return {"attempts": row[1], "window_start": row[0], "expirada": False}


def consumir(session_id: str, max_attempts: int, window: int) -> dict:
    """Check-and-consume atômico de UMA tentativa real.

    Retorna {permitido, tentativa, max, restante}:
      • permitido=True  → registrou a tentativa (incrementou);
      • permitido=False → já atingiu o máximo na janela (NÃO incrementa).
    Ao expirar a janela, reseta antes de consumir.
    """
    now = int(time.time())
    con = _conn()
    try:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute(
            "SELECT window_start, attempts_count FROM gemini_usage_limits WHERE session_id=?",
            (session_id,),
        ).fetchone()

        if row is None or now - row[0] >= window:
            window_start, attempts = now, 0
        else:
            window_start, attempts = row[0], row[1]

        if attempts >= max_attempts:
            con.execute("COMMIT")
            return {"permitido": False, "tentativa": attempts, "max": max_attempts, "restante": 0}

        attempts += 1
        con.execute(
            """INSERT INTO gemini_usage_limits(session_id, window_start, attempts_count, last_attempt_at)
               VALUES(?,?,?,?)
               ON CONFLICT(session_id) DO UPDATE SET
                   window_start=excluded.window_start,
                   attempts_count=excluded.attempts_count,
                   last_attempt_at=excluded.last_attempt_at""",
            (session_id, window_start, attempts, now),
        )
        con.execute("COMMIT")
        return {"permitido": True, "tentativa": attempts, "max": max_attempts,
                "restante": max_attempts - attempts}
    finally:
        con.close()


def resetar(session_id: str) -> None:
    """Remove o registro de um usuário (uso administrativo / testes)."""
    con = _conn()
    try:
        con.execute("DELETE FROM gemini_usage_limits WHERE session_id=?", (session_id,))
    finally:
        con.close()
