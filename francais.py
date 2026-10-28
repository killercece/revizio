"""
Module Francais de Revizio : entrainement adaptatif a l'analyse de texte, la
redaction, le vocabulaire et l'organisation des idees (programme de seconde).

Principe :
- chaque competence (francais_data.SKILLS) a un niveau (1-6) et une maitrise
  (0-1) qui evoluent selon les resultats ;
- l'IA genere l'exercice suivant au bon niveau, sur la competence la plus
  faible ou la plus ancienne, puis le corrige avec une grille ;
- un profil texte, mis a jour a chaque correction, garde la memoire de l'eleve
  et est reinjecte dans chaque prompt.
"""

import json
import logging
import random
import sqlite3
import threading
import time
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, render_template, request

from francais_data import (
    AXES, SKILLS, SKILL_IDS, SKILL_BY_ID, LEVELS, PASSAGES, PASSAGE_BY_ID,
    ORIGINAL_THEMES,
)

import auth

bp = Blueprint('francais', __name__)
logger = logging.getLogger(__name__)

_deps = {}

MAX_LEVEL = 6
# Le reverse proxy PyDeploy coupe les requetes a 30 s : generation et correction
# par l'IA tournent donc en tache de fond, le navigateur interroge /api/fr/jobs/<id>.
JOB_STALE_SECONDS = 180
RETRY_DELAY_SECONDS = 2
BILAN_EVERY = 5
BILAN_SKILLS = ['effet', 'citer', 'precision', 'phrase', 'orthographe', 'connect',
                'paragraphe', 'verbes', 'lexique']

# Ce que les scans des cours de Lucas ont montre (sequence 1 : la nouvelle).
CLASS_CONTEXT = (
    "Cette année en classe (seconde) : séquence 1 sur la nouvelle (Maupassant, "
    "Mérigeau), narrateur et point de vue, récit et schéma actantiel, paragraphe "
    "argumenté (connecteurs, insertion de citations), figures de l'analogie, lexique."
)

INITIAL_PROFILE = (
    "Lucas, seconde, moyenne 12-15 en français. Repère bien le statut du narrateur et "
    "le point de vue (19/20, 9/10) et a eu 14,75/20 au test de lecture, mais perd des "
    "points sur la précision (« soyez le plus précis possible », « mais quoi ? » de "
    "la professeure) et semble plus en difficulté pour interpréter un procédé, rédiger "
    "et organiser ses idées."
)


GENERIC_PROFILE = "Élève de seconde, profil à établir au fil des exercices."


def init(get_db, ask_proxy, db_path, legacy_owner):
    """Branche le module sur l'app (connexion DB, proxy Claude) et cree les tables.
    Les donnees creees avant les comptes sont rattachees a `legacy_owner`."""
    _deps['get_db'] = get_db
    _deps['ask_proxy'] = ask_proxy
    _deps['db_path'] = db_path
    _deps['legacy_owner'] = legacy_owner
    ensure_tables(db_path, legacy_owner)


class ApiError(Exception):
    """Erreur metier d'une tache de fond, avec un message affichable a l'eleve."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _ask(*args, **kwargs):
    """Appel IA avec une seconde tentative : le proxy coupe parfois la connexion
    sans reponse, un nouvel essai passe presque toujours."""
    try:
        return _deps['ask_proxy'](*args, **kwargs)
    except RuntimeError as e:
        logger.warning(f"Appel IA echoue, nouvel essai : {e}")
        time.sleep(RETRY_DELAY_SECONDS)
        return _deps['ask_proxy'](*args, **kwargs)


def _start_job(user, fn):
    """Lance fn(conn) dans un thread pour `user` et renvoie l'id de la tache.

    Le resultat est stocke en base (et non en memoire) car plusieurs workers
    gunicorn se partagent les requetes de polling.
    """
    db = _db()
    db.execute("DELETE FROM fr_jobs WHERE created_at < ?",
               ((datetime.now() - timedelta(days=1)).isoformat(),))
    cur = db.execute("INSERT INTO fr_jobs (user_email, status, created_at) "
                     "VALUES (?, 'running', ?)", (user, datetime.now().isoformat()))
    db.commit()
    job_id = cur.lastrowid

    def runner():
        conn = sqlite3.connect(_deps['db_path'], timeout=30)
        conn.row_factory = sqlite3.Row
        status, result, error = 'error', None, "Erreur inattendue, réessaie."
        try:
            result = json.dumps(fn(conn), ensure_ascii=False)
            status, error = 'done', None
        except ApiError as e:
            error = str(e)
        except Exception:
            logger.exception("Erreur inattendue dans une tache francais")
        try:
            conn.execute("UPDATE fr_jobs SET status = ?, result = ?, error = ? WHERE id = ?",
                         (status, result, error, job_id))
            conn.commit()
        finally:
            conn.close()

    threading.Thread(target=runner, daemon=True).start()
    return job_id


SCHEMA = [
    """CREATE TABLE IF NOT EXISTS fr_skill_state (
        user_email TEXT NOT NULL,
        skill TEXT NOT NULL,
        mastery REAL NOT NULL DEFAULT 0.3,
        level INTEGER NOT NULL DEFAULT 2,
        attempts INTEGER NOT NULL DEFAULT 0,
        streak_good INTEGER NOT NULL DEFAULT 0,
        streak_bad INTEGER NOT NULL DEFAULT 0,
        remediate INTEGER NOT NULL DEFAULT 0,
        last_at TEXT,
        next_review TEXT,
        PRIMARY KEY (user_email, skill)
    )""",
    """CREATE TABLE IF NOT EXISTS fr_exercises (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_email TEXT,
        skill TEXT NOT NULL,
        level INTEGER NOT NULL,
        kind TEXT NOT NULL,
        passage_id TEXT,
        skills TEXT NOT NULL,
        payload TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL,
        completed_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS fr_attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        exercise_id INTEGER NOT NULL REFERENCES fr_exercises(id),
        attempt_no INTEGER NOT NULL,
        answers TEXT NOT NULL,
        score REAL NOT NULL,
        feedback TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS fr_profile (
        user_email TEXT PRIMARY KEY,
        summary TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS fr_vocab (
        user_email TEXT NOT NULL,
        word TEXT NOT NULL,
        meaning TEXT NOT NULL,
        seen INTEGER NOT NULL DEFAULT 1,
        learned_at TEXT NOT NULL,
        PRIMARY KEY (user_email, word)
    )""",
    """CREATE TABLE IF NOT EXISTS fr_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_email TEXT NOT NULL,
        status TEXT NOT NULL,
        result TEXT,
        error TEXT,
        created_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_fr_attempts_ex ON fr_attempts(exercise_id)",
]


def _columns(conn, table):
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def ensure_tables(db_path, legacy_owner):
    """Cree les tables du module (idempotent, ne touche pas aux autres outils) et
    migre l'ancien schema commun vers un schema par utilisateur.

    BEGIN IMMEDIATE serialise les workers gunicorn qui demarrent ensemble.
    """
    conn = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        # 1. anciennes tables sans proprietaire : mises de cote avant recreation
        old = [t for t in ('fr_skill_state', 'fr_profile', 'fr_vocab')
               if _columns(conn, t) and 'user_email' not in _columns(conn, t)]
        for t in old:
            conn.execute(f"ALTER TABLE {t} RENAME TO {t}_old")
        if _columns(conn, 'fr_jobs') and 'user_email' not in _columns(conn, 'fr_jobs'):
            conn.execute("DROP TABLE fr_jobs")  # taches ephemeres : rien a conserver
        for statement in SCHEMA:
            conn.execute(statement)
        # 2. historique existant rattache au proprietaire d'origine
        if 'fr_skill_state' in old:
            conn.execute("""
                INSERT INTO fr_skill_state (user_email, skill, mastery, level, attempts,
                    streak_good, streak_bad, remediate, last_at, next_review)
                SELECT ?, skill, mastery, level, attempts, streak_good, streak_bad,
                    remediate, last_at, next_review FROM fr_skill_state_old
            """, (legacy_owner,))
        if 'fr_profile' in old:
            conn.execute("INSERT INTO fr_profile (user_email, summary, updated_at) "
                         "SELECT ?, summary, updated_at FROM fr_profile_old WHERE id = 1",
                         (legacy_owner,))
        if 'fr_vocab' in old:
            conn.execute("INSERT INTO fr_vocab (user_email, word, meaning, seen, learned_at) "
                         "SELECT ?, word, meaning, seen, learned_at FROM fr_vocab_old",
                         (legacy_owner,))
        for t in old:
            conn.execute(f"DROP TABLE {t}_old")
        if 'user_email' not in _columns(conn, 'fr_exercises'):
            conn.execute("ALTER TABLE fr_exercises ADD COLUMN user_email TEXT")
        conn.execute("UPDATE fr_exercises SET user_email = ? WHERE user_email IS NULL",
                     (legacy_owner,))
        conn.execute("CREATE INDEX IF NOT EXISTS idx_fr_ex_user "
                     "ON fr_exercises(user_email, status)")
        conn.execute("COMMIT")
    except sqlite3.Error:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def _ensure_user(db, user):
    """Cree l'etat initial d'un utilisateur la premiere fois qu'on le voit."""
    have = db.execute("SELECT COUNT(*) AS c FROM fr_skill_state WHERE user_email = ?",
                      (user,)).fetchone()['c']
    if have == len(SKILL_IDS) and db.execute(
            "SELECT 1 FROM fr_profile WHERE user_email = ?", (user,)).fetchone():
        return
    # Premiere visite, ou competence ajoutee depuis : on complete sans toucher a l'existant
    profile = INITIAL_PROFILE if user == _deps.get('legacy_owner') else GENERIC_PROFILE
    db.executemany("INSERT OR IGNORE INTO fr_skill_state (user_email, skill) VALUES (?, ?)",
                   [(user, sid) for sid in SKILL_IDS])
    db.execute("INSERT OR IGNORE INTO fr_profile (user_email, summary, updated_at) "
               "VALUES (?, ?, ?)", (user, profile, datetime.now().isoformat()))
    db.commit()


# === MOTEUR ADAPTATIF (fonctions pures, testables) ===

def review_interval_days(mastery):
    """Delai avant de reproposer une competence, selon sa maitrise."""
    if mastery < 0.5:
        return 1
    if mastery < 0.7:
        return 3
    if mastery < 0.85:
        return 7
    return 14


def apply_result(state, score, attempt_no=1, now=None):
    """Met a jour l'etat d'une competence apres un exercice note `score` (0-1).

    Renvoie (nouvel_etat, ancien_niveau). Regles :
    - premier exercice sur la competence (placement) : >= 0.85 saute 2 niveaux,
      < 0.4 descend d'un niveau ;
    - 3 bons resultats d'affilee (>= 0.8) : +1 niveau (+2 si maitrise >= 0.9) ;
    - 2 mauvais d'affilee (< 0.5) : -1 niveau et exercice de remediation ensuite ;
    - un second essai pese moins et ne modifie pas le niveau.
    """
    now = now or datetime.now()
    st = dict(state)
    old_level = st['level']
    weight = 0.4 if attempt_no == 1 else 0.2
    first = st['attempts'] == 0
    st['mastery'] = round(st['mastery'] * (1 - weight) + score * weight, 3)

    if attempt_no == 1:
        st['attempts'] += 1
        if score >= 0.8:
            st['streak_good'] += 1
            st['streak_bad'] = 0
        elif score < 0.5:
            st['streak_bad'] += 1
            st['streak_good'] = 0
        else:
            st['streak_good'] = 0
            st['streak_bad'] = 0

        if first and score >= 0.85:
            st['level'] += 2
            st['streak_good'] = 0
        elif first and score < 0.4:
            st['level'] -= 1
            st['streak_bad'] = 0
            st['remediate'] = 1
        elif st['streak_good'] >= 3:
            st['level'] += 2 if st['mastery'] >= 0.9 else 1
            st['streak_good'] = 0
        elif st['streak_bad'] >= 2:
            st['level'] -= 1
            st['streak_bad'] = 0
            st['remediate'] = 1

    st['level'] = max(1, min(MAX_LEVEL, st['level']))
    st['last_at'] = now.isoformat()
    st['next_review'] = (now + timedelta(days=review_interval_days(st['mastery']))).isoformat()
    return st, old_level


def pick_skill(states, avoid=None, now=None, rng=random):
    """Choisit la prochaine competence : faible, ancienne ou a revoir en priorite."""
    now = now or datetime.now()
    scored = []
    for sid in SKILL_IDS:
        st = states[sid]
        prio = 1 - st['mastery']
        if st['last_at']:
            days = (now - datetime.fromisoformat(st['last_at'])).total_seconds() / 86400
            prio += min(days / 14, 0.4)
        else:
            prio += 0.3
        if st['next_review'] and st['next_review'] <= now.isoformat():
            prio += 0.3
        if st['streak_bad'] > 0 or st['remediate']:
            prio += 0.2
        if sid == avoid:
            prio -= 0.5
        scored.append((prio, sid))
    scored.sort(reverse=True)
    top = scored[:3]
    return rng.choices([s for _, s in top], weights=[max(p, 0.05) for p, _ in top])[0]


# === ACCES DONNEES ===

def _db():
    return _deps['get_db']()


def _load_states(db, user):
    _ensure_user(db, user)
    return {r['skill']: dict(r) for r in db.execute(
        "SELECT * FROM fr_skill_state WHERE user_email = ?", (user,))}


def _save_state(db, user, st):
    db.execute("""
        UPDATE fr_skill_state SET mastery=?, level=?, attempts=?, streak_good=?,
            streak_bad=?, remediate=?, last_at=?, next_review=?
        WHERE skill=? AND user_email=?
    """, (st['mastery'], st['level'], st['attempts'], st['streak_good'],
          st['streak_bad'], st['remediate'], st['last_at'], st['next_review'],
          st['skill'], user))


def _profile(db, user):
    _ensure_user(db, user)
    row = db.execute("SELECT summary FROM fr_profile WHERE user_email = ?", (user,)).fetchone()
    return row['summary'] if row else GENERIC_PROFILE


def _recent_error_tags(db, user, limit=6):
    """Erreurs les plus frequentes dans les derniers essais de l'utilisateur."""
    counts = {}
    for r in db.execute("""
            SELECT a.feedback FROM fr_attempts a
            JOIN fr_exercises e ON e.id = a.exercise_id
            WHERE e.user_email = ? ORDER BY a.id DESC LIMIT ?""", (user, limit)):
        try:
            for tag in json.loads(r['feedback']).get('erreurs', []):
                counts[tag] = counts.get(tag, 0) + 1
        except (ValueError, AttributeError):
            continue
    return [t for t, _ in sorted(counts.items(), key=lambda kv: -kv[1])[:4]]


def _exercises_since_last_bilan(db, user):
    last = db.execute(
        "SELECT MAX(id) AS m FROM fr_exercises "
        "WHERE kind = 'bilan' AND status = 'done' AND user_email = ?", (user,)
    ).fetchone()['m'] or 0
    return db.execute(
        "SELECT COUNT(*) AS c FROM fr_exercises WHERE status = 'done' AND kind != 'bilan' "
        "AND id > ? AND user_email = ?", (last, user)
    ).fetchone()['c']


# === GENERATION D'EXERCICE ===

GEN_SYSTEM = (
    "Tu es professeur de français en classe de seconde générale (France). Tu conçois "
    "UN exercice d'entraînement pour Lucas, 15 ans, bon élève (12 à 15 de moyenne en "
    "français) : il repère bien les procédés et le point de vue, mais ses réponses "
    "restent imprécises et il peine à interpréter, rédiger et organiser ses idées. "
    "L'exercice doit durer 5 à 10 minutes, être concret, sans cours théorique : de la "
    "mise en pratique. Les questions exigent de la précision (cite, nomme, explique). "
    "Le but est la clarté, la précision et l'aisance d'un élève plutôt scientifique, "
    "pas le style littéraire. "
    "Chaque question est autonome et claire pour un élève seul. Tutoie l'élève "
    "(« tu », « cite », « explique ») dans la consigne et les questions. "
    "Réponds UNIQUEMENT en JSON : {\"titre\":\"court\",\"consigne\":\"1 à 2 phrases "
    "qui disent quoi faire et le rappel de méthode utile\","
    "\"passage\":{\"source\":\"...\",\"texte\":\"...\"},"
    "\"questions\":[{\"enonce\":\"...\",\"attendu\":\"éléments précis attendus, pour "
    "le correcteur uniquement\",\"indice\":\"coup de pouce court qui ne donne PAS la "
    "réponse\",\"longueur\":\"1 phrase|2-3 phrases|paragraphe\"}]}. "
    "Le champ passage n'est à fournir que si on te demande d'écrire un texte original."
)


def _choose_passage(db, user, skill_id, kind):
    """Renvoie un passage classique non encore utilise pour cette competence, ou None
    (l'IA ecrira alors un texte original, signale comme tel)."""
    used = {r['passage_id'] for r in db.execute(
        "SELECT passage_id FROM fr_exercises "
        "WHERE skill = ? AND user_email = ? AND passage_id IS NOT NULL",
        (skill_id, user))}
    pool = [p for p in PASSAGES if p['id'] not in used]
    if skill_id in ('pdv', 'recit'):
        pool = [p for p in pool if p['genre'] == 'prose']
    if kind == 'bilan':
        pool = [p for p in pool if p['genre'] == 'prose' or random.random() < 0.5]
    if pool and random.random() < 0.65:
        return random.choice(pool)
    return None


def generate_exercise(db, user, skill_id, kind='atelier', force_new_level=None):
    """Genere (et enregistre) un exercice via l'IA. Leve RuntimeError en cas d'echec."""
    states = _load_states(db, user)
    if kind == 'bilan':
        core = [states[s]['level'] for s in ('effet', 'citer', 'paragraphe', 'precision')]
        level = max(2, min(MAX_LEVEL, round(sum(core) / len(core))))
        skills = list(BILAN_SKILLS)
        skill_id = 'bilan'
    else:
        st = states[skill_id]
        level = force_new_level or st['level']
        skills = [skill_id]
        if st['remediate']:
            kind = 'remediation'

    passage = _choose_passage(db, user, skill_id, kind)
    lines = []
    if kind == 'bilan':
        lines.append(
            "TYPE : BILAN. Tâche plus longue qui combine plusieurs compétences : une "
            "première question de repérage précis, puis une question demandant de "
            "rédiger un paragraphe argumenté (idée, citation, explication). Le niveau "
            "de difficulté est celui indiqué ci-dessous.")
        lines.append("Compétences évaluées : " + ", ".join(
            f"{SKILL_BY_ID[s]['label']}" for s in skills))
    else:
        sk = SKILL_BY_ID[skill_id]
        lines.append(f"COMPÉTENCE CIBLÉE : {sk['label']} — {sk['desc']}.")
        if kind == 'remediation':
            lines.append(
                "TYPE : REMÉDIATION. L'élève a échoué plusieurs fois sur cette compétence : "
                "décompose la difficulté en une toute petite marche, avec des questions "
                "très ciblées sur le point précis qui bloque, et un exemple modèle dans la "
                "consigne.")
    lines.append(LEVELS[level])
    lines.append(f"CONTEXTE DE CLASSE : {CLASS_CONTEXT}")
    lines.append(f"PROFIL DE L'ÉLÈVE : {_profile(db, user)}")
    tags = _recent_error_tags(db, user)
    if tags:
        lines.append("ERREURS RÉCURRENTES À CIBLER : " + ", ".join(tags))
    words = [r['word'] for r in db.execute(
        "SELECT word FROM fr_vocab WHERE user_email = ? ORDER BY learned_at DESC LIMIT 6",
        (user,))]
    if words:
        lines.append("MOTS RÉCEMMENT APPRIS (réemploie-en un ou deux si naturel) : "
                     + ", ".join(words))
    recent = [r['payload'] for r in db.execute(
        "SELECT payload FROM fr_exercises WHERE user_email = ? ORDER BY id DESC LIMIT 6",
        (user,))]
    titles = []
    for p in recent:
        try:
            titles.append(json.loads(p).get('titre', ''))
        except ValueError:
            pass
    if titles:
        lines.append("EXERCICES RÉCENTS (ne les répète pas, varie les formulations et les "
                     "types de questions) : " + " | ".join(t for t in titles if t))

    if passage:
        lines.append(f"TEXTE SUPPORT (ne le reproduis pas dans ta réponse) : "
                     f"{passage['source']}\n{passage['texte']}")
    else:
        theme = random.choice(ORIGINAL_THEMES)
        lines.append(
            f"Écris toi-même un texte ORIGINAL de 60 à 130 mots ({theme}), adapté au "
            "niveau, avec un sens à interpréter. Mets-le dans passage.texte et écris "
            "dans passage.source « Texte original écrit pour l'exercice (dans l'esprit "
            "de <auteur>) ». Retour à la ligne pour les vers.")

    data = _ask(GEN_SYSTEM, "\n\n".join(lines), max_tokens=2500,
                              temperature=0.9)
    if not isinstance(data, dict):
        raise RuntimeError("Exercice invalide renvoyé par l'IA")
    questions = [q for q in data.get('questions', [])
                 if isinstance(q, dict) and q.get('enonce')]
    if not questions:
        raise RuntimeError("Exercice sans question")
    for i, q in enumerate(questions, 1):
        q['id'] = i
        q.setdefault('attendu', '')
        q.setdefault('indice', '')
        q.setdefault('longueur', '2-3 phrases')

    if passage:
        shown = {'source': passage['source'], 'texte': passage['texte'], 'original': False}
    else:
        p = data.get('passage') or {}
        if not p.get('texte'):
            raise RuntimeError("Exercice sans texte support")
        shown = {'source': p.get('source') or "Texte original écrit pour l'exercice",
                 'texte': p['texte'], 'original': True}

    payload = {
        'titre': data.get('titre') or 'Exercice',
        'consigne': data.get('consigne') or '',
        'passage': shown,
        'questions': questions,
    }
    if kind != 'bilan':
        db.execute("UPDATE fr_skill_state SET remediate = 0 WHERE skill = ? AND user_email = ?",
                   (skill_id, user))
    cur = db.execute("""
        INSERT INTO fr_exercises (user_email, skill, level, kind, passage_id, skills,
                                  payload, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (user, skill_id, level, kind, passage['id'] if passage else None,
          json.dumps(skills), json.dumps(payload, ensure_ascii=False),
          datetime.now().isoformat()))
    db.commit()
    return cur.lastrowid


def _client_exercise(row, attempts=0):
    """Version de l'exercice envoyee au navigateur (sans les elements attendus)."""
    payload = json.loads(row['payload'])
    skills = json.loads(row['skills'])
    return {
        'id': row['id'],
        'kind': row['kind'],
        'level': row['level'],
        'skill': row['skill'],
        'skill_label': ('Bilan' if row['skill'] == 'bilan'
                        else SKILL_BY_ID[row['skill']]['label']),
        'skills': [SKILL_BY_ID[s]['label'] for s in skills if s in SKILL_BY_ID],
        'titre': payload['titre'],
        'consigne': payload['consigne'],
        'passage': payload['passage'],
        'questions': [{k: q[k] for k in ('id', 'enonce', 'indice', 'longueur')}
                      for q in payload['questions']],
        'attempts': attempts,
    }


# === CORRECTION ===

CORR_SYSTEM = (
    "Tu es professeur de français en seconde, correcteur bienveillant mais exigeant "
    "sur la PRÉCISION (point faible de l'élève), la QUALITÉ DE LA RÉDACTION, le "
    "VOCABULAIRE et l'ORTHOGRAPHE. L'élève est un scientifique dans l'âme : le but "
    "n'est pas d'en faire un écrivain mais de le rendre clair, précis et à l'aise à un "
    "niveau seconde. Ne propose jamais de style fleuri ou littéraire : des mots justes "
    "et des phrases nettes qu'un élève de 15 ans peut réellement employer. "
    "Reste toujours encourageant : commence par ce qui va, formule chaque défaut comme "
    "une amélioration possible, jamais comme un reproche. N'emploie jamais les mots "
    "« bannir », « interdit », « fautif », « littéraire », « soutenu » ; dis plutôt "
    "« à l'écrit, on écrit plutôt… », « c'est plus précis », « c'est plus clair ». Principes : "
    "1) note chaque question de 0 à 1 selon la justesse, la précision, la citation et "
    "l'expression ; une réponse vague ou incomplète ne dépasse pas 0,6 ; une réponse "
    "vide vaut 0 ; "
    "2) le commentaire cible l'erreur exacte en citant un mot de la réponse de l'élève "
    "(1 à 2 phrases, jamais de ton condescendant) ; "
    "3) indice_retry aide à améliorer la réponse SANS la donner ; "
    "4) une seule priorité, concrète et actionnable ; "
    "5) modele = corrigé rédigé comme un très bon élève de seconde, un par question ; "
    "6) erreurs : tags snake_case parmi reponse_vague, reponse_incomplete, "
    "citation_absente, citation_trop_longue, paraphrase_sans_interpretation, "
    "procede_mal_nomme, contresens, verbe_pauvre, connecteur_repete, "
    "phrase_trop_longue, phrase_orale, hors_sujet, structure_absente (liste vide si "
    "aucune) ; "
    "7) competences : note de 0 à 1 pour CHAQUE compétence demandée ; "
    "8) mots : 0 à 3 mots de vocabulaire utiles à retenir, avec un sens court ; "
    "9) profil : nouveau résumé (500 caractères maximum) du profil de l'élève, qui "
    "intègre ce que tu viens de voir sans perdre les constats antérieurs encore valables. "
    "Une seule copie ne change pas le profil de fond : reste mesuré, distingue les "
    "constats confirmés sur plusieurs exercices des simples observations du jour, et "
    "ne qualifie jamais l'élève de façon négative ou définitive ; "
    "10) tutoie l'élève dans les commentaires et les pistes, avec un ton encourageant et "
    "exigeant, jamais sec ni ironique ; "
    "11) ameliorations : 2 à 4 passages que l'élève a écrits et qui peuvent être "
    "améliorés (mot pauvre ou répété, verbe vague comme « montre » ou « dit », "
    "tournure lourde ou orale, phrase confuse). Pour chacun : extrait = ses mots exacts, "
    "type = vocabulaire ou tournure, propositions = 2 ou 3 remplacements (synonymes "
    "précis ou tournures différentes) de niveau seconde, courts et réutilisables, "
    "pourquoi = une courte explication. Si la réponse est correcte, propose quand même "
    "une variante plus précise ; "
    "12) orthographe : relève jusqu'à 5 fautes réelles (orthographe, accord, conjugaison, "
    "homophone) avec faute = le mot ou groupe fautif, correction, regle = rappel en une "
    "phrase très courte. Liste vide s'il n'y en a pas, et dis-le dans point_fort. "
    "Ajoute le tag faute_orthographe dans erreurs s'il y en a plusieurs. "
    "Pour orthographe, ne note pas la compétence « orthographe » comme les autres : "
    "0,9 et plus s'il y a au plus 1 faute, 0,6 pour 2 à 3 fautes, 0,3 au-delà. "
    "Réponds UNIQUEMENT en JSON : {\"questions\":[{\"id\":1,\"score\":0.0,"
    "\"commentaire\":\"...\",\"indice_retry\":\"...\"}],\"competences\":{\"id\":0.0},"
    "\"point_fort\":\"...\",\"priorite\":\"...\",\"erreurs\":[\"tag\"],"
    "\"ameliorations\":[{\"extrait\":\"...\",\"type\":\"vocabulaire|tournure\","
    "\"propositions\":[\"...\",\"...\"],\"pourquoi\":\"...\"}],"
    "\"orthographe\":[{\"faute\":\"...\",\"correction\":\"...\",\"regle\":\"...\"}],"
    "\"modele\":[{\"id\":1,\"texte\":\"...\"}],\"mots\":[{\"mot\":\"...\",\"sens\":\"...\"}],"
    "\"profil\":\"...\"}"
)


def _scored_skills(skills):
    """Competences notees a chaque correction : celles de l'exercice, plus
    l'orthographe, evaluee sur tout ce que l'eleve ecrit."""
    return skills if 'orthographe' in skills else skills + ['orthographe']


def _clean_improvements(raw):
    """Garde des ameliorations bien formees (extrait + au moins une proposition)."""
    out = []
    for a in (raw or []):
        if not isinstance(a, dict) or not a.get('extrait'):
            continue
        props = [str(p) for p in (a.get('propositions') or []) if str(p).strip()][:3]
        if props:
            out.append({'extrait': str(a['extrait'])[:200],
                        'type': 'tournure' if a.get('type') == 'tournure' else 'vocabulaire',
                        'propositions': props,
                        'pourquoi': str(a.get('pourquoi', ''))[:240]})
    return out[:4]


def _clean_spelling(raw):
    out = []
    for f in (raw or []):
        if isinstance(f, dict) and f.get('faute') and f.get('correction'):
            out.append({'faute': str(f['faute'])[:80], 'correction': str(f['correction'])[:80],
                        'regle': str(f.get('regle', ''))[:200]})
    return out[:5]


def _clamp01(v, default=0.0):
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return default


def _build_overview(db, user):
    states = _load_states(db, user)
    axes = []
    for ax in AXES:
        skills = []
        for s in SKILLS:
            if s['axis'] != ax['id']:
                continue
            st = states[s['id']]
            skills.append({
                'id': s['id'], 'label': s['label'], 'desc': s['desc'],
                'mastery': round(st['mastery'] * 100), 'level': st['level'],
                'attempts': st['attempts'], 'last_at': st['last_at'],
            })
        avg = round(sum(x['mastery'] for x in skills) / len(skills))
        axes.append({'id': ax['id'], 'label': ax['label'], 'mastery': avg, 'skills': skills})
    pending = db.execute(
        "SELECT id FROM fr_exercises WHERE status = 'pending' AND user_email = ? "
        "ORDER BY id DESC LIMIT 1", (user,)
    ).fetchone()
    since = _exercises_since_last_bilan(db, user)
    return {
        'axes': axes,
        'profile': _profile(db, user),
        'pending_id': pending['id'] if pending else None,
        'since_bilan': since,
        'bilan_due': since >= BILAN_EVERY,
        'bilan_every': BILAN_EVERY,
    }


# === ROUTES ===

@bp.route('/francais/')
def fr_home():
    return render_template('francais.html')


@bp.route('/francais/suivi')
def fr_suivi():
    db = _db()
    viewed = auth.viewed_email()
    history = []
    for r in db.execute("""
        SELECT a.score, a.attempt_no, a.created_at, e.skill, e.level, e.kind, e.payload
        FROM fr_attempts a JOIN fr_exercises e ON e.id = a.exercise_id
        WHERE e.user_email = ?
        ORDER BY a.id DESC LIMIT 40
    """, (viewed,)):
        history.append({
            'date': r['created_at'][:16].replace('T', ' '),
            'titre': json.loads(r['payload']).get('titre', ''),
            'skill': ('Bilan' if r['skill'] == 'bilan' else SKILL_BY_ID[r['skill']]['label']),
            'level': r['level'], 'kind': r['kind'], 'attempt_no': r['attempt_no'],
            'score': round(r['score'] * 100),
        })
    vocab = [dict(r) for r in db.execute(
        "SELECT word, meaning FROM fr_vocab WHERE user_email = ? "
        "ORDER BY learned_at DESC LIMIT 40", (viewed,))]
    return render_template('francais_suivi.html', overview=_build_overview(db, viewed),
                           history=history, vocab=vocab,
                           tags=_recent_error_tags(db, viewed, 12))


@bp.route('/api/fr/overview')
def api_overview():
    return jsonify(_build_overview(_db(), auth.owner_email()))


@bp.route('/api/fr/next', methods=['POST'])
def api_next():
    """Renvoie l'exercice en cours, ou en genere un nouveau.

    Body optionnel : {skill: id} pour forcer une competence, {bilan: true} pour un
    bilan, {fresh: true} pour ignorer l'exercice en attente.
    """
    data = request.get_json(silent=True) or {}
    db = _db()
    user = auth.owner_email()
    skill = data.get('skill')
    if skill is not None and skill not in SKILL_BY_ID:
        return jsonify({'error': 'Compétence inconnue'}), 400

    if not data.get('fresh') and not skill and not data.get('bilan'):
        row = db.execute(
            "SELECT * FROM fr_exercises WHERE status = 'pending' AND user_email = ? "
            "ORDER BY id DESC LIMIT 1", (user,)
        ).fetchone()
        if row:
            return jsonify(_client_exercise(row))

    kind = 'atelier'
    if data.get('bilan') or (not skill and _exercises_since_last_bilan(db, user) >= BILAN_EVERY):
        kind = 'bilan'
    elif not skill:
        last = db.execute(
            "SELECT skill FROM fr_exercises WHERE user_email = ? ORDER BY id DESC LIMIT 1",
            (user,)).fetchone()
        skill = pick_skill(_load_states(db, user), avoid=last['skill'] if last else None)

    def make(conn):
        try:
            ex_id = generate_exercise(conn, user, skill, kind)
        except RuntimeError as e:
            logger.error(f"Erreur generation exercice francais: {e}")
            raise ApiError("Impossible de préparer l'exercice pour le moment. Réessaie.", 502)
        # Un exercice laisse de cote ne doit pas reapparaitre comme "a reprendre"
        conn.execute("UPDATE fr_exercises SET status = 'skipped' "
                     "WHERE status = 'pending' AND id != ? AND user_email = ?", (ex_id, user))
        conn.commit()
        row = conn.execute("SELECT * FROM fr_exercises WHERE id = ?", (ex_id,)).fetchone()
        return _client_exercise(row)

    return jsonify({'job': _start_job(user, make)}), 202


@bp.route('/api/fr/exercises/<int:ex_id>/correct', methods=['POST'])
def api_correct(ex_id):
    """Valide la demande puis corrige en tache de fond (voir _start_job)."""
    db = _db()
    user = auth.owner_email()
    row = db.execute("SELECT * FROM fr_exercises WHERE id = ? AND user_email = ?",
                     (ex_id, user)).fetchone()
    if row is None:
        return jsonify({'error': 'Exercice introuvable'}), 404

    data = request.get_json(silent=True) or {}
    raw = data.get('answers') or {}
    payload = json.loads(row['payload'])
    answers = {str(q['id']): str(raw.get(str(q['id']), '')).strip()[:3000]
               for q in payload['questions']}
    if not any(answers.values()):
        return jsonify({'error': 'Écris au moins une réponse.'}), 400
    done = db.execute("SELECT COUNT(*) AS c FROM fr_attempts WHERE exercise_id = ?",
                      (ex_id,)).fetchone()['c']
    if done >= 2:
        return jsonify({'error': 'Cet exercice a déjà été corrigé deux fois.'}), 400

    return jsonify({'job': _start_job(
        user, lambda conn: _run_correction(conn, user, ex_id, answers))}), 202


@bp.route('/api/fr/jobs/<int:job_id>')
def api_job(job_id):
    """Etat d'une tache de fond : running, done (result) ou error."""
    db = _db()
    row = db.execute("SELECT * FROM fr_jobs WHERE id = ? AND user_email = ?",
                     (job_id, auth.owner_email())).fetchone()
    if row is None:
        return jsonify({'error': 'Tâche introuvable'}), 404
    if row['status'] == 'running':
        age = (datetime.now() - datetime.fromisoformat(row['created_at'])).total_seconds()
        if age > JOB_STALE_SECONDS:
            # Le worker a probablement ete redemarre pendant la tache
            db.execute("UPDATE fr_jobs SET status = 'error', error = ? WHERE id = ?",
                       ("L'IA a mis trop de temps à répondre. Réessaie.", job_id))
            db.commit()
            return jsonify({'status': 'error', 'error': "L'IA a mis trop de temps à répondre. Réessaie."})
        return jsonify({'status': 'running'})
    if row['status'] == 'done':
        return jsonify({'status': 'done', 'result': json.loads(row['result'])})
    return jsonify({'status': 'error', 'error': row['error']})


def _run_correction(db, user, ex_id, answers):
    """Corrige un exercice via l'IA, met a jour competences, profil et vocabulaire.
    Renvoie la reponse destinee au navigateur ; leve ApiError en cas d'echec."""
    row = db.execute("SELECT * FROM fr_exercises WHERE id = ? AND user_email = ?",
                     (ex_id, user)).fetchone()
    if row is None:
        raise ApiError('Exercice introuvable', 404)
    payload = json.loads(row['payload'])
    prev = db.execute(
        "SELECT * FROM fr_attempts WHERE exercise_id = ? ORDER BY attempt_no", (ex_id,)
    ).fetchall()
    attempt_no = len(prev) + 1
    if attempt_no > 2:
        raise ApiError('Cet exercice a déjà été corrigé deux fois.')

    skills = json.loads(row['skills'])
    lines = [
        f"EXERCICE : {payload['titre']} (niveau {row['level']}, type {row['kind']})",
        f"CONSIGNE : {payload['consigne']}",
        f"TEXTE : {payload['passage']['source']}\n{payload['passage']['texte']}",
        f"PROFIL DE L'ÉLÈVE : {_profile(db, user)}",
        "COMPÉTENCES À NOTER (clé = id) : " + "; ".join(
            f"{s} = {SKILL_BY_ID[s]['label']}" for s in _scored_skills(skills)),
        f"ESSAI N°{attempt_no}",
    ]
    if prev:
        old = json.loads(prev[-1]['feedback'])
        old_answers = json.loads(prev[-1]['answers'])
        lines.append("PREMIER ESSAI (réponses) : " + json.dumps(old_answers, ensure_ascii=False))
        lines.append(f"PRIORITÉ DONNÉE APRÈS LE PREMIER ESSAI : {old.get('priorite', '')}")
        lines.append("Évalue aussi si l'élève a tenu compte de la priorité.")
    for q in payload['questions']:
        lines.append(f"QUESTION {q['id']} : {q['enonce']}\n"
                     f"ATTENDU : {q['attendu']}\n"
                     f"RÉPONSE DE L'ÉLÈVE : {answers[str(q['id'])] or '(vide)'}")

    try:
        fb = _ask(CORR_SYSTEM, "\n\n".join(lines), max_tokens=4000,
                                temperature=0.3)
    except RuntimeError as e:
        logger.error(f"Erreur correction francais: {e}")
        raise ApiError("La correction est indisponible pour le moment. Tes réponses sont gardées, réessaie.", 502)
    if not isinstance(fb, dict) or not isinstance(fb.get('questions'), list):
        raise ApiError("Correction illisible, réessaie.", 502)

    by_id = {str(c.get('id')): c for c in fb['questions'] if isinstance(c, dict)}
    q_results = []
    for q in payload['questions']:
        c = by_id.get(str(q['id']), {})
        score = 0.0 if not answers[str(q['id'])] else _clamp01(c.get('score'))
        q_results.append({
            'id': q['id'], 'score': round(score, 2),
            'commentaire': str(c.get('commentaire', '')),
            'indice_retry': str(c.get('indice_retry', '')),
        })
    overall = sum(r['score'] for r in q_results) / len(q_results)

    # Mise a jour des competences (note par competence, a defaut la note globale)
    comp = fb.get('competences') if isinstance(fb.get('competences'), dict) else {}
    states = _load_states(db, user)
    level_changes = []
    for s in _scored_skills(skills):
        sc = _clamp01(comp.get(s), default=overall)
        new_state, old_level = apply_result(states[s], sc, attempt_no)
        _save_state(db, user, new_state)
        if new_state['level'] != old_level:
            level_changes.append({'skill': SKILL_BY_ID[s]['label'],
                                  'from': old_level, 'to': new_state['level']})

    profil = str(fb.get('profil') or '').strip()[:700]
    if profil:
        db.execute("UPDATE fr_profile SET summary = ?, updated_at = ? WHERE user_email = ?",
                   (profil, datetime.now().isoformat(), user))
    mots = [m for m in (fb.get('mots') or []) if isinstance(m, dict) and m.get('mot')][:3]
    for m in mots:
        db.execute("""
            INSERT INTO fr_vocab (user_email, word, meaning, learned_at) VALUES (?, ?, ?, ?)
            ON CONFLICT(user_email, word) DO UPDATE SET seen = seen + 1
        """, (user, str(m['mot'])[:60], str(m.get('sens', ''))[:200],
              datetime.now().isoformat()))

    modele = [m for m in (fb.get('modele') or []) if isinstance(m, dict)]
    stored = {
        'questions': q_results,
        'point_fort': str(fb.get('point_fort', '')),
        'priorite': str(fb.get('priorite', '')),
        'erreurs': [str(t) for t in (fb.get('erreurs') or [])][:6],
        'modele': modele, 'mots': mots,
        'ameliorations': _clean_improvements(fb.get('ameliorations')),
        'orthographe': _clean_spelling(fb.get('orthographe')),
    }
    db.execute("""
        INSERT INTO fr_attempts (exercise_id, attempt_no, answers, score, feedback, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (ex_id, attempt_no, json.dumps(answers, ensure_ascii=False), overall,
          json.dumps(stored, ensure_ascii=False), datetime.now().isoformat()))
    db.execute("UPDATE fr_exercises SET status = 'done', completed_at = ? WHERE id = ?",
               (datetime.now().isoformat(), ex_id))
    db.commit()

    unlocked = attempt_no == 2 or overall >= 0.85
    return {
        'attempt_no': attempt_no,
        'score': round(overall * 100),
        'questions': q_results,
        'point_fort': stored['point_fort'],
        'priorite': stored['priorite'],
        'mots': mots,
        'ameliorations': stored['ameliorations'],
        'orthographe': stored['orthographe'],
        'level_changes': level_changes,
        'can_retry': attempt_no == 1 and overall < 0.85,
        'modele': modele if unlocked else None,
        'bilan_due': _exercises_since_last_bilan(db, user) >= BILAN_EVERY,
    }


@bp.route('/api/fr/exercises/<int:ex_id>/reveal', methods=['POST'])
def api_reveal(ex_id):
    """Donne le corrige modele du dernier essai (l'eleve renonce a retenter)."""
    row = _db().execute("""
        SELECT a.feedback FROM fr_attempts a JOIN fr_exercises e ON e.id = a.exercise_id
        WHERE a.exercise_id = ? AND e.user_email = ? ORDER BY a.attempt_no DESC LIMIT 1
    """, (ex_id, auth.owner_email())).fetchone()
    if row is None:
        return jsonify({'error': "Corrige d'abord ta réponse."}), 404
    return jsonify({'modele': json.loads(row['feedback']).get('modele', [])})
