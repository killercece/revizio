/**
 * Revizio - Francais
 * Parcours adaptatif : accueil (competences) -> exercice -> correction IA -> suite.
 * Tout texte venant du serveur est insere via textContent (jamais innerHTML).
 */

(function () {
    const $ = (id) => document.getElementById(id);
    const SCREENS = ['s-home', 's-loading', 's-exo', 's-feedback', 's-error'];
    const KIND_LABELS = { bilan: 'Bilan', remediation: 'Renforcement' };

    let exercise = null;      // exercice en cours (cote client)
    let lastAnswers = {};     // reponses du dernier essai
    let lastFeedback = null;  // derniere correction

    function el(tag, cls, text) {
        const e = document.createElement(tag);
        if (cls) e.className = cls;
        if (text !== undefined) e.textContent = text;
        return e;
    }

    function show(id) {
        SCREENS.forEach((s) => $(s).classList.toggle('hidden', s !== id));
        window.scrollTo({ top: 0 });
    }

    function loading(title, sub) {
        $('loading-title').textContent = title;
        $('loading-sub').textContent = sub || 'Cela peut prendre quelques secondes.';
        show('s-loading');
    }

    function fail(msg) {
        $('error-msg').textContent = msg;
        show('s-error');
    }

    async function api(url, body) {
        const opts = body === undefined ? {} : {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        };
        const resp = await fetch(url, opts);
        let data = {};
        try { data = await resp.json(); } catch (e) { /* reponse non JSON */ }
        if (!resp.ok) throw new Error(data.error || 'Erreur serveur');
        return data;
    }

    // Generation et correction tournent en tache de fond cote serveur (le reverse
    // proxy coupe a 30 s) : on interroge l'avancement jusqu'au resultat.
    async function apiJob(url, body) {
        const first = await api(url, body);
        if (!first.job) return first;  // reponse immediate (ex. exercice deja en attente)
        const deadline = Date.now() + 200000;
        while (Date.now() < deadline) {
            await new Promise((r) => setTimeout(r, 2000));
            const st = await api(`/api/fr/jobs/${first.job}`);
            if (st.status === 'done') return st.result;
            if (st.status === 'error') throw new Error(st.error);
        }
        throw new Error("L'IA met trop de temps à répondre. Réessaie.");
    }

    function barColor(pct) {
        if (pct >= 70) return 'bg-emerald-500';
        if (pct >= 45) return 'bg-amber-500';
        return 'bg-rose-500';
    }

    // === Accueil ===

    async function loadHome() {
        show('s-home');
        try {
            const ov = await api('/api/fr/overview');
            renderHome(ov);
        } catch (e) {
            $('home-error').textContent = e.message;
            $('home-error').classList.remove('hidden');
        }
    }

    function renderHome(ov) {
        $('profile-text').textContent = ov.profile;
        const started = ov.axes.some((a) => a.skills.some((s) => s.attempts > 0));
        $('btn-next-label').textContent = ov.pending_id
            ? 'Reprendre mon exercice'
            : (started ? 'Exercice suivant' : "Commencer l'entraînement");
        $('btn-bilan').classList.toggle('ring-2', ov.bilan_due);
        $('btn-bilan').classList.toggle('ring-violet-400', ov.bilan_due);
        $('bilan-hint').textContent = ov.bilan_due
            ? 'Un bilan est prêt : il fait le point sur plusieurs compétences à la fois.'
            : `Un bilan se débloque tous les ${ov.bilan_every} exercices (${ov.since_bilan}/${ov.bilan_every}).`;

        const wrap = $('axes');
        wrap.replaceChildren();
        ov.axes.forEach((ax) => {
            const section = el('section');
            const head = el('div', 'flex items-baseline justify-between mb-2');
            head.append(el('h2', 'font-semibold', ax.label),
                        el('span', 'text-xs text-zinc-400', `${ax.mastery} %`));
            section.append(head);
            const grid = el('div', 'grid gap-3 sm:grid-cols-2');
            ax.skills.forEach((s) => grid.append(skillCard(s)));
            section.append(grid);
            wrap.append(section);
        });
    }

    function skillCard(s) {
        const card = el('div', 'rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4');
        const top = el('div', 'flex items-start justify-between gap-2 mb-1');
        top.append(el('h3', 'text-sm font-medium', s.label),
                   el('span', 'text-[11px] font-medium px-2 py-0.5 rounded-full bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300 whitespace-nowrap', `Niv. ${s.level}/6`));
        card.append(top, el('p', 'text-xs text-zinc-500 dark:text-zinc-400 mb-3', s.desc));
        const track = el('div', 'h-1.5 rounded-full bg-zinc-100 dark:bg-zinc-800 overflow-hidden mb-3');
        const fill = el('div', `h-full ${barColor(s.mastery)}`);
        fill.style.width = `${s.mastery}%`;
        track.append(fill);
        card.append(track);
        const btn = el('button', 'text-xs font-medium text-violet-600 dark:text-violet-400 hover:underline', 'Travailler cette compétence');
        btn.type = 'button';
        btn.addEventListener('click', () => startExercise({ skill: s.id, fresh: true }));
        card.append(btn);
        return card;
    }

    // === Exercice ===

    async function startExercise(body) {
        loading('Le professeur prépare ton exercice…');
        try {
            exercise = await apiJob('/api/fr/next', body || {});
            lastAnswers = {};
            renderExercise(false);
        } catch (e) {
            fail(e.message);
        }
    }

    function renderExercise(isRetry) {
        const ex = exercise;
        $('exo-skill').textContent = ex.skill_label;
        $('exo-level').textContent = `Niveau ${ex.level}/6`;
        const kind = KIND_LABELS[ex.kind];
        $('exo-kind').textContent = kind || '';
        $('exo-kind').classList.toggle('hidden', !kind);
        $('exo-title').textContent = ex.titre;
        $('exo-consigne').textContent = ex.consigne;
        $('exo-text').textContent = ex.passage.texte;
        $('exo-source').textContent = ex.passage.original
            ? `${ex.passage.source} (texte écrit par l'IA)`
            : ex.passage.source;
        $('btn-submit').textContent = isRetry ? 'Envoyer ma réponse améliorée' : 'Envoyer pour correction';
        $('exo-error').classList.add('hidden');

        const wrap = $('exo-questions');
        wrap.replaceChildren();
        ex.questions.forEach((q) => {
            const box = el('div', 'rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4');
            box.append(el('p', 'text-sm font-medium mb-2', `${q.id}. ${q.enonce}`));
            const ta = el('textarea', 'w-full rounded-lg border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-950 p-3 text-sm focus:outline-none focus:ring-2 focus:ring-violet-400');
            ta.id = `answer-${q.id}`;
            ta.rows = q.longueur === 'paragraphe' ? 7 : (q.longueur === '1 phrase' ? 2 : 4);
            ta.placeholder = `Ta réponse (${q.longueur})`;
            ta.value = lastAnswers[q.id] || '';
            box.append(ta);

            const row = el('div', 'mt-2');
            if (isRetry && lastFeedback) {
                const r = lastFeedback.questions.find((x) => x.id === q.id);
                if (r && r.indice_retry) {
                    box.append(el('p', 'text-xs text-amber-700 dark:text-amber-300 mb-1', `Piste : ${r.indice_retry}`));
                }
            }
            if (q.indice) {
                const hint = el('p', 'hidden text-xs text-zinc-500 dark:text-zinc-400 mt-1', q.indice);
                const b = el('button', 'text-xs text-violet-600 dark:text-violet-400 hover:underline', 'Un indice ?');
                b.type = 'button';
                b.addEventListener('click', () => { hint.classList.remove('hidden'); b.remove(); });
                row.append(b, hint);
            }
            box.append(row);
            wrap.append(box);
        });
        show('s-exo');
    }

    async function submit() {
        const answers = {};
        exercise.questions.forEach((q) => { answers[q.id] = $(`answer-${q.id}`).value; });
        if (!Object.values(answers).some((a) => a.trim())) {
            $('exo-error').textContent = 'Écris au moins une réponse.';
            $('exo-error').classList.remove('hidden');
            return;
        }
        lastAnswers = answers;
        loading('Correction en cours…', 'Le professeur lit tes réponses avec attention.');
        try {
            lastFeedback = await apiJob(`/api/fr/exercises/${exercise.id}/correct`, { answers });
            renderFeedback(lastFeedback);
        } catch (e) {
            // On garde les reponses : l'eleve peut renvoyer sans rien retaper.
            renderExercise(false);
            $('exo-error').textContent = e.message;
            $('exo-error').classList.remove('hidden');
        }
    }

    // === Correction ===

    function renderFeedback(fb) {
        $('fb-score').textContent = `${fb.score} %`;
        $('fb-score').className = 'text-4xl font-bold mb-1 ' +
            (fb.score >= 70 ? 'text-emerald-600' : (fb.score >= 45 ? 'text-amber-600' : 'text-rose-600'));
        $('fb-label').textContent = fb.attempt_no === 2 ? 'Après amélioration' : 'Premier essai';
        $('fb-strong').textContent = fb.point_fort || '—';
        $('fb-priority').textContent = fb.priorite || '—';
        $('fb-error').classList.add('hidden');

        const levels = $('fb-levels');
        levels.replaceChildren();
        fb.level_changes.forEach((c) => {
            const up = c.to > c.from;
            levels.append(el('div',
                'rounded-lg px-4 py-3 text-sm font-medium ' + (up
                    ? 'bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-300'
                    : 'bg-sky-50 dark:bg-sky-950/30 text-sky-700 dark:text-sky-300'),
                up ? `${c.skill} : niveau ${c.from} → ${c.to}. Les prochains exercices seront plus difficiles.`
                   : `${c.skill} : niveau ${c.from} → ${c.to}. On consolide les bases avec un exercice ciblé.`));
        });

        const qs = $('fb-questions');
        qs.replaceChildren();
        fb.questions.forEach((r) => {
            const q = exercise.questions.find((x) => x.id === r.id);
            const card = el('div', 'rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4');
            const head = el('div', 'flex items-start justify-between gap-3 mb-2');
            head.append(el('p', 'text-sm font-medium', `${r.id}. ${q ? q.enonce : ''}`),
                        el('span', 'text-xs font-semibold whitespace-nowrap ' +
                            (r.score >= 0.7 ? 'text-emerald-600' : (r.score >= 0.45 ? 'text-amber-600' : 'text-rose-600')),
                            `${Math.round(r.score * 100)} %`));
            card.append(head);
            card.append(el('p', 'text-xs text-zinc-500 dark:text-zinc-400 italic mb-2', lastAnswers[r.id] || '(pas de réponse)'));
            card.append(el('p', 'text-sm', r.commentaire));
            qs.append(card);
        });

        const improve = $('fb-improve-list');
        improve.replaceChildren();
        fb.ameliorations.forEach((a) => {
            const card = el('div', 'rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4');
            const was = el('p', 'text-xs text-zinc-500 dark:text-zinc-400 mb-2');
            was.append(document.createTextNode('Tu as écrit : '),
                       el('em', '', `« ${a.extrait} »`),
                       document.createTextNode(a.type === 'tournure' ? '  ·  autre tournure' : '  ·  mot plus précis'));
            card.append(was);
            const props = el('div', 'flex flex-wrap gap-2 mb-2');
            a.propositions.forEach((p) => props.append(
                el('span', 'text-sm px-3 py-1 rounded-full bg-violet-50 dark:bg-violet-950/40 text-violet-700 dark:text-violet-300', p)));
            card.append(props);
            if (a.pourquoi) card.append(el('p', 'text-xs text-zinc-500 dark:text-zinc-400', a.pourquoi));
            improve.append(card);
        });
        $('fb-improve').classList.toggle('hidden', fb.ameliorations.length === 0);

        const spell = $('fb-spell-list');
        spell.replaceChildren();
        fb.orthographe.forEach((f) => {
            const li = el('li');
            li.append(el('span', 'line-through text-rose-600 dark:text-rose-400', f.faute),
                      document.createTextNode(' → '),
                      el('strong', '', f.correction));
            if (f.regle) li.append(el('span', 'block text-xs text-zinc-500 dark:text-zinc-400', f.regle));
            spell.append(li);
        });
        $('fb-spell').classList.toggle('hidden', fb.orthographe.length === 0);

        const words = $('fb-words');
        const list = $('fb-words-list');
        list.replaceChildren();
        fb.mots.forEach((m) => {
            const li = el('li');
            li.append(el('strong', '', m.mot), document.createTextNode(` : ${m.sens || ''}`));
            list.append(li);
        });
        words.classList.toggle('hidden', fb.mots.length === 0);

        showModels(fb.modele);
        $('btn-retry').classList.toggle('hidden', !fb.can_retry);
        $('btn-reveal').classList.toggle('hidden', !!fb.modele || fb.attempt_no === 2);
        show('s-feedback');
    }

    function showModels(modele) {
        const box = $('fb-models');
        box.replaceChildren();
        if (!modele || !modele.length) {
            box.classList.add('hidden');
            return;
        }
        box.append(el('p', 'text-xs font-semibold uppercase tracking-wide text-zinc-500', 'Corrigé modèle'));
        modele.forEach((m) => {
            const card = el('div', 'rounded-xl border border-violet-200 dark:border-violet-900 bg-violet-50 dark:bg-violet-950/30 p-4');
            card.append(el('p', 'text-xs text-violet-700 dark:text-violet-300 mb-1', `Question ${m.id}`),
                        el('p', 'text-sm whitespace-pre-line', m.texte));
            box.append(card);
        });
        box.classList.remove('hidden');
    }

    async function reveal() {
        try {
            const data = await api(`/api/fr/exercises/${exercise.id}/reveal`, {});
            showModels(data.modele);
            $('btn-reveal').classList.add('hidden');
        } catch (e) {
            $('fb-error').textContent = e.message;
            $('fb-error').classList.remove('hidden');
        }
    }

    // === Evenements ===

    $('btn-next').addEventListener('click', () => startExercise({}));
    $('btn-bilan').addEventListener('click', () => startExercise({ bilan: true, fresh: true }));
    $('btn-submit').addEventListener('click', submit);
    $('btn-quit').addEventListener('click', loadHome);
    $('btn-home').addEventListener('click', loadHome);
    $('btn-error-home').addEventListener('click', loadHome);
    $('btn-continue').addEventListener('click', () => startExercise({ fresh: true }));
    $('btn-retry').addEventListener('click', () => renderExercise(true));
    $('btn-reveal').addEventListener('click', reveal);

    loadHome();
})();
