"""Tests de la connexion Google et de la liste blanche (Google simule).

Lancer depuis la racine du projet, sur une base jetable :
    python tests/test_auth.py
"""
import os
import sys
import tempfile
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(tempfile.mkdtemp())
os.makedirs('data')

os.environ.pop('REVIZIO_AUTH_DISABLED', None)
os.environ['REVIZIO_INSECURE_COOKIES'] = '1'
os.environ['GOOGLE_CLIENT_ID'] = 'test-client'
os.environ['GOOGLE_CLIENT_SECRET'] = 'test-secret'
os.environ['ALLOWED_EMAILS'] = 'Parent@Example.com, lucas@example.com'

import app as revizio  # noqa: E402
import auth  # noqa: E402

c = revizio.app.test_client()


def login_as(client, email):
    with client.session_transaction() as s:
        s['user'] = {'email': email, 'name': 'Test'}


def google_returns(info):
    return mock.patch.object(auth.oauth.google, 'authorize_access_token',
                             return_value={'userinfo': info})


def test_everything_is_locked():
    for path in ('/', '/francais/', '/francais/suivi', '/suivi', '/verbes-irreguliers/',
                 '/histoire-geo/'):
        r = c.get(path)
        assert r.status_code == 302 and '/login' in r.headers['Location'], path
    for path in ('/api/fr/overview', '/api/verbs', '/api/hg/themes'):
        assert c.get(path).status_code == 401, path
    assert c.post('/api/fr/next', json={}).status_code == 401
    assert c.post('/api/verbs/sessions', json={}).status_code == 401
    # les chemins publics restent ouverts
    assert c.get('/login').status_code == 200
    assert c.get('/api/health').status_code == 200
    assert c.get('/static/js/main.js').status_code == 200
    # la redirection garde la page demandee
    assert c.get('/francais/').headers['Location'].endswith('next=/francais/')


def test_whitelist_session():
    login_as(c, 'parent@example.com')
    assert c.get('/francais/').status_code == 200
    assert c.get('/api/fr/overview').status_code == 200
    # une adresse hors liste n'a aucun acces, meme avec une session signee
    other = revizio.app.test_client()
    login_as(other, 'intrus@example.com')
    assert other.get('/api/fr/overview').status_code == 401
    # retirer une adresse de la liste coupe l'acces en cours de session
    os.environ['ALLOWED_EMAILS'] = 'lucas@example.com'
    try:
        assert c.get('/api/fr/overview').status_code == 401
    finally:
        os.environ['ALLOWED_EMAILS'] = 'Parent@Example.com, lucas@example.com'


def test_google_callback():
    fresh = revizio.app.test_client()
    with google_returns({'email': 'Lucas@Example.com', 'email_verified': True, 'name': 'Lucas'}):
        r = fresh.get('/auth/callback')
    assert r.status_code == 302 and r.headers['Location'].endswith('/')
    assert fresh.get('/api/fr/overview').status_code == 200

    # compte Google valide mais hors liste blanche
    refused = revizio.app.test_client()
    with google_returns({'email': 'intrus@example.com', 'email_verified': True}):
        r = refused.get('/auth/callback')
    assert 'erreur=refuse' in r.headers['Location']
    assert refused.get('/api/fr/overview').status_code == 401

    # e-mail de la liste mais non verifie par Google
    unverified = revizio.app.test_client()
    with google_returns({'email': 'lucas@example.com', 'email_verified': False}):
        r = unverified.get('/auth/callback')
    assert 'erreur=refuse' in r.headers['Location']
    assert unverified.get('/api/fr/overview').status_code == 401

    # echec cote Google (etat invalide, annulation...)
    failed = revizio.app.test_client()
    with mock.patch.object(auth.oauth.google, 'authorize_access_token',
                           side_effect=auth.OAuthError(error='access_denied')):
        r = failed.get('/auth/callback')
    assert 'erreur=echec' in r.headers['Location']


def test_start_flow_and_next():
    cl = revizio.app.test_client()
    r = cl.get('/auth/google?next=/francais/')
    assert r.status_code == 302
    assert r.headers['Location'].startswith('https://accounts.google.com/')
    assert 'redirect_uri=https%3A%2F%2Frevizio.cdtechnology.fr%2Fauth%2Fcallback' in r.headers['Location']
    # le retour apres connexion est borne au site
    for evil in ('//evil.com', 'https://evil.com', '/\\evil.com', 'javascript:alert(1)'):
        assert auth.safe_next(evil) == '/', evil
    assert auth.safe_next('/francais/suivi?a=1') == '/francais/suivi?a=1'


def test_logout_and_not_configured():
    login_as(c, 'parent@example.com')
    assert c.get('/logout').status_code == 405  # POST uniquement
    assert c.post('/logout').status_code == 302
    assert c.get('/api/fr/overview').status_code == 401

    # sans identifiants Google : tout reste ferme, aucun bouton de connexion
    saved = os.environ.pop('GOOGLE_CLIENT_ID')
    try:
        page = revizio.app.test_client().get('/login').get_data(as_text=True)
        assert 'pas encore configurée' in page and 'Se connecter avec Google' not in page
        assert revizio.app.test_client().get('/francais/').status_code == 302
    finally:
        os.environ['GOOGLE_CLIENT_ID'] = saved

    # sans liste blanche : personne n'entre
    saved = os.environ.pop('ALLOWED_EMAILS')
    try:
        login_as(c, 'parent@example.com')
        assert c.get('/api/fr/overview').status_code == 401
    finally:
        os.environ['ALLOWED_EMAILS'] = saved


def test_session_key_not_hardcoded():
    assert revizio.app.secret_key != 'revizio-portal-secret-key'
    assert len(revizio.app.secret_key) >= 32
    assert os.stat('data/.secret_key').st_mode & 0o777 == 0o600


if __name__ == '__main__':
    test_everything_is_locked()
    test_whitelist_session()
    test_google_callback()
    test_start_flow_and_next()
    test_logout_and_not_configured()
    test_session_key_not_hardcoded()
    print('OK')
