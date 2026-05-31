// Authenticated fetch wrapper. Auto-redirects to /login on 401.
window.CSSA = window.CSSA || {};

CSSA.api = (function() {
  async function request(method, path, body = null) {
    const opts = {
      method,
      headers: {},
    };
    const token = CSSA.auth.token();
    if (token) opts.headers['Authorization'] = `Bearer ${token}`;
    if (body !== null) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    const resp = await fetch(path, opts);
    if (resp.status === 401) {
      CSSA.auth.logout();
      throw new Error('unauthenticated');
    }
    if (!resp.ok) {
      let err = `HTTP ${resp.status}`;
      try { const j = await resp.json(); err = j.detail || err; } catch {}
      throw new Error(err);
    }
    if (resp.status === 204) return null;
    return await resp.json();
  }

  return {
    get(path) { return request('GET', path); },
    post(path, body) { return request('POST', path, body); },
    put(path, body) { return request('PUT', path, body); },
    del(path) { return request('DELETE', path); },

    /** Build an MJPEG live-feed URL with token embedded as query param
     *  (necessary because <img src> can't carry headers). */
    streamUrl(sourceId) {
      const token = encodeURIComponent(CSSA.auth.token() || '');
      return `/api/sources/${sourceId}/stream.mjpeg?token=${token}`;
    },
  };
})();
