/**
 * Revizio - Histoire-Géo (révision Brevet 3e) — MODE BATCH
 *
 * Le proxy IA etant lent, on genere TOUTES les questions d'un coup, l'eleve
 * repond a tout, puis une seule correction groupee est demandee a la fin.
 *
 * Flux :
 *   Ecran 1 (screen-start)      : selection des themes -> POST sessions.
 *   Ecran attente (generating)  : generation des 10 questions (1 appel long).
 *   Ecran 2 (screen-quiz)       : questionnaire sequentiel, navigation libre,
 *                                 reponses conservees en memoire, SANS correction.
 *   Ecran attente (correcting)  : correction groupee (1 appel long).
 *   Ecran 3 (screen-results)    : score global + detail question par question.
 *   Ecran erreur (screen-error) : reessai sur l'action en cours (sessions/correct).
 *
 * Contrat API (batch) :
 *   GET  /api/hg/themes
 *        -> [{id, matiere, chapitre, intitule}]
 *   POST /api/hg/sessions {themes:[ids], count:10}
 *        -> {id, questions:[{idx, theme_id, theme_label, question, image_url|null, illustrated}]}
 *   POST /api/hg/sessions/<id>/correct {answers:[{idx, answer}]}
 *        -> {summary:{total_correct,total_errors,accuracy},
 *            corrections:[{idx, correct, note, feedback, correction}]}
 *        (cet appel CLOT la session ; il n'y a plus de PUT de cloture)
 */

const QUESTION_COUNT = 10;

// === ETAT ===
let allThemes = [];          // tous les themes charges
let selectedThemeIds = [];   // ids coches par l'eleve
let sessionId = null;
let questions = [];          // liste des questions (ordre du serveur)
let answers = {};            // { idx: texte de la reponse }
let currentPos = 0;          // position courante dans `questions`
let busy = false;            // anti-double appel pendant un fetch
let retryAction = null;      // callback a relancer depuis l'ecran d'erreur

// === INITIALISATION ===
document.addEventListener('DOMContentLoaded', () => {
    initEventListeners();
    loadThemes();
});

function initEventListeners() {
    document.getElementById('btn-retry-themes').addEventListener('click', loadThemes);
    document.getElementById('btn-select-all').addEventListener('click', toggleSelectAll);
    document.getElementById('btn-start').addEventListener('click', startSession);

    document.getElementById('btn-prev').addEventListener('click', goPrev);
    document.getElementById('btn-next').addEventListener('click', goNext);
    document.getElementById('btn-submit').addEventListener('click', submitForCorrection);

    document.getElementById('btn-retry-action').addEventListener('click', () => {
        if (retryAction) retryAction();
    });
}

// === NAVIGATION ENTRE ECRANS ===

function showScreen(screenId) {
    document.querySelectorAll('.screen').forEach(s => s.classList.remove('active'));
    const screen = document.getElementById(screenId);
    void screen.offsetWidth;
    screen.classList.add('active');
}

function setVisible(id, visible) {
    document.getElementById(id).classList.toggle('hidden', !visible);
}

/**
 * Affiche l'ecran d'erreur avec un message et memorise l'action a reessayer.
 */
function showError(message, action) {
    document.getElementById('error-msg').textContent = message;
    retryAction = action;
    showScreen('screen-error');
}

// === ECRAN 1 : THEMES ===

async function loadThemes() {
    setVisible('themes-loading', true);
    setVisible('themes-error', false);
    setVisible('themes-container', false);
    showScreen('screen-start');

    try {
        const res = await fetch('/api/hg/themes');
        if (!res.ok) throw new Error('HTTP ' + res.status);
        allThemes = await res.json();
        renderThemes();
        setVisible('themes-loading', false);
        setVisible('themes-container', true);
    } catch (e) {
        console.error('Erreur chargement themes:', e);
        setVisible('themes-loading', false);
        setVisible('themes-error', true);
    }
}

function renderThemes() {
    const container = document.getElementById('themes-groups');
    container.innerHTML = '';

    // Regrouper par matiere en conservant l'ordre d'apparition.
    const groups = {};
    const order = [];
    allThemes.forEach(t => {
        const key = t.matiere || 'Autres';
        if (!groups[key]) { groups[key] = []; order.push(key); }
        groups[key].push(t);
    });

    order.forEach(matiere => {
        const section = document.createElement('div');

        const title = document.createElement('p');
        title.className = 'text-[11px] font-medium text-zinc-400 dark:text-zinc-500 uppercase tracking-wider mb-2';
        title.textContent = matiere;
        section.appendChild(title);

        const list = document.createElement('div');
        list.className = 'rounded-xl border border-zinc-200 dark:border-zinc-800 divide-y divide-zinc-100 dark:divide-zinc-800';

        groups[matiere].forEach(theme => {
            const label = document.createElement('label');
            label.className = 'flex items-start gap-3 p-3 cursor-pointer hover:bg-zinc-50 dark:hover:bg-zinc-800/50 transition-colors';

            const cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.className = 'mt-0.5 w-4 h-4 rounded border-zinc-300 dark:border-zinc-600 text-violet-600 focus:ring-violet-600/30 cursor-pointer accent-violet-600';
            cb.value = theme.id;
            cb.addEventListener('change', updateSelection);

            const text = document.createElement('div');
            text.className = 'flex-1 min-w-0';
            const main = document.createElement('span');
            main.className = 'block text-sm font-medium';
            main.textContent = theme.intitule;
            text.appendChild(main);
            if (theme.chapitre) {
                const sub = document.createElement('span');
                sub.className = 'block text-xs text-zinc-400';
                sub.textContent = theme.chapitre;
                text.appendChild(sub);
            }

            label.appendChild(cb);
            label.appendChild(text);
            list.appendChild(label);
        });

        section.appendChild(list);
        container.appendChild(section);
    });

    document.getElementById('themes-count').textContent =
        `${allThemes.length} thème${allThemes.length > 1 ? 's' : ''} disponible${allThemes.length > 1 ? 's' : ''}`;

    updateSelection();
}

function updateSelection() {
    const boxes = document.querySelectorAll('#themes-groups input[type="checkbox"]');
    selectedThemeIds = Array.from(boxes)
        .filter(b => b.checked)
        .map(b => parseInt(b.value, 10));

    document.getElementById('btn-start').disabled = selectedThemeIds.length === 0;

    const hint = document.getElementById('start-hint');
    if (selectedThemeIds.length === 0) {
        hint.textContent = 'Sélectionne au moins un thème pour commencer.';
    } else {
        hint.textContent = `${selectedThemeIds.length} thème${selectedThemeIds.length > 1 ? 's' : ''} sélectionné${selectedThemeIds.length > 1 ? 's' : ''}.`;
    }

    const allChecked = boxes.length > 0 && selectedThemeIds.length === boxes.length;
    document.getElementById('btn-select-all').textContent =
        allChecked ? 'Tout désélectionner' : 'Tout sélectionner';
}

function toggleSelectAll() {
    const boxes = document.querySelectorAll('#themes-groups input[type="checkbox"]');
    const allChecked = Array.from(boxes).every(b => b.checked);
    boxes.forEach(b => { b.checked = !allChecked; });
    updateSelection();
}

// === CREATION DE SESSION + GENERATION DES QUESTIONS ===

/**
 * Cree la session et recupere les 10 questions (un seul appel proxy, long).
 */
async function startSession() {
    if (busy || selectedThemeIds.length === 0) return;
    busy = true;
    showScreen('screen-generating');

    try {
        const res = await fetch('/api/hg/sessions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ themes: selectedThemeIds, count: QUESTION_COUNT })
        });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();

        sessionId = data.id;
        questions = (data.questions || []).slice();
        answers = {};
        currentPos = 0;

        busy = false;

        if (questions.length === 0) {
            showError('Aucune question n\'a pu être générée. Réessaie.', startSession);
            return;
        }

        showScreen('screen-quiz');
        renderCurrentQuestion();
    } catch (e) {
        console.error('Erreur creation session:', e);
        busy = false;
        showError('La préparation des questions a échoué (réseau ou serveur). Réessaie.', startSession);
    }
}

// === ECRAN 2 : QUESTIONNAIRE SEQUENTIEL ===

/**
 * Affiche la question a la position courante.
 */
function renderCurrentQuestion() {
    const q = questions[currentPos];

    document.getElementById('round-badge').textContent =
        `Question ${currentPos + 1} / ${questions.length}`;
    document.getElementById('theme-badge').textContent = q.theme_label || 'Thème';
    document.getElementById('question-text').textContent = q.question;

    // Image illustree.
    const wrap = document.getElementById('question-image-wrap');
    const img = document.getElementById('question-image');
    if (q.illustrated && q.image_url) {
        img.src = q.image_url;
        wrap.classList.remove('hidden');
    } else {
        img.removeAttribute('src');
        wrap.classList.add('hidden');
    }

    // Reponse memorisee.
    const input = document.getElementById('answer-input');
    input.value = answers[q.idx] || '';

    // Compteur de reponses saisies.
    const filled = questions.filter(x => (answers[x.idx] || '').trim()).length;
    document.getElementById('answered-count').textContent =
        `${filled} / ${questions.length} répondue${filled > 1 ? 's' : ''}`;

    // Barre de progression (position dans le parcours).
    document.getElementById('progress-fill').style.width =
        `${((currentPos + 1) / questions.length) * 100}%`;

    // Boutons de navigation.
    document.getElementById('btn-prev').disabled = currentPos === 0;
    const isLast = currentPos === questions.length - 1;
    setVisible('btn-next', !isLast);
    document.getElementById('btn-submit').classList.toggle('hidden', !isLast);
    document.getElementById('btn-submit').classList.toggle('flex', isLast);

    setTimeout(() => input.focus(), 100);
    animateCard();
}

/**
 * Sauvegarde la reponse courante en memoire.
 */
function saveCurrentAnswer() {
    const q = questions[currentPos];
    answers[q.idx] = document.getElementById('answer-input').value;
}

function goPrev() {
    saveCurrentAnswer();
    if (currentPos > 0) {
        currentPos--;
        renderCurrentQuestion();
    }
}

function goNext() {
    saveCurrentAnswer();
    if (currentPos < questions.length - 1) {
        currentPos++;
        renderCurrentQuestion();
    }
}

function animateCard() {
    const card = document.getElementById('quiz-card');
    card.style.animation = 'none';
    void card.offsetWidth;
    card.style.animation = 'fadeIn 0.3s ease';
}

// === CORRECTION GROUPEE ===

/**
 * Envoie toutes les reponses pour correction groupee (un seul appel long).
 */
async function submitForCorrection() {
    if (busy) return;
    saveCurrentAnswer();
    busy = true;
    showScreen('screen-correcting');

    const payload = {
        answers: questions.map(q => ({
            idx: q.idx,
            answer: (answers[q.idx] || '').trim()
        }))
    };

    try {
        const res = await fetch(`/api/hg/sessions/${sessionId}/correct`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();

        busy = false;
        renderResults(data);
        showScreen('screen-results');
    } catch (e) {
        console.error('Erreur correction:', e);
        busy = false;
        // On revient a l'ecran d'erreur, qui relancera la correction.
        showError('La correction a échoué (réseau ou serveur). Tes réponses sont conservées, réessaie.', submitForCorrection);
    }
}

// === ECRAN 3 : RESULTATS ===

/**
 * Affiche le score global puis le detail question par question.
 */
function renderResults(data) {
    const summary = data.summary || {};
    const corrections = data.corrections || [];

    const total = questions.length;
    const correct = summary.total_correct != null ? summary.total_correct : 0;
    const accuracy = summary.accuracy != null
        ? summary.accuracy
        : (total > 0 ? Math.round((correct / total) * 100) : 0);

    document.getElementById('summary-total').textContent = total;
    document.getElementById('summary-correct').textContent = correct;
    document.getElementById('summary-accuracy').textContent = `${accuracy}%`;

    // Index des corrections par idx pour les apparier aux questions.
    const corrById = {};
    corrections.forEach(c => { corrById[c.idx] = c; });

    const listEl = document.getElementById('results-list');
    listEl.innerHTML = '';

    questions.forEach((q, i) => {
        const c = corrById[q.idx] || {};
        const studentAnswer = (answers[q.idx] || '').trim();

        const card = document.createElement('div');
        card.className = 'rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6';

        const badgeClass = c.correct
            ? 'bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400'
            : 'bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-400';
        const badgeText = c.correct ? 'Réussie' : 'À revoir';

        // En-tete : numero, theme, badge, note. textContent pour eviter l'injection.
        const header = document.createElement('div');
        header.className = 'flex items-start justify-between gap-3 mb-3';

        const tags = document.createElement('div');
        tags.className = 'flex items-center gap-2 flex-wrap';

        const numSpan = document.createElement('span');
        numSpan.className = 'text-xs text-zinc-400 font-medium';
        numSpan.textContent = `Q${i + 1}`;

        const themeSpan = document.createElement('span');
        themeSpan.className = 'text-[11px] font-medium bg-zinc-100 dark:bg-zinc-800 text-zinc-500 dark:text-zinc-400 px-2 py-0.5 rounded-full';
        themeSpan.textContent = q.theme_label || 'Thème';

        const badgeSpan = document.createElement('span');
        badgeSpan.className = `text-xs font-medium px-2 py-0.5 rounded-full ${badgeClass}`;
        badgeSpan.textContent = badgeText;

        tags.append(numSpan, themeSpan, badgeSpan);

        const noteSpan = document.createElement('span');
        noteSpan.className = 'text-sm font-semibold text-zinc-500 dark:text-zinc-400 flex-shrink-0';
        noteSpan.textContent = c.note || '';

        header.append(tags, noteSpan);
        card.appendChild(header);

        // Image si illustree.
        if (q.illustrated && q.image_url) {
            const imgWrap = document.createElement('div');
            imgWrap.className = 'mb-3';
            const img = document.createElement('img');
            img.src = q.image_url;
            img.alt = 'Illustration de la question';
            img.className = 'w-full max-w-md rounded-lg border border-zinc-200 dark:border-zinc-800';
            imgWrap.appendChild(img);
            card.appendChild(imgWrap);
        }

        // Enonce.
        const qEl = document.createElement('p');
        qEl.className = 'text-sm font-semibold mb-3';
        qEl.textContent = q.question;
        card.appendChild(qEl);

        // Bloc reponse / feedback / correction.
        const body = document.createElement('div');
        body.className = 'space-y-2 text-sm';

        const ansBlock = document.createElement('div');
        ansBlock.innerHTML = `<span class="text-[11px] font-medium text-zinc-400 dark:text-zinc-500 uppercase tracking-wider">Ta réponse</span>`;
        const ansP = document.createElement('p');
        ansP.className = 'text-zinc-600 dark:text-zinc-300 mt-0.5 whitespace-pre-line';
        ansP.textContent = studentAnswer || '(pas de réponse)';
        if (!studentAnswer) ansP.classList.add('italic', 'text-zinc-400');
        ansBlock.appendChild(ansP);
        body.appendChild(ansBlock);

        if (c.feedback) {
            const fb = document.createElement('div');
            fb.innerHTML = `<span class="text-[11px] font-medium text-zinc-400 dark:text-zinc-500 uppercase tracking-wider">Appréciation</span>`;
            const fbP = document.createElement('p');
            fbP.className = 'text-zinc-600 dark:text-zinc-300 mt-0.5 whitespace-pre-line';
            fbP.textContent = c.feedback;
            fb.appendChild(fbP);
            body.appendChild(fb);
        }

        if (c.correction) {
            const corr = document.createElement('div');
            corr.className = 'rounded-lg bg-zinc-50 dark:bg-zinc-800/50 border border-zinc-100 dark:border-zinc-800 p-3';
            corr.innerHTML = `<span class="text-[11px] font-medium text-zinc-400 dark:text-zinc-500 uppercase tracking-wider">Correction</span>`;
            const corrP = document.createElement('p');
            corrP.className = 'text-zinc-700 dark:text-zinc-200 mt-0.5 whitespace-pre-line';
            corrP.textContent = c.correction;
            corr.appendChild(corrP);
            body.appendChild(corr);
        }

        card.appendChild(body);
        listEl.appendChild(card);
    });
}
