// Auth helpers used across all pages.
// Token is stored in localStorage as 'cssa_token'.

window.CSSA = window.CSSA || {};

CSSA.auth = (function() {
  const TOKEN_KEY = 'cssa_token';
  const USER_KEY = 'cssa_user';

  return {
    token() { return localStorage.getItem(TOKEN_KEY); },
    user() {
      const raw = localStorage.getItem(USER_KEY);
      try { return raw ? JSON.parse(raw) : null; } catch { return null; }
    },
    isAuthenticated() { return !!this.token(); },
    setSession(token, user) {
      localStorage.setItem(TOKEN_KEY, token);
      localStorage.setItem(USER_KEY, JSON.stringify(user || {}));
    },
    logout() {
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(USER_KEY);
      window.location.href = '/login';
    },
    /** Call at the top of any protected page. Redirects to /login if no token. */
    requireAuth() {
      if (!this.isAuthenticated()) {
        window.location.href = '/login?next=' + encodeURIComponent(window.location.pathname);
        return false;
      }
      return true;
    },
    /** Render the sidebar user widget */
    renderUserWidget(containerId) {
      const u = this.user() || {};
      const el = document.getElementById(containerId);
      if (!el) return;
      const initials = (u.full_name || u.email || '?')
        .split(/[\s@]/).filter(Boolean).slice(0, 2)
        .map(s => s[0].toUpperCase()).join('');
      el.innerHTML = `
        <div class="user-row">
          <div class="avatar">${initials || 'U'}</div>
          <div class="who">
            <strong>${u.full_name || 'User'}</strong>
            <span>${u.email || ''} · ${u.role || ''}</span>
          </div>
          <button id="logout-btn" title="Sign out">⏻</button>
        </div>
      `;
      const btn = document.getElementById('logout-btn');
      if (btn) btn.addEventListener('click', () => this.logout());
    },
  };
})();
