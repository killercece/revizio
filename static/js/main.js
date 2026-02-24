/**
 * Revizio - Core
 * Theme toggle, burger menu et utilitaires partages.
 */

document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    initBurgerMenu();

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

/**
 * Initialise le menu burger pour mobile.
 */
function initBurgerMenu() {
    const burger = document.getElementById('burger-btn');
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebar-overlay');

    if (!burger || !sidebar || !overlay) return;

    burger.addEventListener('click', () => {
        sidebar.classList.toggle('open');
        overlay.classList.toggle('active');
    });

    overlay.addEventListener('click', () => {
        sidebar.classList.remove('open');
        overlay.classList.remove('active');
    });
}
