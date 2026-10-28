# Revizio

Portail de revision pour le college. Regroupe plusieurs outils interactifs pour reviser efficacement.

## Outils disponibles

- **Verbes Irreguliers** : Quiz interactif sur 53 verbes irreguliers anglais avec systeme de rounds, suivi parental et sauvegarde automatique
- **Francais : analyse et redaction** (`/francais/`) : entrainement adaptatif de seconde. 12 competences en 4 axes (analyse de texte, redaction, vocabulaire, organisation des idees), 6 niveaux, exercices generes et corriges par l'IA, profil de l'eleve garde en memoire, bilan tous les 5 exercices, suivi parental (`/francais/suivi`). Code dans `francais.py` (moteur, routes) et `francais_data.py` (competences, niveaux, textes du domaine public). Tests : `python tests/test_francais.py` (base jetable, IA simulee).

## Installation

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python setup.py
python app.py
```

## Deploiement

Deploye via PyDeploy sur `revizio.cdtechnology.fr`.
Le push sur `main` declenche le redeploiement automatique.

## Structure

```
revizio/
├── app.py              # Application Flask (portail + outils)
├── setup.py            # Initialisation BDD
├── requirements.txt
├── static/
│   ├── css/style.css   # Design system complet
│   ├── js/main.js      # Core (theme toggle)
│   ├── js/verbs.js     # Quiz verbes irreguliers
│   └── favicon.svg
└── templates/
    ├── base.html        # Layout commun
    ├── index.html       # Portail d'accueil
    ├── verbs.html       # Quiz verbes irreguliers
    ├── verbs_suivi.html # Suivi verbes
    └── suivi.html       # Suivi global
```

## Securite (connexion Google)

Toutes les pages et API exigent une session, sauf `/login`, `/auth/*`, `/static/*` et `/api/health`. La connexion passe par Google (OpenID Connect, PKCE) : seul un utilisateur actif de la table `auth_users`, dont l'e-mail est verifie par Google, entre. Sans identifiants Google configures, tout reste ferme. Modele repris de cdt-hr (utilisateurs en base, roles, administration).

Roles : `admin` (gere les utilisateurs depuis `/admin/utilisateurs` : ajout, passage admin, desactivation) et `user`. Le statut est relu a chaque requete : desactiver un compte coupe sa session aussitot. On ne peut pas retirer son propre acces admin ni le dernier admin.

Variables d'environnement (PyDeploy) : `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `ADMIN_EMAILS` (administrateurs de depart, separes par des virgules, recrees actifs a chaque demarrage), `PUBLIC_URL` (optionnelle, defaut `https://revizio.cdtechnology.fr`), `SECRET_KEY` (optionnelle : sinon une cle aleatoire est creee dans `data/.secret_key`). Adresse de retour a declarer chez Google : `<PUBLIC_URL>/auth/callback`.

En local : `REVIZIO_AUTH_DISABLED=1` desactive la protection, `REVIZIO_INSECURE_COOKIES=1` autorise le http. Tests : `python tests/test_auth.py`.
