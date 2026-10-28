"""
Contenu pedagogique du module Francais : competences, niveaux, textes.

Les textes de PASSAGES sont du domaine public et reproduits fidelement.
Tout autre texte est ecrit par l'IA et signale comme tel a l'eleve.
"""

AXES = [
    {'id': 'analyse', 'label': 'Analyse de texte'},
    {'id': 'redaction', 'label': 'Rédaction'},
    {'id': 'vocab', 'label': 'Vocabulaire'},
    {'id': 'orga', 'label': 'Organisation des idées'},
]

SKILLS = [
    {'id': 'pdv', 'axis': 'analyse', 'label': 'Narrateur et point de vue',
     'desc': "statut du narrateur (intérieur/extérieur à l'histoire), focalisation "
             "zéro/interne/externe, toujours justifiés par des indices du texte"},
    {'id': 'recit', 'axis': 'analyse', 'label': 'Récit : personnages et intrigue',
     'desc': "personnages, cadre spatio-temporel, schéma actantiel, schéma narratif, chute"},
    {'id': 'figures', 'axis': 'analyse', 'label': 'Figures de style',
     'desc': "identifier et nommer comparaison, métaphore, personnification, allégorie, "
             "antithèse, hyperbole, gradation, énumération, anaphore"},
    {'id': 'effet', 'axis': 'analyse', 'label': "Expliquer l'effet d'un procédé",
     'desc': "passer de « il y a une métaphore » à « elle suggère / souligne… » : interpréter "
             "l'effet produit sur le lecteur et le sens du texte"},
    {'id': 'citer', 'axis': 'analyse', 'label': 'Citer et relever',
     'desc': "relever le bon passage, citation courte entre guillemets, intégrée à la phrase, "
             "avec la référence (vers ou ligne)"},
    {'id': 'precision', 'axis': 'redaction', 'label': 'Précision et complétude',
     'desc': "répondre exactement à la question, en phrases complètes, sans vague "
             "(« quelque chose », « il se passe un truc »), avec les éléments précis du texte"},
    {'id': 'phrase', 'axis': 'redaction', 'label': 'Qualité des phrases',
     'desc': "syntaxe, ponctuation, registre soutenu, éviter les répétitions et l'oral, "
             "phrases ni trop courtes ni interminables"},
    {'id': 'connect', 'axis': 'redaction', 'label': 'Connecteurs logiques',
     'desc': "articuler les idées : d'abord, ensuite, en effet, ainsi, donc, cependant, de plus…"},
    {'id': 'lexique', 'axis': 'vocab', 'label': 'Richesse du lexique',
     'desc': "mot juste, nuances, synonymes précis, champs lexicaux, polysémie"},
    {'id': 'verbes', 'axis': 'vocab', 'label': "Verbes d'analyse",
     'desc': "suggère, souligne, met en relief, traduit, révèle, évoque, témoigne de… "
             "à la place de « montre » et « dit »"},
    {'id': 'paragraphe', 'axis': 'orga', 'label': 'Paragraphe argumenté',
     'desc': "une idée → une citation → une explication de l'effet → un lien avec la question"},
    {'id': 'plan', 'axis': 'orga', 'label': 'Organiser ses idées',
     'desc': "regrouper des relevés en axes, hiérarchiser, bâtir un plan en 2 ou 3 parties, "
             "introduction et conclusion de commentaire"},
]

SKILL_IDS = [s['id'] for s in SKILLS]
SKILL_BY_ID = {s['id']: s for s in SKILLS}

LEVELS = {
    1: "NIVEAU 1 (très guidé) : 3 questions courtes, une seule difficulté à la fois, "
       "réponse en une phrase, consigne et méthode rappelées dans l'énoncé.",
    2: "NIVEAU 2 (guidé) : 3 questions, réponse justifiée en 1 à 2 phrases avec une "
       "citation du texte.",
    3: "NIVEAU 3 (semi-autonome) : 2 questions dont une demande un court paragraphe "
       "(3-4 lignes) ; l'énoncé donne la structure attendue.",
    4: "NIVEAU 4 (autonome) : 1 ou 2 questions dont un paragraphe argumenté complet "
       "(idée, citation, explication) sans structure donnée.",
    5: "NIVEAU 5 (type épreuve) : une question d'analyse ouverte en style question de "
       "corpus / mini-commentaire (10 lignes) ; l'élève choisit lui-même ses procédés.",
    6: "NIVEAU 6 (épreuve blanche) : un sujet complet, deux ou trois questions "
       "enchaînées puis une consigne de rédaction d'un paragraphe de synthèse. Texte "
       "plus dense, sens implicite.",
}

# Textes classiques du domaine public (programme de seconde : roman et recit,
# poesie du XIXe, litterature d'idees). Reproduits fidelement.
PASSAGES = [
    {
        'id': 'parure', 'genre': 'prose',
        'source': "Guy de Maupassant, « La Parure », 1884 (incipit)",
        'texte': "C'était une de ces jolies et charmantes filles, nées, comme par une erreur "
                 "du destin, dans une famille d'employés. Elle n'avait pas de dot, pas "
                 "d'espérances, aucun moyen d'être connue, comprise, aimée, épousée par un "
                 "homme riche et distingué ; et elle se laissa marier avec un petit commis "
                 "du ministère de l'Instruction publique.",
    },
    {
        'id': 'germinal', 'genre': 'prose',
        'source': "Émile Zola, Germinal, 1885 (première phrase)",
        'texte': "Dans la plaine rase, sous la nuit sans étoiles, d'une obscurité et d'une "
                 "épaisseur d'encre, un homme suivait seul la grande route de Marchiennes à "
                 "Montsou, dix kilomètres de pavé coupant tout droit, à travers les champs "
                 "de betteraves.",
    },
    {
        'id': 'rouge_noir', 'genre': 'prose',
        'source': "Stendhal, Le Rouge et le Noir, 1830 (incipit)",
        'texte': "La petite ville de Verrières peut passer pour l'une des plus jolies de la "
                 "Franche-Comté. Ses maisons blanches avec leurs toits pointus de tuiles "
                 "rouges s'étendent sur la pente d'une colline, dont des touffes de "
                 "vigoureux châtaigniers marquent les moindres sinuosités.",
    },
    {
        'id': 'bovary', 'genre': 'prose',
        'source': "Gustave Flaubert, Madame Bovary, 1857 (incipit)",
        'texte': "Nous étions à l'Étude, quand le Proviseur entra, suivi d'un nouveau "
                 "habillé en bourgeois et d'un garçon de classe qui portait un grand pupitre.",
    },
    {
        'id': 'candide', 'genre': 'prose',
        'source': "Voltaire, Candide, 1759 (chapitre 1)",
        'texte': "Il y avait en Westphalie, dans le château de M. le baron de "
                 "Thunder-ten-tronckh, un jeune garçon à qui la nature avait donné les "
                 "mœurs les plus douces.",
    },
    {
        'id': 'albatros', 'genre': 'poesie',
        'source': "Charles Baudelaire, « L'Albatros », Les Fleurs du mal, 1857",
        'texte': "Souvent, pour s'amuser, les hommes d'équipage\n"
                 "Prennent des albatros, vastes oiseaux des mers,\n"
                 "Qui suivent, indolents compagnons de voyage,\n"
                 "Le navire glissant sur les gouffres amers.\n\n"
                 "À peine les ont-ils déposés sur les planches,\n"
                 "Que ces rois de l'azur, maladroits et honteux,\n"
                 "Laissent piteusement leurs grandes ailes blanches\n"
                 "Comme des avirons traîner à côté d'eux.\n\n"
                 "Ce voyageur ailé, comme il est gauche et veule !\n"
                 "Lui, naguère si beau, qu'il est comique et laid !\n"
                 "L'un agace son bec avec un brûle-gueule,\n"
                 "L'autre mime, en boitant, l'infirme qui volait !\n\n"
                 "Le Poète est semblable au prince des nuées\n"
                 "Qui hante la tempête et se rit de l'archer ;\n"
                 "Exilé sur le sol au milieu des huées,\n"
                 "Ses ailes de géant l'empêchent de marcher.",
    },
    {
        'id': 'dormeur', 'genre': 'poesie',
        'source': "Arthur Rimbaud, « Le Dormeur du val », 1870",
        'texte': "C'est un trou de verdure où chante une rivière\n"
                 "Accrochant follement aux herbes des haillons\n"
                 "D'argent ; où le soleil, de la montagne fière,\n"
                 "Luit : c'est un petit val qui mousse de rayons.\n\n"
                 "Un soldat jeune, bouche ouverte, tête nue,\n"
                 "Et la nuque baignant dans le frais cresson bleu,\n"
                 "Dort ; il est étendu dans l'herbe, sous la nue,\n"
                 "Pâle dans son lit vert où la lumière pleut.\n\n"
                 "Les pieds dans les glaïeuls, il dort. Souriant comme\n"
                 "Sourirait un enfant malade, il fait un somme :\n"
                 "Nature, berce-le chaudement : il a froid.\n\n"
                 "Les parfums ne font pas frissonner sa narine ;\n"
                 "Il dort dans le soleil, la main sur sa poitrine,\n"
                 "Tranquille. Il a deux trous rouges au côté droit.",
    },
    {
        'id': 'demain_aube', 'genre': 'poesie',
        'source': "Victor Hugo, « Demain, dès l'aube… », Les Contemplations, 1856",
        'texte': "Demain, dès l'aube, à l'heure où blanchit la campagne,\n"
                 "Je partirai. Vois-tu, je sais que tu m'attends.\n"
                 "J'irai par la forêt, j'irai par la montagne.\n"
                 "Je ne puis demeurer loin de toi plus longtemps.\n\n"
                 "Je marcherai les yeux fixés sur mes pensées,\n"
                 "Sans rien voir au dehors, sans entendre aucun bruit,\n"
                 "Seul, inconnu, le dos courbé, les mains croisées,\n"
                 "Triste, et le jour pour moi sera comme la nuit.\n\n"
                 "Je ne regarderai ni l'or du soir qui tombe,\n"
                 "Ni les voiles au loin descendant vers Harfleur,\n"
                 "Et, quand j'arriverai, je mettrai sur ta tombe\n"
                 "Un bouquet de houx vert et de bruyère en fleur.",
    },
    {
        'id': 'du_bellay', 'genre': 'poesie',
        'source': "Joachim Du Bellay, « Heureux qui, comme Ulysse… », Les Regrets, 1558 (quatrain 1)",
        'texte': "Heureux qui, comme Ulysse, a fait un beau voyage,\n"
                 "Ou comme cestuy-là qui conquit la toison,\n"
                 "Et puis est retourné, plein d'usage et raison,\n"
                 "Vivre entre ses parents le reste de son âge !",
    },
]
PASSAGE_BY_ID = {p['id']: p for p in PASSAGES}

# Pistes pour les textes originaux ecrits par l'IA (genres du programme de seconde).
ORIGINAL_THEMES = [
    "une nouvelle réaliste du XIXe siècle (scène de rue, portrait d'un personnage)",
    "l'incipit d'un roman : description d'un lieu qui annonce un drame",
    "un portrait moral par un narrateur ironique",
    "un court poème lyrique en vers libres ou en alexandrins sur la nature ou le temps",
    "une scène de nouvelle fantastique : un détail étrange dans un quotidien banal",
    "un extrait de lettre ou d'apologue qui défend une idée (littérature d'idées)",
    "une scène de dialogue entre deux personnages au conflit sous-jacent",
]
