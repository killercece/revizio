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
