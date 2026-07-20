// Token storage, kept tiny and in one place.
//
// We store the bearer token in localStorage so a page refresh doesn't log you
// out. Note the tradeoff: localStorage is readable by any JS on the page, so
// it's vulnerable to XSS. The more secure alternative is an httpOnly cookie
// (which JS can't read) — worth doing if this ever leaves localhost, but it
// requires CSRF protection in return. For a local single-user tool this is the
// reasonable simple choice, and it's a deliberate one rather than an accident.

const KEY = "papertrading.token";

export const getToken = () => localStorage.getItem(KEY);
export const setToken = (t) => localStorage.setItem(KEY, t);
export const clearToken = () => localStorage.removeItem(KEY);
