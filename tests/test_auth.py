"""Tests de la connexion Google et de la gestion des utilisateurs (Google simule).

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
os.environ['ADMIN_EMAILS'] = 'Parent@Example.com'

import app as revizio  # noqa: E402
import auth  # noqa: E402


def new_client(email=None):
    cl = revizio.app.test_client()
    if email:
        with cl.session_transaction() as s:
            s['user'] = {'email': email}
    return cl


def csrf(cl):
    cl.get('/admin/utilisateurs')
    with cl.session_transaction() as s:
        return s.get('csrf', '')


def post_admin(cl, path, **form):
    return cl.post(path, data={'csrf': csrf(cl), **form})


def google_returns(info):
    return mock.patch.object(auth.oauth.google, 'authorize_access_token',
                             return_value={'userinfo': info})


def test_everything_is_locked():
    c = new_client()
    for path in ('/', '/francais/', '/francais/suivi', '/suivi', '/verbes-irreguliers/',
                 '/histoire-geo/', '/admin/utilisateurs'):
        r = c.get(path)
        assert r.status_code == 302 and '/login' in r.headers['Location'], path
    for path in ('/api/fr/overview', '/api/verbs', '/api/hg/themes'):
        assert c.get(path).status_code == 401, path
    assert c.post('/api/fr/next', json={}).status_code == 401
    assert c.post('/api/verbs/sessions', json={}).status_code == 401
    assert c.post('/admin/utilisateurs', data={'email': 'a@b.fr'}).status_code == 302
    # les chemins publics restent ouverts
    assert c.get('/login').status_code == 200
    assert c.get('/api/health').status_code == 200
    assert c.get('/static/js/main.js').status_code == 200
    assert c.get('/francais/').headers['Location'].endswith('next=/francais/')


def test_admin_bootstrap_and_access():
    admin = auth.get_user('parent@example.com')
    assert admin['role'] == 'admin' and admin['active']
    c = new_client('PARENT@example.com')
    assert c.get('/francais/').status_code == 200
    assert c.get('/api/fr/overview').status_code == 200
    assert 'Utilisateurs' in c.get('/').get_data(as_text=True)
    # un e-mail inconnu n'entre pas, meme avec une session signee
    other = new_client('intrus@example.com')
    assert other.get('/api/fr/overview').status_code == 401


def test_google_callback():
    ok = new_client()
    with google_returns({'email': 'Parent@Example.com', 'email_verified': True, 'name': 'Parent'}):
        r = ok.get('/auth/callback')
    assert r.status_code == 302 and r.headers['Location'].endswith('/')
    assert ok.get('/api/fr/overview').status_code == 200
    assert auth.get_user('parent@example.com')['last_login_at']

    refused = new_client()
    with google_returns({'email': 'intrus@example.com', 'email_verified': True}):
        r = refused.get('/auth/callback')
    assert 'erreur=refuse' in r.headers['Location']
    assert refused.get('/api/fr/overview').status_code == 401

    unverified = new_client()
    with google_returns({'email': 'parent@example.com', 'email_verified': False}):
        r = unverified.get('/auth/callback')
    assert 'erreur=refuse' in r.headers['Location']
    assert unverified.get('/api/fr/overview').status_code == 401

    failed = new_client()
    with mock.patch.object(auth.oauth.google, 'authorize_access_token',
                           side_effect=auth.OAuthError(error='access_denied')):
        r = failed.get('/auth/callback')
    assert 'erreur=echec' in r.headers['Location']


def test_start_flow_pkce_and_next():
    r = new_client().get('/auth/google?next=/francais/')
    loc = r.headers['Location']
    assert r.status_code == 302 and loc.startswith('https://accounts.google.com/')
    assert 'redirect_uri=https%3A%2F%2Frevizio.cdtechnology.fr%2Fauth%2Fcallback' in loc
    assert 'code_challenge=' in loc and 'code_challenge_method=S256' in loc
    for evil in ('//evil.com', 'https://evil.com', '/\\evil.com', 'javascript:alert(1)'):
        assert auth.safe_next(evil) == '/', evil
    assert auth.safe_next('/francais/suivi?a=1') == '/francais/suivi?a=1'


def test_user_management():
    admin = new_client('parent@example.com')

    # ajout : jeton CSRF obligatoire, e-mail valide, pas de doublon
    assert admin.post('/admin/utilisateurs', data={'email': 'lucas@example.com'}).status_code == 400
    assert post_admin(admin, '/admin/utilisateurs', email='pas-un-email', role='user').status_code == 302
    assert auth.get_user('pas-un-email') is None
    assert post_admin(admin, '/admin/utilisateurs', email='Lucas@Example.com', role='user').status_code == 302
    assert auth.get_user('lucas@example.com')['role'] == 'user'
    post_admin(admin, '/admin/utilisateurs', email='lucas@example.com', role='admin')
    assert auth.get_user('lucas@example.com')['role'] == 'user'  # doublon ignore

    # un simple utilisateur entre, mais n'administre rien
    lucas = new_client('lucas@example.com')
    assert lucas.get('/francais/').status_code == 200
    assert lucas.get('/admin/utilisateurs').status_code == 403
    assert 'Utilisateurs' not in lucas.get('/').get_data(as_text=True)
    assert lucas.post('/admin/utilisateurs/modifier',
                      data={'email': 'lucas@example.com', 'action': 'promouvoir'}).status_code == 403
    assert auth.get_user('lucas@example.com')['role'] == 'user'

    # desactiver coupe aussitot la session en cours ; reactiver la rend
    post_admin(admin, '/admin/utilisateurs/modifier', email='lucas@example.com', action='desactiver')
    assert lucas.get('/api/fr/overview').status_code == 401
    refused = new_client()
    with google_returns({'email': 'lucas@example.com', 'email_verified': True}):
        assert 'erreur=refuse' in refused.get('/auth/callback').headers['Location']
    post_admin(admin, '/admin/utilisateurs/modifier', email='lucas@example.com', action='reactiver')
    assert lucas.get('/api/fr/overview').status_code == 200

    # on ne peut ni se retirer soi-meme ni retirer le dernier administrateur
    post_admin(admin, '/admin/utilisateurs/modifier', email='parent@example.com', action='desactiver')
    post_admin(admin, '/admin/utilisateurs/modifier', email='parent@example.com', action='retrograder')
    assert auth.get_user('parent@example.com')['role'] == 'admin'
    assert auth.get_user('parent@example.com')['active']

    # avec un second admin, on peut retirer le premier (mais pas soi-meme)
    post_admin(admin, '/admin/utilisateurs/modifier', email='lucas@example.com', action='promouvoir')
    assert auth.get_user('lucas@example.com')['role'] == 'admin'
    post_admin(lucas, '/admin/utilisateurs/modifier', email='parent@example.com', action='retrograder')
    assert auth.get_user('parent@example.com')['role'] == 'user'
    post_admin(lucas, '/admin/utilisateurs/modifier', email='lucas@example.com', action='retrograder')
    assert auth.get_user('lucas@example.com')['role'] == 'admin'

    # action inconnue ou compte inexistant
    assert post_admin(lucas, '/admin/utilisateurs/modifier', email='x@y.fr', action='desactiver').status_code == 400
    assert post_admin(lucas, '/admin/utilisateurs/modifier', email='lucas@example.com', action='supprimer').status_code == 400

    # ADMIN_EMAILS repose l'administrateur de depart au demarrage (anti-verrouillage)
    auth.init_db('data/app.db')
    assert auth.get_user('parent@example.com')['role'] == 'admin'


def test_logout_and_not_configured():
    c = new_client('parent@example.com')
    assert c.get('/logout').status_code == 405  # POST uniquement
    assert c.post('/logout').status_code == 302
    assert c.get('/api/fr/overview').status_code == 401

    saved = os.environ.pop('GOOGLE_CLIENT_ID')
    try:
        page = new_client().get('/login').get_data(as_text=True)
        assert 'pas encore configurée' in page and 'Se connecter avec Google' not in page
        assert new_client().get('/francais/').status_code == 302
    finally:
        os.environ['GOOGLE_CLIENT_ID'] = saved


def test_session_key_not_hardcoded():
    assert revizio.app.secret_key != 'revizio-portal-secret-key'
    assert len(revizio.app.secret_key) >= 32
    assert os.stat('data/.secret_key').st_mode & 0o777 == 0o600


if __name__ == '__main__':
    test_everything_is_locked()
    test_admin_bootstrap_and_access()
    test_google_callback()
    test_start_flow_pkce_and_next()
    test_user_management()
    test_logout_and_not_configured()
    test_session_key_not_hardcoded()
    print('OK')
