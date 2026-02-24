"""Script d'initialisation - Revizio
Cree la base de donnees et insere les donnees initiales des outils."""

import sqlite3
from pathlib import Path

DB_PATH = Path('data/app.db')

# Liste des verbes irreguliers a reviser (liste n°1 et n°2)
# Format: (infinitive, past_simple, past_participle, french)
VERBS = [
    # Liste n°1 (1-35)
    ("read", "read", "read", "lire"),
    ("go", "went", "gone", "aller"),
    ("come", "came", "come", "venir"),
    ("put", "put", "put", "mettre"),
    ("sit", "sat", "sat", "s'asseoir"),
    ("stand", "stood", "stood", "se lever"),
    ("write", "wrote", "written", "écrire"),
    ("be", "was / were", "been", "être"),
    ("have", "had", "had", "avoir"),
    ("do", "did", "done", "faire"),
    ("choose", "chose", "chosen", "choisir"),
    ("make", "made", "made", "faire, fabriquer"),
    ("lose", "lost", "lost", "perdre"),
    ("overcome", "overcame", "overcome", "surmonter, vaincre"),
    ("hear", "heard", "heard", "entendre"),
    ("see", "saw", "seen", "voir"),
    ("speak", "spoke", "spoken", "parler"),
    ("fight", "fought", "fought", "se battre"),
    ("give", "gave", "given", "donner"),
    ("blend", "blent", "blent", "mélanger"),
    ("shoot", "shot", "shot", "tirer"),
    ("know", "knew", "known", "savoir, connaître"),
    ("run", "ran", "run", "courir"),
    ("swim", "swam", "swum", "nager"),
    ("rise", "rose", "risen", "monter, s'élever"),
    ("fly", "flew", "flown", "voler (dans l'air)"),
    ("spend", "spent", "spent", "dépenser de l'argent, passer du temps"),
    ("sell", "sold", "sold", "vendre"),
    ("buy", "bought", "bought", "acheter"),
    ("become", "became", "become", "devenir"),
    ("dream", "dreamt", "dreamt", "rêver"),
    ("drive", "drove", "driven", "conduire"),
    ("ride", "rode", "ridden", "faire/aller à cheval, moto, vélo"),
    ("pay", "paid", "paid", "payer"),
    ("cost", "cost", "cost", "coûter"),
    # Liste n°2 (36-53)
    ("keep", "kept", "kept", "garder"),
    ("hit", "hit", "hit", "frapper"),
    ("find", "found", "found", "trouver"),
    ("wear", "wore", "worn", "porter (un vêtement)"),
    ("tell", "told", "told", "dire (à quelqu'un)"),
    ("say", "said", "said", "dire (quelque chose)"),
    ("mean", "meant", "meant", "signifier, vouloir dire"),
    ("feel", "felt", "felt", "ressentir"),
    ("break", "broke", "broken", "casser"),
    ("bring", "brought", "brought", "apporter"),
    ("grow", "grew", "grown", "grandir"),
    ("awake", "awoke", "awoken", "se réveiller, se lever"),
    ("begin", "began", "begun", "commencer"),
    ("learn", "learnt", "learnt", "apprendre"),
    ("teach", "taught", "taught", "enseigner"),
    ("leave", "left", "left", "quitter, partir, laisser"),
    ("meet", "met", "met", "rencontrer"),
    ("leap", "leapt", "leapt", "bondir"),
]


def init_database():
    """Initialise la base de donnees avec le schema et les donnees."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Table des verbes irreguliers
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS verbs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            infinitive TEXT NOT NULL,
            past_simple TEXT NOT NULL,
            past_participle TEXT NOT NULL,
            french TEXT NOT NULL
        )
    """)

    # Inserer les verbes si la table est vide
    count = cursor.execute("SELECT COUNT(*) FROM verbs").fetchone()[0]
    if count == 0:
        cursor.executemany(
            "INSERT INTO verbs (infinitive, past_simple, past_participle, french) "
            "VALUES (?, ?, ?, ?)",
            VERBS
        )
        print(f"  {len(VERBS)} verbes irreguliers inseres")
    else:
        print(f"  {count} verbes deja presents, insertion ignoree")

    # Index sur les colonnes de recherche
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_infinitive ON verbs(infinitive)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_french ON verbs(french)")

    # Table des sessions (multi-outils via tool_type)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tool_type TEXT NOT NULL DEFAULT 'irregular-verbs',
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            mode TEXT DEFAULT 'random',
            total_verbs INTEGER DEFAULT 0,
            total_correct INTEGER DEFAULT 0,
            total_errors INTEGER DEFAULT 0,
            rounds INTEGER DEFAULT 0,
            pause_state TEXT
        )
    """)

    # Index sur le type d'outil pour filtrer les stats
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_tool_type ON sessions(tool_type)")

    # Table des erreurs par session
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS session_errors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL REFERENCES sessions(id),
            verb_id INTEGER NOT NULL REFERENCES verbs(id),
            error_count INTEGER DEFAULT 1
        )
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_session_errors_session ON session_errors(session_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_session_errors_verb ON session_errors(verb_id)")

    conn.commit()
    conn.close()

    print(f"  Base de donnees initialisee: {DB_PATH}")


if __name__ == '__main__':
    init_database()
    print("  Setup termine!")
