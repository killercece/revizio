"""
Authentification de Revizio : connexion Google (OpenID Connect avec PKCE) et
gestion des utilisateurs, sur le modele de cdt-hr.

- Tout est protege par defaut (pages et API), sauf /login, /auth/*, /static/* et
  /api/health ; sans identifiants Google configures, rien n'est accessible
  (le blocage est la valeur par defaut, jamais l'ouverture).
- Les utilisateurs vivent en base (table auth_users) avec un role : `admin`
  (gere les utilisateurs) ou `user`. Seul un utilisateur actif dont l'e-mail est
  verifie par Google peut entrer. Son statut est relu a chaque requete :
  desactiver un compte coupe aussitot sa session.
- Les administrateurs de depart viennent de ADMIN_EMAILS (virgules) : ils sont
  recrees actifs a chaque demarrage, ce qui evite de se verrouiller dehors.
  Les autres comptes s'ajoutent depuis /admin/utilisateurs.
- Variables d'environnement (PyDeploy) : GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET,
  ADMIN_EMAILS, PUBLIC_URL (optionnelle), SECRET_KEY (optionnelle : a defaut,
  une cle aleatoire est creee dans data/).
- REVIZIO_AUTH_DISABLED=1 desactive la protection, pour le developpement local
  et les tests uniquement.
"""

import hmac
import logging
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from authlib.integrations.base_client import OAuthError
from authlib.integrations.flask_client import OAuth
from flask import (Blueprint, abort, flash, g, jsonify, redirect, render_template,
                   request, session, url_for)

bp = Blueprint('auth', __name__)
logger = logging.getLogger(__name__)
oauth = OAuth()

DEFAULT_PUBLIC_URL = 'https://revizio.cdtechnology.fr'
GOOGLE_METADATA_URL = 'https://accounts.google.com/.well-known/openid-configuration'
SESSION_DAYS = 30
ROLES = ('admin', 'user')
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

# Proprietaire de l'historique cree avant l'arrivee des comptes (voir migrations.py)
LEGACY_OWNER = os.environ.get('LEGACY_OWNER_EMAIL', 'lucas.decroi@gmail.com').strip().lower()
# Utilisateur fictif quand la protection est coupee (developpement local, tests)
DEV_OWNER = 'dev@local'

_state = {'db_path': None}

LOGIN_ERRORS = {
    'refuse': "Ce compte Google n'est pas autorisé à utiliser Revizio.",
    'echec': "La connexion avec Google a échoué. Réessaie.",
    'non_configure': "La connexion Google n'est pas encore configurée.",
}


# === CONFIGURATION ===

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


def admin_emails():
    raw = os.environ.get('ADMIN_EMAILS', '')
    return [e.strip().lower() for e in raw.split(',') if e.strip()]


def google_configured():
    return bool(os.environ.get('GOOGLE_CLIENT_ID') and os.environ.get('GOOGLE_CLIENT_SECRET'))


def safe_next(target):
    """N'accepte qu'un chemin relatif du site (pas d'URL externe, pas de //)."""
    if not target or not target.startswith('/') or target.startswith('//') or '\\' in target:
        return '/'
    parsed = urlparse(target)
    return target if not parsed.scheme and not parsed.netloc else '/'


# === UTILISATEURS (SQLite) ===

def _conn():
    conn = sqlite3.connect(_state['db_path'], timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path):
    """Cree la table des utilisateurs et (re)pose les administrateurs de depart."""
    _state['db_path'] = db_path
    conn = _conn()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS auth_users (
                email TEXT PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')),
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                last_login_at TEXT,
                added_by TEXT
            )
        """)
        now = datetime.now().isoformat()
        # Le proprietaire de l'historique peut se connecter des sa premiere visite
        conn.execute("INSERT OR IGNORE INTO auth_users (email, role, active, created_at, added_by) "
                     "VALUES (?, 'user', 1, ?, 'historique')", (LEGACY_OWNER, now))
        for email in admin_emails():
            conn.execute("""
                INSERT INTO auth_users (email, role, active, created_at, added_by)
                VALUES (?, 'admin', 1, ?, 'ADMIN_EMAILS')
                ON CONFLICT(email) DO UPDATE SET role = 'admin', active = 1
            """, (email, now))
        conn.commit()
    finally:
        conn.close()


def get_user(email):
    conn = _conn()
    try:
        row = conn.execute("SELECT * FROM auth_users WHERE email = ?",
                           (email.lower(),)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_users():
    conn = _conn()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM auth_users ORDER BY active DESC, role, email")]
    finally:
        conn.close()


def current_user():
    """Utilisateur actif de la session, relu en base a chaque requete (mis en cache
    pour la requete), ou None."""
    if 'auth_user' not in g:
        user = None
        email = str((session.get('user') or {}).get('email', '')).lower()
        if email:
            found = get_user(email)
            if found and found['active']:
                user = found
        g.auth_user = user
    return g.auth_user


def owner_email():
    """Adresse a laquelle rattacher les donnees de la requete courante."""
    user = current_user()
    if user:
        return user['email']
    if os.environ.get('REVIZIO_AUTH_DISABLED') == '1':
        return DEV_OWNER
    abort(401)


def viewed_email():
    """Utilisateur dont on affiche le suivi : le sien, ou celui choisi par un admin
    avec ?user=<adresse> (seulement si ce compte existe)."""
    me = owner_email()
    wanted = request.args.get('user', '').strip().lower()
    user = current_user()
    if wanted and user and user['role'] == 'admin' and get_user(wanted):
        return wanted
    return me


def _active_admin_count(conn):
    return conn.execute(
        "SELECT COUNT(*) AS c FROM auth_users WHERE role = 'admin' AND active = 1"
    ).fetchone()['c']


# === INITIALISATION ===

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
        client_kwargs={'scope': 'openid email profile', 'code_challenge_method': 'S256'},
    )
    app.register_blueprint(bp)
    app.before_request(guard)

    @app.context_processor
    def inject_user():
        user = current_user()
        is_admin = bool(user and user['role'] == 'admin')
        return {'current_user': user['email'] if user else None,
                'is_admin': is_admin,
                'csrf_token': csrf_token,
                # selecteur du suivi (admin) : voir la progression d'un autre compte
                'picker_users': [u['email'] for u in list_users() if u['active']] if is_admin else [],
                'viewed_user': viewed_email() if user else None}


def guard():
    """Refuse toute requete sans session valide, sauf les chemins publics."""
    if os.environ.get('REVIZIO_AUTH_DISABLED') == '1':
        return None
    path = request.path
    if (path in ('/login', '/api/health') or path.startswith('/auth/')
            or path.startswith('/static/')):
        return None
    if current_user():
        return None
    if path.startswith('/api/'):
        return jsonify({'error': 'Authentification requise'}), 401
    return redirect(url_for('auth.login', next=request.full_path.rstrip('?')))


def csrf_token():
    if 'csrf' not in session:
        session['csrf'] = secrets.token_urlsafe(32)
    return session['csrf']


def _check_csrf():
    sent = request.form.get('csrf', '')
    expected = session.get('csrf', '')
    # un jeton vide ne doit jamais etre accepte (deux chaines vides sont egales)
    if not expected or not hmac.compare_digest(sent, expected):
        abort(400)


# === CONNEXION ===

@bp.route('/login')
def login():
    if current_user():
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
    user = get_user(email) if email else None
    if (not user or not user['active'] or info.get('email_verified') is not True):
        logger.warning(f"Connexion refusee pour {email or '(sans e-mail)'}")
        session.clear()
        return redirect(url_for('auth.login', erreur='refuse'))

    conn = _conn()
    try:
        conn.execute("UPDATE auth_users SET last_login_at = ?, name = ? WHERE email = ?",
                     (datetime.now().isoformat(), str(info.get('name', ''))[:120], email))
        conn.commit()
    finally:
        conn.close()
    target = safe_next(session.get('next'))
    session.clear()
    session['user'] = {'email': email}
    session.permanent = True
    logger.info(f"Connexion de {email}")
    return redirect(target)


@bp.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('auth.login'))


# === ADMINISTRATION DES UTILISATEURS ===

def _require_admin():
    user = current_user()
    if not user or user['role'] != 'admin':
        abort(403)
    return user


@bp.route('/admin/utilisateurs')
def admin_users():
    _require_admin()
    return render_template('admin_utilisateurs.html', users=list_users(), roles=ROLES)


@bp.route('/admin/utilisateurs', methods=['POST'])
def admin_add_user():
    admin = _require_admin()
    _check_csrf()
    email = request.form.get('email', '').strip().lower()
    role = request.form.get('role', 'user')
    if not EMAIL_RE.match(email) or len(email) > 200 or role not in ROLES:
        flash("Adresse e-mail ou rôle invalide.", 'error')
    elif get_user(email):
        flash(f"{email} existe déjà.", 'error')
    else:
        conn = _conn()
        try:
            conn.execute("INSERT INTO auth_users (email, role, active, created_at, added_by) "
                         "VALUES (?, ?, 1, ?, ?)",
                         (email, role, datetime.now().isoformat(), admin['email']))
            conn.commit()
        finally:
            conn.close()
        logger.info(f"{admin['email']} ajoute {email} ({role})")
        flash(f"{email} peut maintenant se connecter.", 'ok')
    return redirect(url_for('auth.admin_users'))


@bp.route('/admin/utilisateurs/modifier', methods=['POST'])
def admin_update_user():
    """Change le role ou l'etat actif d'un compte, en gardant au moins un admin actif."""
    admin = _require_admin()
    _check_csrf()
    email = request.form.get('email', '').strip().lower()
    action = request.form.get('action', '')
    target = get_user(email)
    if not target or action not in ('promouvoir', 'retrograder', 'desactiver', 'reactiver'):
        abort(400)

    conn = _conn()
    try:
        removes_admin = (target['role'] == 'admin' and target['active']
                         and action in ('retrograder', 'desactiver'))
        if removes_admin and (email == admin['email'] or _active_admin_count(conn) <= 1):
            flash("Tu ne peux pas retirer ton propre accès d'administrateur, ni le "
                  "dernier administrateur.", 'error')
            return redirect(url_for('auth.admin_users'))
        if action in ('promouvoir', 'retrograder'):
            conn.execute("UPDATE auth_users SET role = ? WHERE email = ?",
                         ('admin' if action == 'promouvoir' else 'user', email))
        else:
            conn.execute("UPDATE auth_users SET active = ? WHERE email = ?",
                         (1 if action == 'reactiver' else 0, email))
        conn.commit()
    finally:
        conn.close()
    logger.info(f"{admin['email']} : {action} {email}")
    flash("Modification enregistrée.", 'ok')
    return redirect(url_for('auth.admin_users'))
