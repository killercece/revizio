/**
 * Revizio - Core
 * Theme toggle et utilitaires partages entre toutes les pages.
 */

document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    const btnTheme = document.getElementById('btn-theme');
    if (btnTheme) btnTheme.addEventListener('click', toggleTheme);
});

/**
 * Initialise le theme depuis le localStorage.
 */
function initTheme() {
    const theme = localStorage.getItem('theme') || 'light';
    document.documentElement.setAttribute('data-theme', theme);
}

/**
 * Bascule entre theme clair et sombre.
 */
function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme');
    const next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
}
