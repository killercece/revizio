"""
Migration de l'historique vers des donnees par utilisateur.

Avant l'arrivee des comptes, toutes les sessions (verbes, histoire-geo) etaient
communes. Elles sont rattachees ici a un proprietaire (auth.LEGACY_OWNER). Les
erreurs de verbes et les reponses d'histoire-geo suivent par leur session.
Idempotent : sans effet une fois la colonne posee et remplie.
"""

import logging
import sqlite3

logger = logging.getLogger(__name__)


def attach_history(db_path, owner):
    """Ajoute sessions.user_email et rattache les sessions existantes a `owner`.

    BEGIN IMMEDIATE serialise les workers gunicorn qui importent l'app en
    parallele : un seul migre, les autres trouvent la colonne deja posee.
    """
    conn = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        cols = [r[1] for r in conn.execute("PRAGMA table_info(sessions)")]
        if not cols:  # base sans table sessions : rien a migrer
            conn.execute("COMMIT")
            return 0
        if 'user_email' not in cols:
            conn.execute("ALTER TABLE sessions ADD COLUMN user_email TEXT")
        moved = conn.execute("UPDATE sessions SET user_email = ? WHERE user_email IS NULL",
                             (owner,)).rowcount
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user "
                     "ON sessions(user_email, tool_type)")
        conn.execute("COMMIT")
        if moved:
            logger.info(f"Migration : {moved} session(s) rattachee(s) a {owner}")
        return moved
    except sqlite3.Error:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
