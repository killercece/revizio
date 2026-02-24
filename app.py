"""
Application Flask - Revizio
Portail de revision multi-outils pour le college.
"""

__version__ = '1.0.0'

from flask import Flask, render_template, jsonify, request, g
import sqlite3
import json
import logging
import os
from pathlib import Path
from datetime import datetime

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialiser Flask
app = Flask(__name__)
app.secret_key = 'revizio-portal-secret-key'

# Configuration base de donnees
DB_PATH = Path('data/app.db')

# Registre des outils disponibles
TOOLS = [
    {
        'id': 'irregular-verbs',
        'name': 'Verbes Irréguliers',
        'description': 'Révise les 53 verbes irréguliers anglais',
        'icon': 'book',
        'url': '/verbes-irreguliers/',
        'suivi_url': '/verbes-irreguliers/suivi',
        'color': '#667eea',
    },
]


# === BASE DE DONNEES ===

def ensure_db():
    """Cree la base de donnees si elle n'existe pas, ou migre si necessaire."""
    from setup import init_database
    if not DB_PATH.exists():
        logger.info("Base de donnees absente, initialisation automatique...")
        init_database()
    else:
        conn = sqlite3.connect(DB_PATH)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]

        if 'sessions' not in tables:
            conn.close()
            logger.info("Migration : ajout des tables sessions...")
            init_database()
        else:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(sessions)").fetchall()]
            if 'pause_state' not in cols:
                logger.info("Migration : ajout colonne pause_state...")
                conn.execute("ALTER TABLE sessions ADD COLUMN pause_state TEXT")
                conn.commit()
            if 'tool_type' not in cols:
                logger.info("Migration : ajout colonne tool_type...")
                conn.execute("ALTER TABLE sessions ADD COLUMN tool_type TEXT NOT NULL DEFAULT 'irregular-verbs'")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_tool_type ON sessions(tool_type)")
                conn.commit()
            conn.close()


# Auto-init au demarrage
ensure_db()


def get_db():
    """Connexion a la base de donnees avec reutilisation par requete."""
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception):
    """Ferme la connexion a la fin de la requete."""
    db = g.pop('db', None)
    if db is not None:
        db.close()


def get_tool_stats(db, tool_id):
    """Recupere les stats d'un outil (sessions terminees, precision moyenne)."""
    row = db.execute("""
        SELECT COUNT(*) as total_sessions,
               COALESCE(AVG(
                   CASE WHEN total_correct + total_errors > 0
                   THEN ROUND(total_correct * 100.0 / (total_correct + total_errors))
                   ELSE 100 END
               ), 0) as avg_accuracy
        FROM sessions
        WHERE tool_type = ? AND completed_at IS NOT NULL
    """, (tool_id,)).fetchone()
    return {
        'total_sessions': row['total_sessions'],
        'avg_accuracy': round(row['avg_accuracy']),
    }


# === ROUTES PORTAIL ===

@app.route('/')
def index():
    """Page d'accueil du portail — liste des outils disponibles."""
    db = get_db()
    tools_with_stats = []
    for tool in TOOLS:
        t = dict(tool)
        t['stats'] = get_tool_stats(db, tool['id'])
        tools_with_stats.append(t)
    return render_template('index.html', tools=tools_with_stats)


@app.route('/suivi')
def suivi():
    """Suivi global agrege pour tous les outils."""
    db = get_db()

    # Stats par outil
    tool_stats = []
    for tool in TOOLS:
        stats = get_tool_stats(db, tool['id'])
        tool_stats.append({**tool, 'stats': stats})

    # Stats globales
    row = db.execute("""
        SELECT COUNT(*) as total_sessions,
               COALESCE(AVG(
                   CASE WHEN total_correct + total_errors > 0
                   THEN ROUND(total_correct * 100.0 / (total_correct + total_errors))
                   ELSE 100 END
               ), 0) as avg_accuracy,
               COALESCE(AVG(rounds), 0) as avg_rounds
        FROM sessions WHERE completed_at IS NOT NULL
    """).fetchone()

    return render_template('suivi.html',
                           tool_stats=tool_stats,
                           total_sessions=row['total_sessions'],
                           avg_accuracy=round(row['avg_accuracy']),
                           avg_rounds=round(row['avg_rounds'], 1))


@app.route('/api/health')
def health():
    """Health check endpoint pour PyDeploy."""
    return jsonify({"status": "ok", "version": __version__}), 200


# === ROUTES VERBES IRREGULIERS ===

@app.route('/verbes-irreguliers/')
def verbs_quiz():
    """Page du quiz des verbes irreguliers."""
    return render_template('verbs.html')


@app.route('/verbes-irreguliers/suivi')
def verbs_suivi():
    """Page de suivi pour les verbes irreguliers."""
    try:
        db = get_db()

        sessions = db.execute("""
            SELECT id, started_at, completed_at, mode, total_verbs,
                   total_correct, total_errors, rounds
            FROM sessions
            WHERE completed_at IS NOT NULL AND tool_type = 'irregular-verbs'
            ORDER BY started_at DESC
        """).fetchall()
        sessions = [dict(s) for s in sessions]

        for session in sessions:
            errors = db.execute("""
                SELECT v.infinitive, v.french, se.error_count
                FROM session_errors se
                JOIN verbs v ON v.id = se.verb_id
                WHERE se.session_id = ?
                ORDER BY se.error_count DESC
            """, (session['id'],)).fetchall()
            session['error_verbs'] = [dict(e) for e in errors]
            total = session['total_correct'] + session['total_errors']
            session['accuracy'] = round(session['total_correct'] / total * 100) if total > 0 else 0

        hard_verbs = db.execute("""
            SELECT v.infinitive, v.french, v.past_simple, v.past_participle,
                   SUM(se.error_count) as total_errors,
                   COUNT(DISTINCT se.session_id) as sessions_with_error
            FROM session_errors se
            JOIN verbs v ON v.id = se.verb_id
            JOIN sessions s ON s.id = se.session_id
            WHERE s.tool_type = 'irregular-verbs'
            GROUP BY se.verb_id
            ORDER BY total_errors DESC
            LIMIT 10
        """).fetchall()
        hard_verbs = [dict(v) for v in hard_verbs]

        total_sessions = len(sessions)
        avg_accuracy = round(sum(s['accuracy'] for s in sessions) / total_sessions) if total_sessions > 0 else 0
        avg_rounds = round(sum(s['rounds'] for s in sessions) / total_sessions, 1) if total_sessions > 0 else 0

        return render_template('verbs_suivi.html',
                               sessions=sessions,
                               hard_verbs=hard_verbs,
                               total_sessions=total_sessions,
                               avg_accuracy=avg_accuracy,
                               avg_rounds=avg_rounds)
    except sqlite3.Error as e:
        logger.error(f"Erreur base de donnees: {e}")
        return render_template('verbs_suivi.html',
                               sessions=[], hard_verbs=[],
                               total_sessions=0, avg_accuracy=0, avg_rounds=0)


# === API VERBES IRREGULIERS ===

@app.route('/api/verbs')
def get_verbs():
    """Recupere la liste de tous les verbes irreguliers."""
    try:
        db = get_db()
        verbs = db.execute(
            "SELECT id, infinitive, past_simple, past_participle, french "
            "FROM verbs ORDER BY infinitive"
        ).fetchall()
        return jsonify([dict(v) for v in verbs]), 200
    except sqlite3.Error as e:
        logger.error(f"Erreur base de donnees: {e}")
        return jsonify({"error": "Erreur base de donnees"}), 500


@app.route('/api/verbs/sessions', methods=['POST'])
def create_verb_session():
    """Cree une nouvelle session de quiz pour les verbes irreguliers."""
    try:
        data = request.get_json() or {}
        mode = data.get('mode', 'random')
        total_verbs = data.get('total_verbs', 0)

        db = get_db()
        cursor = db.execute(
            "INSERT INTO sessions (tool_type, mode, total_verbs) VALUES (?, ?, ?)",
            ('irregular-verbs', mode, total_verbs)
        )
        db.commit()
        return jsonify({"id": cursor.lastrowid}), 201
    except sqlite3.Error as e:
        logger.error(f"Erreur creation session: {e}")
        return jsonify({"error": "Erreur base de donnees"}), 500


@app.route('/api/verbs/sessions/<int:session_id>', methods=['PUT'])
def complete_verb_session(session_id):
    """Termine une session de verbes avec les resultats."""
    try:
        data = request.get_json()
        db = get_db()

        db.execute("""
            UPDATE sessions
            SET completed_at = ?, total_correct = ?, total_errors = ?, rounds = ?,
                pause_state = NULL
            WHERE id = ? AND tool_type = 'irregular-verbs'
        """, (
            datetime.now().isoformat(),
            data.get('total_correct', 0),
            data.get('total_errors', 0),
            data.get('rounds', 0),
            session_id
        ))

        errors = data.get('errors', [])
        for err in errors:
            db.execute(
                "INSERT INTO session_errors (session_id, verb_id, error_count) VALUES (?, ?, ?)",
                (session_id, err['verb_id'], err['count'])
            )

        db.commit()
        return jsonify({"status": "ok"}), 200
    except sqlite3.Error as e:
        logger.error(f"Erreur completion session: {e}")
        return jsonify({"error": "Erreur base de donnees"}), 500


@app.route('/api/verbs/sessions/<int:session_id>/pause', methods=['PUT'])
def pause_verb_session(session_id):
    """Sauvegarde l'etat d'une session de verbes en pause."""
    try:
        data = request.get_json()
        db = get_db()

        db.execute("""
            UPDATE sessions SET pause_state = ?, total_correct = ?, total_errors = ?, rounds = ?
            WHERE id = ? AND completed_at IS NULL AND tool_type = 'irregular-verbs'
        """, (
            json.dumps(data.get('state', {})),
            data.get('total_correct', 0),
            data.get('total_errors', 0),
            data.get('rounds', 0),
            session_id
        ))
        db.commit()
        return jsonify({"status": "ok"}), 200
    except sqlite3.Error as e:
        logger.error(f"Erreur pause session: {e}")
        return jsonify({"error": "Erreur base de donnees"}), 500


@app.route('/api/verbs/sessions/pending')
def get_pending_verb_session():
    """Recupere la derniere session de verbes en pause."""
    try:
        db = get_db()
        session = db.execute("""
            SELECT id, started_at, mode, total_verbs, total_correct,
                   total_errors, rounds, pause_state
            FROM sessions
            WHERE completed_at IS NULL AND pause_state IS NOT NULL
                  AND tool_type = 'irregular-verbs'
            ORDER BY started_at DESC LIMIT 1
        """).fetchone()

        if session:
            s = dict(session)
            s['pause_state'] = json.loads(s['pause_state']) if s['pause_state'] else None
            return jsonify(s), 200
        return jsonify(None), 200
    except sqlite3.Error as e:
        logger.error(f"Erreur recup session en pause: {e}")
        return jsonify({"error": "Erreur base de donnees"}), 500


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    logger.info(f"Demarrage sur le port {port}")
    app.run(debug=True, port=port, host='0.0.0.0')
