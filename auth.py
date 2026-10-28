"""
Authentification de Revizio : connexion Google (OpenID Connect) et liste blanche.

- Tout est protege par defaut (pages et API), sauf /login, /auth/*, /static/* et
  /api/health ; sans identifiants Google configures, rien n'est accessible
  (le blocage est la valeur par defaut, jamais l'ouverture).
- Seules les adresses de ALLOWED_EMAILS (virgules) peuvent entrer, et leur
  e-mail doit etre verifie par Google. La liste est relue a chaque requete :
  retirer une adresse coupe aussitot l'acces de sa session.
- Configuration par variables d'environnement (PyDeploy) :
  GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, ALLOWED_EMAILS, PUBLIC_URL (optionnelle),
  SECRET_KEY (optionnelle : a defaut, une cle aleatoire est creee dans data/).
- REVIZIO_AUTH_DISABLED=1 desactive la protection, pour le developpement local
  et les tests uniquement.
"""

import logging
import os
import secrets
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

from authlib.integrations.base_client import OAuthError
from authlib.integrations.flask_client import OAuth
from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

bp = Blueprint('auth', __name__)
logger = logging.getLogger(__name__)
oauth = OAuth()

DEFAULT_PUBLIC_URL = 'https://revizio.cdtechnology.fr'
GOOGLE_METADATA_URL = 'https://accounts.google.com/.well-known/openid-configuration'
SESSION_DAYS = 30

LOGIN_ERRORS = {
    'refuse': "Ce compte Google n'est pas autorisé à utiliser Revizio.",
    'echec': "La connexion avec Google a échoué. Réessaie.",
    'non_configure': "La connexion Google n'est pas encore configurée.",
}


def load_secret_key(data_dir):
    """Cle de signature des sessions : variable SECRET_KEY, sinon fichier persistant."""
    env = os.environ.get('SECRET_KEY')
    if env:
        return env
    path = Path(data_dir) / '.secret_key'
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_hex(32))
        path.chmod(0o600)
    return path.read_text().strip()


def allowed_emails():
    raw = os.environ.get('ALLOWED_EMAILS', '')
    return {e.strip().lower() for e in raw.split(',') if e.strip()}


def google_configured():
    return bool(os.environ.get('GOOGLE_CLIENT_ID') and os.environ.get('GOOGLE_CLIENT_SECRET'))


def safe_next(target):
    """N'accepte qu'un chemin relatif du site (pas d'URL externe, pas de //)."""
    if not target or not target.startswith('/') or target.startswith('//') or '\\' in target:
        return '/'
    parsed = urlparse(target)
    return target if not parsed.scheme and not parsed.netloc else '/'


def current_email():
    user = session.get('user') or {}
    email = str(user.get('email', '')).lower()
    return email if email and email in allowed_emails() else None


def init_app(app, data_dir):
    """Branche l'authentification : cle de session, cookies, Google, garde globale."""
    app.secret_key = load_secret_key(data_dir)
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        # Le site est servi en HTTPS derriere Cloudflare ; en local on laisse http
        SESSION_COOKIE_SECURE=os.environ.get('REVIZIO_INSECURE_COOKIES') != '1',
        PERMANENT_SESSION_LIFETIME=timedelta(days=SESSION_DAYS),
    )
    oauth.init_app(app)
    oauth.register(
        name='google',
        client_id=os.environ.get('GOOGLE_CLIENT_ID', ''),
        client_secret=os.environ.get('GOOGLE_CLIENT_SECRET', ''),
        server_metadata_url=GOOGLE_METADATA_URL,
        client_kwargs={'scope': 'openid email profile'},
    )
    app.register_blueprint(bp)
    app.before_request(guard)

    @app.context_processor
    def inject_user():
        return {'current_user': current_email()}


def guard():
    """Refuse toute requete sans session valide, sauf les chemins publics."""
    if os.environ.get('REVIZIO_AUTH_DISABLED') == '1':
        return None
    path = request.path
    if (path in ('/login', '/api/health') or path.startswith('/auth/')
            or path.startswith('/static/')):
        return None
    if current_email():
        return None
    if path.startswith('/api/'):
        return jsonify({'error': 'Authentification requise'}), 401
    return redirect(url_for('auth.login', next=request.full_path.rstrip('?')))


@bp.route('/login')
def login():
    if current_email():
        return redirect(safe_next(request.args.get('next')))
    error = LOGIN_ERRORS.get(request.args.get('erreur', ''))
    if not google_configured() and not error:
        error = LOGIN_ERRORS['non_configure']
    return render_template('login.html', error=error, configured=google_configured(),
                           next=safe_next(request.args.get('next')))


@bp.route('/auth/google')
def auth_google():
    if not google_configured():
        return redirect(url_for('auth.login', erreur='non_configure'))
    session['next'] = safe_next(request.args.get('next'))
    public_url = os.environ.get('PUBLIC_URL', DEFAULT_PUBLIC_URL).rstrip('/')
    return oauth.google.authorize_redirect(f'{public_url}/auth/callback',
                                           prompt='select_account')


@bp.route('/auth/callback')
def auth_callback():
    try:
        token = oauth.google.authorize_access_token()
    except OAuthError as e:
        logger.warning(f"Connexion Google echouee : {e.error}")
        return redirect(url_for('auth.login', erreur='echec'))

    info = token.get('userinfo') or {}
    email = str(info.get('email', '')).lower()
    if not email or info.get('email_verified') is not True or email not in allowed_emails():
        logger.warning(f"Connexion refusee pour {email or '(sans e-mail)'}")
        session.clear()
        return redirect(url_for('auth.login', erreur='refuse'))

    target = safe_next(session.get('next'))
    session.clear()
    session['user'] = {'email': email, 'name': str(info.get('name', ''))}
    session.permanent = True
    logger.info(f"Connexion de {email}")
    return redirect(target)


@bp.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('auth.login'))
