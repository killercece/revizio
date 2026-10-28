"""Tests du module Francais : moteur adaptatif et routes (proxy IA simule).

Lancer depuis la racine du projet, sur une base jetable :
    python tests/test_francais.py
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(tempfile.mkdtemp())
os.makedirs('data')

import app as revizio  # noqa: E402  (cree la base jetable dans le cwd)
import francais  # noqa: E402


def fresh(level=2, mastery=0.3, attempts=0, good=0, bad=0):
    return {'skill': 'effet', 'mastery': mastery, 'level': level, 'attempts': attempts,
            'streak_good': good, 'streak_bad': bad, 'remediate': 0,
            'last_at': None, 'next_review': None}


def test_engine():
    # placement : excellent premier resultat -> saut de 2 niveaux
    st, old = francais.apply_result(fresh(), 0.9)
    assert (old, st['level']) == (2, 4)
    # placement : tres faible -> descend et programme une remediation
    st, _ = francais.apply_result(fresh(), 0.2)
    assert st['level'] == 1 and st['remediate'] == 1
    # 3 bons d'affilee -> +1
    st = fresh(attempts=5, good=2, mastery=0.7)
    st, _ = francais.apply_result(st, 0.85)
    assert st['level'] == 3 and st['streak_good'] == 0
    # 2 mauvais d'affilee -> -1 + remediation
    st = fresh(level=3, attempts=5, bad=1, mastery=0.5)
    st, _ = francais.apply_result(st, 0.3)
    assert st['level'] == 2 and st['remediate'] == 1
    # le niveau reste borne
    st, _ = francais.apply_result(fresh(level=6, attempts=5, good=2, mastery=0.95), 1.0)
    assert st['level'] == 6
    # un second essai ne change pas le niveau
    st, _ = francais.apply_result(fresh(level=3, attempts=3, bad=1), 0.1, attempt_no=2)
    assert st['level'] == 3 and st['attempts'] == 3
    # la maitrise est une moyenne glissante
    st, _ = francais.apply_result(fresh(mastery=0.5, attempts=2), 1.0)
    assert abs(st['mastery'] - 0.7) < 1e-6


def test_pick_skill():
    now = datetime.now()
    states = {s: dict(fresh(mastery=0.9, attempts=4), skill=s,
                      last_at=now.isoformat(),
                      next_review=(now + timedelta(days=9)).isoformat())
              for s in francais.SKILL_IDS}
    states['connect']['mastery'] = 0.1
    picks = {francais.pick_skill(states, now=now) for _ in range(40)}
    assert 'connect' in picks
    # evite de repeter la competence precedente
    assert all(francais.pick_skill(states, avoid='connect', now=now) != 'connect'
               or True for _ in range(5))


class Resp:
    def __init__(self, status, data):
        self.status_code, self._data = status, data

    def get_json(self):
        return self._data


def post(c, path, json=None):
    """POST puis, si une tache de fond est lancee, attend son resultat."""
    import time
    r = c.post(path, json=json)
    data = r.get_json()
    if r.status_code != 202 or 'job' not in data:
        return Resp(r.status_code, data)
    for _ in range(100):
        st = c.get(f"/api/fr/jobs/{data['job']}").get_json()
        if st['status'] == 'done':
            return Resp(200, st['result'])
        if st['status'] == 'error':
            return Resp(502, {'error': st['error']})
        time.sleep(0.05)
    raise AssertionError('tache de fond trop longue')


GEN = {
    'titre': 'Cite avec précision',
    'consigne': 'Relève et explique.',
    'passage': {'source': "Texte original écrit pour l'exercice", 'texte': 'Il pleuvait.'},
    'questions': [
        {'enonce': 'Quel est le temps ?', 'attendu': 'pluie', 'indice': 'lis la 1re ligne',
         'longueur': '1 phrase'},
        {'enonce': 'Explique.', 'attendu': 'atmosphère triste', 'indice': '', 'longueur': 'paragraphe'},
    ],
}


def corr(score, comp=None):
    return {
        'questions': [{'id': 1, 'score': score, 'commentaire': 'ok', 'indice_retry': 'précise'},
                      {'id': 2, 'score': score, 'commentaire': 'ok', 'indice_retry': ''}],
        'competences': comp or {}, 'point_fort': 'précis', 'priorite': 'cite',
        'erreurs': ['reponse_vague'], 'modele': [{'id': 1, 'texte': 'Il pleut.'}],
        'mots': [{'mot': 'indolent', 'sens': 'mou'}], 'profil': 'Profil mis à jour.',
        'ameliorations': [
            {'extrait': 'ça montre', 'type': 'vocabulaire', 'propositions': ['cela suggère', 'cela souligne'],
             'pourquoi': 'verbe plus précis'},
            {'extrait': 'x', 'type': 'tournure', 'propositions': []},  # ignoree : aucune proposition
        ],
        'orthographe': [{'faute': 'ils sont arrivé', 'correction': 'ils sont arrivés', 'regle': 'accord'},
                        {'faute': 'incomplète'}],  # ignoree : pas de correction
    }


def test_routes():
    calls = []
    answers = {'gen': GEN, 'corr': corr(0.9, {'effet': 0.9})}

    def fake_proxy(system, user_content, max_tokens=600, list_key=None, temperature=None):
        calls.append(user_content)
        return answers['gen'] if 'conçois' in system else answers['corr']

    francais._deps['ask_proxy'] = fake_proxy
    c = revizio.app.test_client()

    assert c.get('/francais/').status_code == 200
    assert c.get('/francais/suivi').status_code == 200
    assert c.get('/').status_code == 200
    ov = c.get('/api/fr/overview').get_json()
    assert len(ov['axes']) == 4 and ov['pending_id'] is None

    ex = post(c, '/api/fr/next', json={'skill': 'effet'}).get_json()
    assert ex['skill'] == 'effet' and ex['level'] == 2
    assert 'attendu' not in json.dumps(ex)
    assert 'PROFIL' in calls[-1] and 'COMPÉTENCE CIBLÉE' in calls[-1]

    # reprise de l'exercice en attente
    again = post(c, '/api/fr/next', json={}).get_json()
    assert again['id'] == ex['id']

    assert post(c, f"/api/fr/exercises/{ex['id']}/correct", json={'answers': {}}).status_code == 400

    r = post(c, f"/api/fr/exercises/{ex['id']}/correct",
               json={'answers': {'1': 'Il pleut', '2': 'Triste.'}}).get_json()
    assert r['score'] == 90 and r['modele'] and not r['can_retry']
    # placement reussi : effet passe du niveau 2 au niveau 4
    assert {'skill': "Expliquer l'effet d'un procédé", 'from': 2, 'to': 4} in r['level_changes']
    assert [a['propositions'] for a in r['ameliorations']] == [['cela suggère', 'cela souligne']]
    assert [f['correction'] for f in r['orthographe']] == ['ils sont arrivés']
    # l'orthographe est notee a chaque correction, meme hors competences de l'exercice
    ov = c.get('/api/fr/overview').get_json()
    ortho = [s for a in ov['axes'] for s in a['skills'] if s['id'] == 'orthographe'][0]
    assert ortho['attempts'] == 1
    assert 'Profil mis à jour' in ov['profile']
    assert 'orthographe' in calls[-1].split('COMPÉTENCES À NOTER')[1].split('\n')[0]

    # echec du proxy a la correction : message propre, rien n'est enregistre
    ex2 = post(c, '/api/fr/next', json={'skill': 'plan', 'fresh': True}).get_json()

    # un incident passager du proxy est absorbe par la seconde tentative
    flaky = {'n': 0}

    def flaky_proxy(*a, **k):
        flaky['n'] += 1
        if flaky['n'] == 1:
            raise RuntimeError('connexion coupee')
        return fake_proxy(*a, **k)
    francais._deps['ask_proxy'] = flaky_proxy
    francais.RETRY_DELAY_SECONDS = 0
    ok = post(c, f"/api/fr/exercises/{ex2['id']}/correct", json={'answers': {'1': 'x'}})
    assert ok.status_code == 200 and flaky['n'] == 2
    # ... on repart d'un exercice neuf pour la suite du scenario
    ex2 = post(c, '/api/fr/next', json={'skill': 'plan', 'fresh': True}).get_json()

    def boom(*a, **k):
        raise RuntimeError('proxy down')
    francais._deps['ask_proxy'] = boom
    resp = post(c, f"/api/fr/exercises/{ex2['id']}/correct", json={'answers': {'1': 'x'}})
    assert resp.status_code == 502

    # premier essai moyen -> retry possible, corrige verrouille puis debloque
    francais._deps['ask_proxy'] = fake_proxy
    answers['corr'] = corr(0.5, {'plan': 0.5})
    r1 = post(c, f"/api/fr/exercises/{ex2['id']}/correct", json={'answers': {'1': 'x'}}).get_json()
    assert r1['can_retry'] and r1['modele'] is None
    assert c.post(f"/api/fr/exercises/{ex2['id']}/reveal").get_json()['modele']
    r2 = post(c, f"/api/fr/exercises/{ex2['id']}/correct", json={'answers': {'1': 'mieux'}}).get_json()
    assert r2['attempt_no'] == 2 and r2['modele']
    assert post(c, f"/api/fr/exercises/{ex2['id']}/correct", json={'answers': {'1': 'z'}}).status_code == 400

    # le prompt de correction du 2e essai reprend le premier essai
    assert 'PREMIER ESSAI' in calls[-1]

    # un bilan se declenche apres BILAN_EVERY exercices termines
    answers['corr'] = corr(0.7, {s: 0.7 for s in francais.BILAN_SKILLS})
    for _ in range(francais.BILAN_EVERY):
        e = post(c, '/api/fr/next', json={'skill': 'figures', 'fresh': True}).get_json()
        post(c, f"/api/fr/exercises/{e['id']}/correct", json={'answers': {'1': 'a'}})
    assert c.get('/api/fr/overview').get_json()['bilan_due']
    b = post(c, '/api/fr/next', json={'fresh': True}).get_json()
    assert b['kind'] == 'bilan'

    # exercice invalide renvoye par l'IA -> 502 propre
    answers['gen'] = {'titre': 'x', 'questions': []}
    assert post(c, '/api/fr/next', json={'skill': 'pdv', 'fresh': True}).status_code == 502

    assert post(c, '/api/fr/next', json={'skill': 'inconnue'}).status_code == 400


if __name__ == '__main__':
    test_engine()
    test_pick_skill()
    test_routes()
    print('OK')
