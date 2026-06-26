"""
Application Flask - Revizio
Portail de revision multi-outils pour le college.
"""

__version__ = '1.2.0'

from flask import Flask, render_template, jsonify, request, g, url_for
import sqlite3
import json
import logging
import os
import re
import random
from pathlib import Path
from datetime import datetime

import requests

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialiser Flask
app = Flask(__name__)
app.secret_key = 'revizio-portal-secret-key'


@app.context_processor
def inject_globals():
    """Injecte les variables globales dans tous les templates."""
    return {'app_version': __version__, 'tools': TOOLS}

# Configuration base de donnees
DB_PATH = Path('data/app.db')

# Configuration du proxy Claude (module histoire-geo)
# Le token reste cote serveur et ne doit JAMAIS partir vers le navigateur.
PROXY_URL = os.getenv('PROXY_URL', 'http://10.0.0.40:8005/v1/messages')
PROXY_TOKEN = os.getenv('PROXY_TOKEN', '')
PROXY_MODEL = os.getenv('PROXY_MODEL', 'claude-sonnet-4-6')

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
    {
        'id': 'histoire-geo',
        'name': 'Histoire-Géo Brevet',
        'description': 'Révise le programme d\'histoire-géo de 3e avec un prof IA',
        'icon': 'globe',
        'url': '/histoire-geo/',
        'suivi_url': '/histoire-geo/suivi',
        'color': '#e67e22',
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

            # Migration : creation des tables du module histoire-geo si absentes.
            # init_database est idempotent (CREATE IF NOT EXISTS + seed si vide),
            # il ne touche pas aux donnees existantes (verbes, sessions).
            if 'hg_themes' not in tables:
                logger.info("Migration : ajout des tables histoire-geo...")
                init_database()
            else:
                # Migration : (re)seed des questions illustrees si la table est
                # absente ou vide, ou si elle pointe encore vers d'anciens SVG
                # (cartes remplacees par des PNG bases sur les cartes officielles
                # du Brevet). Plusieurs workers gunicorn importent ce module en
                # parallele : on serialise tout dans une transaction BEGIN
                # IMMEDIATE pour qu'un seul worker migre, sans crash ni doublon.
                from setup import seed_illustrated
                conn2 = sqlite3.connect(DB_PATH, timeout=30)
                try:
                    conn2.execute("BEGIN IMMEDIATE")
                    has_table = conn2.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' "
                        "AND name='hg_illustrated_questions'"
                    ).fetchone()
                    need = True
                    if has_table:
                        oldsvg = conn2.execute(
                            "SELECT COUNT(*) FROM hg_illustrated_questions "
                            "WHERE image_path LIKE '%.svg'"
                        ).fetchone()[0]
                        total = conn2.execute(
                            "SELECT COUNT(*) FROM hg_illustrated_questions"
                        ).fetchone()[0]
                        need = (oldsvg > 0) or (total == 0)
                    if need:
                        logger.info("Migration : (re)seed des cartes illustrees...")
                        seed_illustrated(conn2)
                    conn2.commit()
                except sqlite3.Error as e:
                    logger.warning(f"Migration cartes illustrees ignoree: {e}")
                    conn2.rollback()
                finally:
                    conn2.close()


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


# === PROXY CLAUDE (module histoire-geo) ===

def _salvage_list(text):
    """Recupere les objets JSON complets d'un tableau, meme si la reponse est
    tronquee (le dernier objet incomplet est simplement ignore)."""
    start = text.find('[')
    if start == -1:
        return []
    objs = []
    depth = 0
    obj_start = None
    in_str = False
    esc = False
    for i in range(start + 1, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == '{':
            if depth == 0:
                obj_start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and obj_start is not None:
                try:
                    objs.append(json.loads(text[obj_start:i + 1]))
                except json.JSONDecodeError:
                    pass
                obj_start = None
        elif ch == ']' and depth == 0:
            break
    return objs


def ask_proxy(system, user_content, max_tokens=600, list_key=None):
    """Interroge le proxy Claude et renvoie le JSON parse de la reponse.

    Effectue un POST sur PROXY_URL (header Authorization: Bearer PROXY_TOKEN).
    Le texte renvoye peut etre encadre de fences ```json ... ``` : on les
    retire avant json.loads. Leve une exception claire en cas d'erreur
    (timeout 120s, reponse invalide, JSON non parsable).

    Si list_key est fourni, renvoie la liste sous cette cle (ex. 'questions',
    'corrections') et tolere une reponse tronquee en recuperant les objets
    complets. Sinon renvoie le dict complet.
    """
    headers = {
        'Authorization': f'Bearer {PROXY_TOKEN}',
        'Content-Type': 'application/json',
    }
    body = {
        'model': PROXY_MODEL,
        'max_tokens': max_tokens,
        'system': system,
        'messages': [{'role': 'user', 'content': user_content}],
    }

    try:
        resp = requests.post(PROXY_URL, headers=headers, json=body, timeout=120)
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Echec de l'appel au proxy Claude: {e}")

    try:
        text = resp.json()['content'][0]['text']
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"Reponse inattendue du proxy Claude: {e}")

    # Retirer d'eventuels fences markdown ```json ... ``` ou ``` ... ```
    text = text.strip()
    fence = re.match(r'^```(?:json)?\s*(.*?)\s*```$', text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()

    try:
        data = json.loads(text)
        if list_key is not None:
            if isinstance(data, dict):
                return data.get(list_key, [])
            if isinstance(data, list):
                return data
            return []
        return data
    except json.JSONDecodeError as e:
        # Reponse probablement tronquee : on tente de recuperer les objets
        # complets si on attend une liste, sinon on echoue.
        if list_key is not None:
            salvaged = _salvage_list(text)
            if salvaged:
                logger.warning(
                    "JSON tronque du proxy : %d objets recuperes", len(salvaged)
                )
                return salvaged
        raise RuntimeError(f"JSON invalide renvoye par le proxy Claude: {e}")


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


# === ROUTES HISTOIRE-GEO ===

@app.route('/histoire-geo/')
def hg_quiz():
    """Page du quiz d'histoire-geographie (Brevet 3e)."""
    return render_template('histoire_geo.html')


@app.route('/histoire-geo/suivi')
def hg_suivi():
    """Page de suivi pour le module histoire-geographie."""
    try:
        db = get_db()

        sessions = db.execute("""
            SELECT id, started_at, completed_at, mode, total_verbs,
                   total_correct, total_errors, rounds
            FROM sessions
            WHERE completed_at IS NOT NULL AND tool_type = 'histoire-geo'
            ORDER BY started_at DESC
        """).fetchall()
        sessions = [dict(s) for s in sessions]

        for session in sessions:
            answers = db.execute("""
                SELECT ha.question, ha.student_answer, ha.correct, ha.note,
                       ha.feedback, ha.correction,
                       t.matiere, t.chapitre, t.intitule
                FROM hg_answers ha
                LEFT JOIN hg_themes t ON t.id = ha.theme_id
                WHERE ha.session_id = ?
                ORDER BY ha.id
            """, (session['id'],)).fetchall()
            session['answers'] = [dict(a) for a in answers]
            total = session['total_correct'] + session['total_errors']
            session['accuracy'] = round(session['total_correct'] / total * 100) if total > 0 else 0

        # Themes les plus rates (reponses incorrectes)
        hard_themes = db.execute("""
            SELECT t.matiere, t.chapitre, t.intitule,
                   COUNT(*) as total_errors,
                   COUNT(DISTINCT ha.session_id) as sessions_with_error
            FROM hg_answers ha
            JOIN hg_themes t ON t.id = ha.theme_id
            JOIN sessions s ON s.id = ha.session_id
            WHERE s.tool_type = 'histoire-geo' AND ha.correct = 0
            GROUP BY ha.theme_id
            ORDER BY total_errors DESC
            LIMIT 10
        """).fetchall()
        hard_themes = [dict(t) for t in hard_themes]

        total_sessions = len(sessions)
        avg_accuracy = round(sum(s['accuracy'] for s in sessions) / total_sessions) if total_sessions > 0 else 0

        # Suivi par theme avec evolution dans le temps.
        # Une ligne par (theme, session) : precision du theme sur cette session.
        rows = db.execute("""
            SELECT t.id AS theme_id, t.intitule, t.matiere,
                   ha.session_id,
                   DATE(MAX(ha.created_at)) AS day,
                   MAX(ha.created_at) AS last_at,
                   COUNT(*) AS attempts,
                   SUM(ha.correct) AS correct
            FROM hg_answers ha
            JOIN hg_themes t ON t.id = ha.theme_id
            JOIN sessions s ON s.id = ha.session_id
            WHERE s.tool_type = 'histoire-geo'
            GROUP BY t.id, ha.session_id
            ORDER BY t.id, last_at
        """).fetchall()

        progress = {}  # theme_id -> agregat
        for r in rows:
            r = dict(r)
            tid = r['theme_id']
            if tid not in progress:
                progress[tid] = {
                    'theme_id': tid,
                    'intitule': r['intitule'],
                    'matiere': r['matiere'],
                    'attempts': 0,
                    'total_correct': 0,
                    'history': [],
                }
            p = progress[tid]
            attempts = r['attempts'] or 0
            correct = r['correct'] or 0
            p['attempts'] += attempts
            p['total_correct'] += correct
            sess_acc = round(correct / attempts * 100) if attempts > 0 else 0
            p['history'].append({'date': r['day'], 'accuracy': sess_acc})

        theme_progress = []
        for p in progress.values():
            p['accuracy_global'] = (
                round(p['total_correct'] / p['attempts'] * 100)
                if p['attempts'] > 0 else 0
            )
            del p['total_correct']
            theme_progress.append(p)
        # Les themes les plus faibles en premier
        theme_progress.sort(key=lambda x: x['accuracy_global'])

        return render_template('histoire_geo_suivi.html',
                               sessions=sessions,
                               hard_themes=hard_themes,
                               theme_progress=theme_progress,
                               total_sessions=total_sessions,
                               avg_accuracy=avg_accuracy)
    except sqlite3.Error as e:
        logger.error(f"Erreur base de donnees: {e}")
        return render_template('histoire_geo_suivi.html',
                               sessions=[], hard_themes=[],
                               theme_progress=[],
                               total_sessions=0, avg_accuracy=0)


# === API HISTOIRE-GEO ===

@app.route('/api/hg/themes')
def get_hg_themes():
    """Recupere la liste des themes d'histoire-geo (triee par matiere, chapitre)."""
    try:
        db = get_db()
        themes = db.execute(
            "SELECT id, matiere, chapitre, intitule FROM hg_themes "
            "ORDER BY matiere, chapitre, id"
        ).fetchall()
        return jsonify([dict(t) for t in themes]), 200
    except sqlite3.Error as e:
        logger.error(f"Erreur base de donnees: {e}")
        return jsonify({"error": "Erreur base de donnees"}), 500


@app.route('/api/hg/sessions', methods=['POST'])
def create_hg_session():
    """Cree une session histoire-geo en mode BATCH (un seul appel au proxy).

    Body {themes:[ids], count:10} (themes vide = tous les themes).

    Genere `count` questions reparties sur les themes choisis : quelques
    questions illustrees (geo) piochees dans la banque (max ~3), le reste en
    questions texte generees EN UN SEUL appel ask_proxy. Le mapping complet
    (avec expected_answer) est conserve cote serveur dans pause_state ; le
    client ne recoit jamais expected_answer.
    """
    try:
        data = request.get_json() or {}
        theme_ids = data.get('themes') or []
        count = int(data.get('count') or 10)
        if count < 1:
            count = 1

        db = get_db()

        # Resoudre la liste des themes (vide = tous)
        if theme_ids:
            placeholders = ','.join('?' for _ in theme_ids)
            themes = db.execute(
                f"SELECT id, matiere, chapitre, intitule, points_cles "
                f"FROM hg_themes WHERE id IN ({placeholders}) "
                f"ORDER BY matiere, chapitre, id",
                theme_ids
            ).fetchall()
        else:
            themes = db.execute(
                "SELECT id, matiere, chapitre, intitule, points_cles "
                "FROM hg_themes ORDER BY matiere, chapitre, id"
            ).fetchall()
        themes = [dict(t) for t in themes]

        if not themes:
            return jsonify({"error": "Aucun theme disponible"}), 400

        theme_by_id = {t['id']: t for t in themes}
        chosen_ids = list(theme_by_id.keys())

        # Piocher quelques questions illustrees liees aux themes choisis (max 3)
        illus_rows = db.execute(
            f"SELECT id, theme_id, image_path, description, question, expected_answer "
            f"FROM hg_illustrated_questions "
            f"WHERE theme_id IN ({','.join('?' for _ in chosen_ids)})",
            chosen_ids
        ).fetchall()
        illus_rows = [dict(r) for r in illus_rows]
        random.shuffle(illus_rows)
        max_illus = min(3, count, len(illus_rows))
        illus_selected = illus_rows[:max_illus]

        # Le reste = questions texte a generer
        n_text = count - len(illus_selected)

        # Repartir les n_text questions sur les themes choisis (round-robin)
        text_assignments = []  # liste de theme_id
        if n_text > 0:
            i = 0
            while len(text_assignments) < n_text:
                text_assignments.append(chosen_ids[i % len(chosen_ids)])
                i += 1

        # Compter le nombre de questions texte demandees par theme
        per_theme = {}
        for tid in text_assignments:
            per_theme[tid] = per_theme.get(tid, 0) + 1

        text_questions = []  # [{theme_id, question}]
        if n_text > 0:
            system = (
                "Tu es professeur d'histoire-géographie en 3e. Génère des "
                "questions COURTES de connaissances pures, niveau Brevet, qui "
                "appellent une réponse BRÈVE et factuelle : une date, un lieu, "
                "un personnage, un nombre, un mot de vocabulaire ou une "
                "définition en quelques mots. INTERDIT : les questions "
                "ouvertes du type « expliquez », « montrez », « décrivez », "
                "qui demandent un paragraphe. Pour chaque question, fournis "
                "aussi la réponse attendue (courte). Réponds UNIQUEMENT en "
                "JSON {\"questions\":[{\"theme_id\":int,\"question\":\"...\","
                "\"expected_answer\":\"...\"}]}. Une question par thème "
                "demandé, variées, strictement dans le programme officiel."
            )
            lines = ["Génère les questions demandées pour les thèmes suivants :"]
            for tid, nb in per_theme.items():
                t = theme_by_id[tid]
                lines.append(
                    f"- theme_id={tid} ({nb} question(s)) : {t['intitule']} "
                    f"(chapitre : {t['chapitre']}, {t['matiere']}). "
                    f"Notions clés : {t['points_cles']}"
                )
            user_content = '\n'.join(lines)

            try:
                generated = ask_proxy(
                    system, user_content, max_tokens=2000, list_key='questions'
                )
            except RuntimeError as e:
                logger.error(f"Erreur proxy (generation batch): {e}")
                return jsonify({"error": "Service IA indisponible"}), 502

            for q in generated:
                tid = q.get('theme_id')
                # Garder uniquement les themes valides
                if tid in theme_by_id and q.get('question'):
                    text_questions.append({
                        'theme_id': tid,
                        'question': q.get('question', ''),
                        'expected_answer': q.get('expected_answer') or None,
                    })
            # Tronquer si le proxy en a renvoye trop
            text_questions = text_questions[:n_text]

        # Construire la liste finale + mapping serveur
        items = []  # objets internes complets
        for q in text_questions:
            t = theme_by_id[q['theme_id']]
            items.append({
                'theme_id': q['theme_id'],
                'theme_label': f"{t['matiere']} — {t['intitule']}",
                'question': q['question'],
                'illustrated': False,
                'image_path': None,
                'expected_answer': q.get('expected_answer'),
            })
        for r in illus_selected:
            t = theme_by_id.get(r['theme_id'])
            label = f"{t['matiere']} — {t['intitule']}" if t else 'Géographie'
            items.append({
                'theme_id': r['theme_id'],
                'theme_label': label,
                'question': r['question'],
                'illustrated': True,
                'image_path': r['image_path'],
                'expected_answer': r['expected_answer'],
            })

        random.shuffle(items)

        # Attribuer un idx et construire le mapping serveur + la reponse client
        mapping = {}        # idx -> {theme_id, question, expected_answer, image_path}
        client_questions = []
        for idx, it in enumerate(items):
            mapping[str(idx)] = {
                'theme_id': it['theme_id'],
                'question': it['question'],
                'expected_answer': it['expected_answer'],
                'image_path': it['image_path'],
            }
            image_url = (
                url_for('static', filename=it['image_path'])
                if it['image_path'] else None
            )
            client_questions.append({
                'idx': idx,
                'theme_id': it['theme_id'],
                'theme_label': it['theme_label'],
                'question': it['question'],
                'image_url': image_url,
                'illustrated': it['illustrated'],
            })

        # Creer la session avec le mapping dans pause_state
        cursor = db.execute(
            "INSERT INTO sessions (tool_type, mode, total_verbs, pause_state) "
            "VALUES (?, ?, ?, ?)",
            ('histoire-geo', 'themes', len(items),
             json.dumps({'themes': chosen_ids, 'questions': mapping}))
        )
        db.commit()

        return jsonify({
            'id': cursor.lastrowid,
            'questions': client_questions,
        }), 201
    except sqlite3.Error as e:
        logger.error(f"Erreur creation session: {e}")
        return jsonify({"error": "Erreur base de donnees"}), 500


@app.route('/api/hg/sessions/<int:session_id>/correct', methods=['POST'])
def correct_hg_session(session_id):
    """Corrige TOUTES les reponses d'une session en UN SEUL appel au proxy.

    Body {answers:[{idx, answer}]}. Le mapping des questions (et les reponses
    attendues) est relu depuis pause_state ; on n'accorde aucune confiance au
    client pour les enonces / corriges.
    """
    try:
        data = request.get_json() or {}
        client_answers = data.get('answers') or []

        db = get_db()
        session = db.execute(
            "SELECT id, pause_state FROM sessions "
            "WHERE id = ? AND tool_type = 'histoire-geo'",
            (session_id,)
        ).fetchone()
        if session is None:
            return jsonify({"error": "Session introuvable"}), 404

        state = json.loads(session['pause_state']) if session['pause_state'] else {}
        mapping = state.get('questions', {})
        if not mapping:
            return jsonify({"error": "Aucune question a corriger"}), 400
    except sqlite3.Error as e:
        logger.error(f"Erreur base de donnees: {e}")
        return jsonify({"error": "Erreur base de donnees"}), 500

    # Indexer les reponses de l'eleve par idx
    answer_by_idx = {}
    for a in client_answers:
        try:
            answer_by_idx[str(a.get('idx'))] = a.get('answer', '')
        except AttributeError:
            continue

    # Construire le user_content (une entree par question)
    system = (
        "Tu es professeur d'histoire-géo en 3e qui corrige des questions de "
        "connaissances à réponse COURTE. Sois bienveillant mais précis : la "
        "réponse de l'élève est correcte dès qu'elle contient l'information "
        "essentielle attendue (l'orthographe approximative est tolérée). "
        "Marque correct=true seulement si le fond est juste. Sois CONCIS : "
        "feedback = une phrase, correction = la bonne réponse courte (pas de "
        "paragraphe, pas de développement). Réponds UNIQUEMENT en JSON "
        "{\"corrections\":[{\"idx\":int,\"correct\":bool,\"note\":\"x/5\","
        "\"feedback\":\"...\",\"correction\":\"...\"}]}."
    )
    lines = ["Corrige les réponses suivantes :"]
    ordered_idx = sorted(mapping.keys(), key=lambda k: int(k))
    for k in ordered_idx:
        q = mapping[k]
        student = answer_by_idx.get(k, '')
        entry = f"- idx={k}\n  Question : {q.get('question', '')}\n  Réponse de l'élève : {student}"
        if q.get('expected_answer'):
            entry += f"\n  Réponse attendue : {q['expected_answer']}"
        lines.append(entry)
    user_content = '\n'.join(lines)

    # Repli gracieux : si le proxy echoue, on ne plante PAS. On renvoie quand
    # meme un resultat (en s'appuyant sur les reponses attendues) pour que
    # l'eleve voie ses corrections.
    proxy_failed = False
    corr_list = []
    try:
        corr_list = ask_proxy(
            system, user_content, max_tokens=4096, list_key='corrections'
        )
    except RuntimeError as e:
        logger.error(f"Erreur proxy (correction batch): {e}")
        proxy_failed = True

    # Apparier les corrections par idx (valeurs par defaut si manquant)
    corr_by_idx = {}
    for c in corr_list:
        if isinstance(c, dict) and c.get('idx') is not None:
            corr_by_idx[str(c.get('idx'))] = c

    corrections = []
    total_correct = 0
    total_errors = 0

    try:
        db = get_db()
        for k in ordered_idx:
            q = mapping[k]
            c = corr_by_idx.get(k, {})
            has_corr = bool(c)
            correct = bool(c.get('correct'))
            note = c.get('note', '') or ('—' if not has_corr else '')
            feedback = c.get('feedback', '')
            if not feedback and not has_corr:
                feedback = ("Correction automatique indisponible pour cette "
                            "question. Voici la réponse attendue.")
            correction = c.get('correction', '') or (q.get('expected_answer') or '')
            student = answer_by_idx.get(k, '')

            if correct:
                total_correct += 1
            else:
                total_errors += 1

            db.execute("""
                INSERT INTO hg_answers
                    (session_id, theme_id, question, student_answer,
                     correct, note, feedback, correction)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id, q.get('theme_id'), q.get('question', ''), student,
                1 if correct else 0, note, feedback, correction
            ))

            corrections.append({
                'idx': int(k),
                'correct': correct,
                'note': note,
                'feedback': feedback,
                'correction': correction,
            })

        rounds = len(ordered_idx)
        db.execute("""
            UPDATE sessions
            SET completed_at = ?, total_correct = ?, total_errors = ?, rounds = ?,
                pause_state = NULL
            WHERE id = ? AND tool_type = 'histoire-geo'
        """, (
            datetime.now().isoformat(),
            total_correct, total_errors, rounds, session_id
        ))
        db.commit()
    except sqlite3.Error as e:
        logger.error(f"Erreur stockage corrections: {e}")
        return jsonify({"error": "Erreur base de donnees"}), 500

    total = total_correct + total_errors
    accuracy = round(total_correct / total * 100) if total > 0 else 0

    return jsonify({
        'summary': {
            'total_correct': total_correct,
            'total_errors': total_errors,
            'accuracy': accuracy,
        },
        'corrections': corrections,
    }), 200


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    logger.info(f"Demarrage sur le port {port}")
    app.run(debug=True, port=port, host='0.0.0.0')
