/**
 * Revizio - Core
 * Theme toggle (class-based pour Tailwind), burger menu.
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
    if (theme === 'dark') {
        document.documentElement.classList.add('dark');
    }
}

/**
 * Bascule entre theme clair et sombre (class "dark" sur <html>).
 */
function toggleTheme() {
    const isDark = document.documentElement.classList.contains('dark');
    if (isDark) {
        document.documentElement.classList.remove('dark');
        localStorage.setItem('theme', 'light');
    } else {
        document.documentElement.classList.add('dark');
        localStorage.setItem('theme', 'dark');
    }
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
        overlay.classList.toggle('hidden');
    });

    overlay.addEventListener('click', () => {
        sidebar.classList.remove('open');
        overlay.classList.add('hidden');
    });
}
