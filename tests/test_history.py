"""Tests de la migration de l'historique vers Lucas et de l'isolation par utilisateur.

Lancer depuis la racine du projet, sur une base jetable :
    python tests/test_history.py
"""
import json
import os
import sqlite3
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(tempfile.mkdtemp())
os.makedirs('data')

os.environ.pop('REVIZIO_AUTH_DISABLED', None)
os.environ['REVIZIO_INSECURE_COOKIES'] = '1'
os.environ['GOOGLE_CLIENT_ID'] = 'test-client'
os.environ['GOOGLE_CLIENT_SECRET'] = 'test-secret'
os.environ['ADMIN_EMAILS'] = 'parent@example.com'

LUCAS = 'lucas.decroi@gmail.com'

# --- 1. Base "d'avant les comptes" : ancien schema commun, avec de l'historique reel
from setup import init_database  # noqa: E402

init_database()  # tables d'origine (sessions sans proprietaire, verbes, themes HG...)
db = sqlite3.connect('data/app.db')
db.executescript("""
    CREATE TABLE fr_skill_state (skill TEXT PRIMARY KEY, mastery REAL NOT NULL DEFAULT 0.3,
        level INTEGER NOT NULL DEFAULT 2, attempts INTEGER NOT NULL DEFAULT 0,
        streak_good INTEGER NOT NULL DEFAULT 0, streak_bad INTEGER NOT NULL DEFAULT 0,
        remediate INTEGER NOT NULL DEFAULT 0, last_at TEXT, next_review TEXT);
    CREATE TABLE fr_exercises (id INTEGER PRIMARY KEY AUTOINCREMENT, skill TEXT NOT NULL,
        level INTEGER NOT NULL, kind TEXT NOT NULL, passage_id TEXT, skills TEXT NOT NULL,
        payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL, completed_at TEXT);
    CREATE TABLE fr_profile (id INTEGER PRIMARY KEY CHECK (id = 1), summary TEXT NOT NULL,
        updated_at TEXT NOT NULL);
    CREATE TABLE fr_vocab (word TEXT PRIMARY KEY, meaning TEXT NOT NULL,
        seen INTEGER NOT NULL DEFAULT 1, learned_at TEXT NOT NULL);
    CREATE TABLE fr_jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL,
        result TEXT, error TEXT, created_at TEXT NOT NULL);
    INSERT INTO fr_skill_state (skill, mastery, level, attempts) VALUES ('effet', 0.66, 4, 7);
    INSERT INTO fr_profile (id, summary, updated_at) VALUES (1, 'Profil de Lucas', '2026-10-01');
    INSERT INTO fr_vocab (word, meaning, learned_at) VALUES ('indolent', 'mou', '2026-10-01');
    INSERT INTO fr_exercises (skill, level, kind, skills, payload, status, created_at)
        VALUES ('effet', 4, 'atelier', '["effet"]', '{"titre":"Ancien"}', 'done', '2026-10-01');
    INSERT INTO sessions (tool_type, completed_at, total_verbs, total_correct, total_errors, rounds)
        VALUES ('irregular-verbs', '2026-10-02', 10, 8, 2, 1);
    INSERT INTO sessions (tool_type, completed_at, total_verbs, total_correct, total_errors, rounds)
        VALUES ('histoire-geo', '2026-10-03', 10, 6, 4, 1);
    INSERT INTO session_errors (session_id, verb_id, error_count) VALUES (1, 1, 2);
""")
db.commit()
db.close()

import app as revizio  # noqa: E402  (la migration s'execute a l'import)
import auth  # noqa: E402
import francais  # noqa: E402
import migrations  # noqa: E402


def rows(sql, *args):
    conn = sqlite3.connect('data/app.db')
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


def client(email):
    cl = revizio.app.test_client()
    with cl.session_transaction() as s:
        s['user'] = {'email': email}
    return cl


def test_history_goes_to_lucas():
    assert [r['user_email'] for r in rows("SELECT user_email FROM sessions")] == [LUCAS, LUCAS]
    # erreurs et reponses suivent leur session : rien a deplacer
    assert rows("SELECT COUNT(*) AS c FROM session_errors WHERE session_id = 1")[0]['c'] == 1
    state = rows("SELECT * FROM fr_skill_state WHERE user_email = ?", LUCAS)
    assert [(r['skill'], r['level'], r['attempts']) for r in state] == [('effet', 4, 7)]
    assert rows("SELECT summary FROM fr_profile WHERE user_email = ?", LUCAS)[0]['summary'] == 'Profil de Lucas'
    assert rows("SELECT word FROM fr_vocab WHERE user_email = ?", LUCAS)[0]['word'] == 'indolent'
    assert rows("SELECT user_email FROM fr_exercises")[0]['user_email'] == LUCAS
    # Lucas existe comme utilisateur et peut se connecter des sa premiere visite
    lucas = auth.get_user(LUCAS)
    assert lucas['role'] == 'user' and lucas['active']
    # les anciennes tables ne trainent pas
    assert not rows("SELECT name FROM sqlite_master WHERE name LIKE '%_old'")
    # idempotent : relancer ne change rien
    assert migrations.attach_history('data/app.db', LUCAS) == 0
    francais.ensure_tables('data/app.db', LUCAS)
    assert len(rows("SELECT * FROM fr_skill_state")) == 1


def test_lucas_sees_his_history():
    c = client(LUCAS)
    page = c.get('/verbes-irreguliers/suivi').get_data(as_text=True)
    assert '80' in page  # 8 bonnes reponses sur 10
    fr = c.get('/api/fr/overview').get_json()
    effet = [s for a in fr['axes'] for s in a['skills'] if s['id'] == 'effet'][0]
    assert effet['level'] == 4 and effet['attempts'] == 7 and fr['profile'] == 'Profil de Lucas'


def test_other_user_starts_clean_and_is_isolated():
    parent = client('parent@example.com')
    fr = parent.get('/api/fr/overview').get_json()
    effet = [s for a in fr['axes'] for s in a['skills'] if s['id'] == 'effet'][0]
    assert effet['level'] == 2 and effet['attempts'] == 0
    assert fr['profile'] == francais.GENERIC_PROFILE  # pas le profil de Lucas
    stats = rows("SELECT COUNT(*) AS c FROM sessions WHERE user_email = 'parent@example.com'")[0]['c']
    assert stats == 0

    # verbes : les sessions du parent sont a lui, celles de Lucas inaccessibles
    sid = parent.post('/api/verbs/sessions', json={'mode': 'random', 'total_verbs': 5}).get_json()['id']
    assert rows("SELECT user_email FROM sessions WHERE id = ?", sid)[0]['user_email'] == 'parent@example.com'
    lucas = client(LUCAS)
    # Lucas ne peut ni terminer ni mettre en pause la session du parent
    r = lucas.put(f'/api/verbs/sessions/{sid}', json={'total_correct': 5, 'errors': [{'verb_id': 2, 'count': 9}]})
    assert r.status_code == 404
    assert not rows("SELECT * FROM session_errors WHERE verb_id = 2")
    lucas.put(f'/api/verbs/sessions/{sid}/pause', json={'state': {'x': 1}})
    assert rows("SELECT pause_state FROM sessions WHERE id = ?", sid)[0]['pause_state'] is None
    # et inversement, le parent ne peut pas toucher a l'historique de Lucas
    assert parent.put('/api/verbs/sessions/1', json={'total_correct': 0}).status_code == 404
    assert rows("SELECT total_correct FROM sessions WHERE id = 1")[0]['total_correct'] == 8
    # la reprise de session n'expose que les siennes
    parent.put(f'/api/verbs/sessions/{sid}/pause', json={'state': {'x': 1}})
    assert parent.get('/api/verbs/sessions/pending').get_json()['id'] == sid
    assert lucas.get('/api/verbs/sessions/pending').get_json() in (None, {}) or \
        lucas.get('/api/verbs/sessions/pending').get_json().get('id') != sid

    # histoire-geo : correction d'une session d'un autre refusee
    r = parent.post('/api/hg/sessions/2/correct', json={'answers': []})
    assert r.status_code == 404


def test_francais_isolation_and_admin_view():
    francais._deps['ask_proxy'] = lambda system, user_content, **k: (
        {'titre': 'T', 'consigne': 'C', 'passage': {'source': 'S', 'texte': 'Texte.'},
         'questions': [{'enonce': 'Q', 'attendu': 'A'}]})
    import time

    def post(cl, path, body):
        r = cl.post(path, json=body)
        data = r.get_json()
        if r.status_code != 202:
            return r.status_code, data
        for _ in range(100):
            st = cl.get(f"/api/fr/jobs/{data['job']}").get_json()
            if st['status'] != 'running':
                return (200, st['result']) if st['status'] == 'done' else (502, st)
            time.sleep(0.05)

    parent, lucas = client('parent@example.com'), client(LUCAS)
    code, ex = post(parent, '/api/fr/next', {'skill': 'plan', 'fresh': True})
    assert code == 200
    job = parent.post('/api/fr/next', json={'skill': 'plan', 'fresh': True}).get_json()['job']
    # Lucas n'accede ni a l'exercice, ni a la tache, ni au corrige du parent
    assert lucas.post(f"/api/fr/exercises/{ex['id']}/correct", json={'answers': {'1': 'x'}}).status_code == 404
    assert lucas.get(f'/api/fr/jobs/{job}').status_code == 404
    assert lucas.post(f"/api/fr/exercises/{ex['id']}/reveal").status_code == 404
    # l'exercice en attente du parent n'est pas propose a Lucas
    assert lucas.post('/api/fr/next', json={}).status_code in (202, 200)
    assert rows("SELECT COUNT(*) AS c FROM fr_exercises WHERE user_email = ?", LUCAS)[0]['c'] >= 1

    # un admin consulte le suivi de Lucas avec ?user= ; un simple utilisateur non
    page = parent.get(f'/francais/suivi?user={LUCAS}').get_data(as_text=True)
    assert 'Profil de Lucas' in page and 'selected' in page
    assert 'Profil de Lucas' not in parent.get('/francais/suivi').get_data(as_text=True)
    other = client(LUCAS).get('/francais/suivi?user=parent@example.com').get_data(as_text=True)
    assert 'Profil de Lucas' in other  # ?user= ignore : il voit toujours le sien
    assert 'picker-user' not in other


if __name__ == '__main__':
    test_history_goes_to_lucas()
    test_lucas_sees_his_history()
    test_other_user_starts_clean_and_is_isolated()
    test_francais_isolation_and_admin_view()
    print('OK')
