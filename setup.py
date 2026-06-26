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


# Programme officiel d'histoire-geographie de 3e (Education Nationale)
# Format: (matiere, chapitre, intitule, points_cles)
# points_cles = notions concretes separees par ' ; ' pour cadrer la generation
HG_THEMES = [
    # === HISTOIRE ===
    ("Histoire", "L'Europe, un théâtre majeur des guerres totales (1914-1945)",
     "Civils et militaires dans la Première Guerre mondiale",
     "1914 entrée en guerre ; tranchées ; bataille de Verdun 1916 ; guerre totale ; "
     "génocide arménien ; 1918 armistice ; traité de Versailles 1919"),
    ("Histoire", "L'Europe, un théâtre majeur des guerres totales (1914-1945)",
     "Démocraties fragilisées et expériences totalitaires dans l'Europe de l'entre-deux-guerres",
     "URSS de Staline ; Italie fasciste de Mussolini ; Allemagne nazie d'Hitler 1933 ; "
     "crise économique de 1929 ; propagande ; régimes totalitaires"),
    ("Histoire", "L'Europe, un théâtre majeur des guerres totales (1914-1945)",
     "La Seconde Guerre mondiale, une guerre d'anéantissement",
     "1939-1945 ; Résistance ; collaboration et régime de Vichy ; Shoah ; "
     "camp d'Auschwitz ; débarquement de Normandie 1944 ; bombe atomique d'Hiroshima"),

    ("Histoire", "Le monde depuis 1945",
     "Indépendances et construction de nouveaux États (décolonisation)",
     "indépendance de l'Inde 1947 ; guerre d'Algérie 1954-1962 ; décolonisation de l'Afrique ; "
     "tiers-monde ; conférence de Bandung 1955"),
    ("Histoire", "Le monde depuis 1945",
     "Un monde bipolaire au temps de la guerre froide",
     "affrontement USA / URSS ; Berlin ; mur de Berlin 1961 ; crise de Cuba 1962 ; "
     "OTAN et Pacte de Varsovie ; fin de la guerre froide 1989-1991"),
    ("Histoire", "Le monde depuis 1945",
     "Affirmation et mise en œuvre du projet européen",
     "CECA 1951 ; traité de Rome 1957 ; CEE ; traité de Maastricht 1992 ; "
     "monnaie unique euro ; construction européenne"),

    ("Histoire", "Françaises et Français dans une République repensée",
     "Refonder la République, redéfinir la démocratie (1944-1947)",
     "GPRF ; de Gaulle ; droit de vote des femmes 1944 ; Sécurité sociale 1945 ; "
     "IVe République ; programme du CNR"),
    ("Histoire", "Françaises et Français dans une République repensée",
     "La Ve République, de la République gaullienne à l'alternance et à la cohabitation",
     "1958 fondation ; Constitution ; de Gaulle ; élection du président au suffrage universel 1962 ; "
     "1981 élection de Mitterrand ; cohabitation"),
    ("Histoire", "Françaises et Français dans une République repensée",
     "Femmes et hommes dans la société des années 1950 aux années 1980",
     "Trente Glorieuses ; travail des femmes ; loi Veil 1975 ; contraception ; "
     "MLF ; immigration"),

    # === GEOGRAPHIE ===
    # Les points_cles integrent les reperes cartographiques officiels du DNB 2026
    # (d'apres histographie.net, O. Fourrier) pour cadrer la generation.
    ("Géographie", "Dynamiques territoriales de la France contemporaine",
     "Les aires urbaines d'une France mondialisée",
     "métropolisation ; périurbanisation ; étalement urbain ; banlieues ; "
     "10 plus grandes aires urbaines : Paris, Lyon, Marseille-Aix, Lille, "
     "Toulouse, Bordeaux, Nice, Nantes, Strasbourg, Rennes ; "
     "métropole mondiale Paris ; métropoles régionales ; "
     "13 régions métropolitaines : Hauts-de-France, Normandie, Île-de-France, "
     "Grand Est, Bretagne, Pays de la Loire, Centre-Val de Loire, "
     "Bourgogne-Franche-Comté, Nouvelle-Aquitaine, Auvergne-Rhône-Alpes, "
     "Occitanie, Provence-Alpes-Côte d'Azur, Corse"),
    ("Géographie", "Dynamiques territoriales de la France contemporaine",
     "Les espaces productifs et leurs évolutions",
     "agriculture ; industrie ; services ; technopôles ; mondialisation ; "
     "tourisme ; grand port ; aéroport international ; axe majeur et axe "
     "important de transport ; région industrielle en reconversion ; "
     "5 fleuves : Seine, Loire, Garonne, Rhône, Rhin"),
    ("Géographie", "Dynamiques territoriales de la France contemporaine",
     "Les espaces de faible densité et leurs atouts",
     "espaces ruraux ; déprise rurale ; néoruraux ; atouts touristiques ; "
     "5 reliefs / massifs montagneux : Massif central, Alpes, Pyrénées, Jura, "
     "Vosges ; île montagneuse au Sud-Est = Corse ; "
     "3 mers (Manche, mer du Nord, Méditerranée) + océan Atlantique"),

    ("Géographie", "Pourquoi et comment aménager le territoire ?",
     "Aménager pour réduire les inégalités territoriales",
     "inégalités territoriales ; collectivités territoriales ; État ; "
     "Union européenne ; politiques d'aménagement ; "
     "espace central (cœur du territoire) ; périphérie dynamique ; "
     "espace à dominante rurale en déprise ; métropoles régionales et "
     "métropole mondiale Paris ; axes structurants du territoire"),
    ("Géographie", "Pourquoi et comment aménager le territoire ?",
     "Les territoires ultramarins français",
     "DROM ; éloignement ; atouts maritimes ; zone économique exclusive (ZEE) ; "
     "contraintes ; 5 DROM : Guadeloupe et Martinique (Atlantique/Antilles), "
     "Guyane (Amérique du Sud, continentale), Mayotte et La Réunion (océan "
     "Indien, près de Madagascar) ; 4 DROM insulaires (Guadeloupe, Martinique, "
     "La Réunion, Mayotte), Guyane non insulaire ; TOM / TAAF ; "
     "Nouvelle-Calédonie ; autres collectivités d'outre-mer"),

    ("Géographie", "La France et l'Union européenne",
     "L'UE, un territoire de référence et d'appartenance",
     "27 pays de l'UE et leurs 27 capitales ; élargissements ; "
     "zone euro (pays ayant adopté l'euro) ; espace Schengen (libre "
     "circulation, 27 membres dont 4 hors UE) ; 6 mers (Méditerranée, mer du "
     "Nord, Baltique, mer Noire, Manche) + océan Atlantique ; "
     "pays voisins : Royaume-Uni, Norvège, Ukraine, Russie, Turquie, Maroc, "
     "Algérie, Tunisie, Israël ; mégalopole européenne (dorsale) ; "
     "cœur de l'UE ; périphéries (Europe du Sud, Europe centrale et orientale) ; "
     "sièges des institutions ; disparités"),
    ("Géographie", "La France et l'Union européenne",
     "La France et l'Europe dans le monde",
     "rayonnement ; francophonie ; DROM ; puissance ; ONU ; "
     "4 puissances : États-Unis, Union européenne, Japon, Corée du Sud ; "
     "5 BRICS : Brésil, Russie, Inde, Chine, Afrique du Sud ; "
     "mégapoles (> 10 M hab) ; 2 canaux : Panama (Atlantique/Pacifique) et "
     "Suez (Méditerranée/mer Rouge) ; 5 océans (Pacifique, Atlantique, Indien, "
     "Glacial Arctique, Glacial Antarctique) ; latitudes (équateur, tropiques, "
     "cercles polaires) ; 7 pays frontaliers de la France dont le "
     "Royaume-Uni relié par le tunnel sous la Manche : Belgique, Luxembourg, "
     "Allemagne, Suisse, Italie, Espagne, Royaume-Uni (+ Andorre, Monaco)"),
]


# Banque de questions illustrees (geographie) rattachees a un theme par intitule.
# Format: (intitule_theme, image_path, description, question, expected_answer)
# image_path est relatif a static/ (utilisable via url_for('static', filename=...)).
# description sert au proxy a corriger sans "voir" l'image.
# Reperes conformes au programme officiel du DNB — cartes de revision d'apres
# histographie.net (O. Fourrier).
HG_ILLUSTRATED = [
    ("Les aires urbaines d'une France mondialisée",
     "img/geo/france-metropoles.png",
     "Carte de France avec 6 points : 1=Paris, 2=Lille, 3=Strasbourg, "
     "4=Lyon, 5=Marseille, 6=Bordeaux.",
     "Nomme les grandes aires urbaines repérées 1 à 6.",
     "1 Paris, 2 Lille, 3 Strasbourg, 4 Lyon, 5 Marseille, 6 Bordeaux"),
    ("Les aires urbaines d'une France mondialisée",
     "img/geo/france-fleuves.png",
     "Carte de France avec 5 fleuves tracés et numérotés : 1=Seine, 2=Loire, "
     "3=Garonne, 4=Rhône, 5=Rhin.",
     "Nomme les 5 grands fleuves français numérotés.",
     "1 Seine, 2 Loire, 3 Garonne, 4 Rhône, 5 Rhin"),
    ("Les espaces de faible densité et leurs atouts",
     "img/geo/france-reliefs.png",
     "Carte de France des reliefs : 1=Massif central, 2=Alpes, 3=Pyrénées, "
     "4=Jura, 5=Vosges.",
     "Identifie les 5 principaux massifs montagneux numérotés.",
     "1 Massif central, 2 Alpes, 3 Pyrénées, 4 Jura, 5 Vosges"),
    ("Les territoires ultramarins français",
     "img/geo/france-drom.png",
     "Planisphère localisant les 5 DROM numérotés : 1=Guadeloupe, "
     "2=Martinique, 3=Guyane, 4=La Réunion, 5=Mayotte. Guyane = continentale "
     "(Amérique du Sud), les autres sont insulaires.",
     "Nomme les 5 DROM et précise lesquels sont insulaires.",
     "1 Guadeloupe (île), 2 Martinique (île), 3 Guyane (continentale, Amérique "
     "du Sud), 4 La Réunion (île), 5 Mayotte (île)"),
    ("La France et l'Europe dans le monde",
     "img/geo/france-frontieres.png",
     "Carte des pays frontaliers numérotés 1 à 7 : 1=Belgique, 2=Luxembourg, "
     "3=Allemagne, 4=Suisse, 5=Italie, 6=Espagne, 7=Royaume-Uni relié par le "
     "tunnel sous la Manche.",
     "Nomme les pays frontaliers de la France (1 à 7), dont celui relié par un "
     "tunnel.",
     "1 Belgique, 2 Luxembourg, 3 Allemagne, 4 Suisse, 5 Italie, 6 Espagne, "
     "7 Royaume-Uni (tunnel sous la Manche)"),
    ("L'UE, un territoire de référence et d'appartenance",
     "img/geo/ue-pays.png",
     "Carte de l'Europe avec 6 pays de l'UE numérotés : 1=France, 2=Espagne, "
     "3=Allemagne, 4=Italie, 5=Pologne, 6=Suède.",
     "Nomme les 6 pays de l'Union européenne numérotés sur la carte.",
     "1 France, 2 Espagne, 3 Allemagne, 4 Italie, 5 Pologne, 6 Suède"),
    ("Les aires urbaines d'une France mondialisée",
     "img/geo/france-regions.png",
     "Carte des 13 régions administratives métropolitaines numérotées 1 à 13 "
     "(1=Hauts-de-France, 2=Normandie, 3=Île-de-France, 4=Grand Est, "
     "5=Bretagne, 6=Pays de la Loire, 7=Centre-Val de Loire, "
     "8=Bourgogne-Franche-Comté, 9=Nouvelle-Aquitaine, "
     "10=Auvergne-Rhône-Alpes, 11=Occitanie, "
     "12=Provence-Alpes-Côte d'Azur, 13=Corse).",
     "Nomme les 13 régions administratives métropolitaines numérotées.",
     "1 Hauts-de-France, 2 Normandie, 3 Île-de-France, 4 Grand Est, "
     "5 Bretagne, 6 Pays de la Loire, 7 Centre-Val de Loire, "
     "8 Bourgogne-Franche-Comté, 9 Nouvelle-Aquitaine, "
     "10 Auvergne-Rhône-Alpes, 11 Occitanie, "
     "12 Provence-Alpes-Côte d'Azur, 13 Corse"),
    ("La France et l'Europe dans le monde",
     "img/geo/monde-reperes.png",
     "Planisphère avec les 5 BRICS numérotés : 1=Brésil, 2=Russie, 3=Inde, "
     "4=Chine, 5=Afrique du Sud.",
     "Identifie les 5 pays des BRICS numérotés sur le planisphère.",
     "1 Brésil, 2 Russie, 3 Inde, 4 Chine, 5 Afrique du Sud"),
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

    # Table des themes d'histoire-geographie (programme officiel de 3e)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hg_themes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            matiere TEXT NOT NULL,
            chapitre TEXT NOT NULL,
            intitule TEXT NOT NULL,
            points_cles TEXT NOT NULL
        )
    """)

    # Inserer les themes si la table est vide
    hg_count = cursor.execute("SELECT COUNT(*) FROM hg_themes").fetchone()[0]
    if hg_count == 0:
        cursor.executemany(
            "INSERT INTO hg_themes (matiere, chapitre, intitule, points_cles) "
            "VALUES (?, ?, ?, ?)",
            HG_THEMES
        )
        print(f"  {len(HG_THEMES)} themes histoire-geo inseres")
    else:
        print(f"  {hg_count} themes histoire-geo deja presents, insertion ignoree")

    # Table des reponses libres corrigees par l'IA
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hg_answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER REFERENCES sessions(id),
            theme_id INTEGER REFERENCES hg_themes(id),
            question TEXT,
            student_answer TEXT,
            correct INTEGER,
            note TEXT,
            feedback TEXT,
            correction TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_hg_answers_session ON hg_answers(session_id)")

    # Table de la banque de questions illustrees (geographie)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hg_illustrated_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            theme_id INTEGER REFERENCES hg_themes(id),
            image_path TEXT,
            description TEXT,
            question TEXT,
            expected_answer TEXT
        )
    """)

    # Seed des questions illustrees si la table est vide.
    # Chaque entree est rattachee au theme par son intitule.
    illus_count = cursor.execute(
        "SELECT COUNT(*) FROM hg_illustrated_questions"
    ).fetchone()[0]
    if illus_count == 0:
        inserted = 0
        for intitule, image_path, description, question, expected in HG_ILLUSTRATED:
            theme_row = cursor.execute(
                "SELECT id FROM hg_themes WHERE intitule = ?", (intitule,)
            ).fetchone()
            theme_id = theme_row[0] if theme_row else None
            cursor.execute(
                "INSERT INTO hg_illustrated_questions "
                "(theme_id, image_path, description, question, expected_answer) "
                "VALUES (?, ?, ?, ?, ?)",
                (theme_id, image_path, description, question, expected)
            )
            inserted += 1
        print(f"  {inserted} questions illustrees inserees")
    else:
        print(f"  {illus_count} questions illustrees deja presentes, insertion ignoree")

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_hg_illus_theme "
        "ON hg_illustrated_questions(theme_id)"
    )

    conn.commit()
    conn.close()

    print(f"  Base de donnees initialisee: {DB_PATH}")


if __name__ == '__main__':
    init_database()
    print("  Setup termine!")
