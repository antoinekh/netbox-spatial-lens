/*
 * What the reader has narrowed a drawing to, kept in the URL hash.
 *
 * The colouring is in the query string, because the server draws it. Picked bands, ticked rows
 * and the find box are the browser's own business, and they used to be lost on every reload and
 * could not be sent to anybody. The hash keeps them without a request, and a copied link opens
 * the drawing narrowed the same way.
 *
 * One key can hold several values (`band-racks=a&band-racks=b`), so a value never has to be
 * escaped against a separator of our own. Loaded before the scripts that use it.
 */
(function () {
  'use strict';

  function params() {
    return new URLSearchParams(window.location.hash.slice(1));
  }

  // A link pasted into a tab that already shows this page changes the hash and loads nothing, so
  // the page is loaded again to read it. Our own writes replace the state and do not fire this.
  window.addEventListener('hashchange', () => window.location.reload());

  window.lensState = {
    get: function (key) {
      return params().getAll(key);
    },
    set: function (key, values) {
      const next = params();
      next.delete(key);
      (values || []).forEach((value) => next.append(key, value));
      const hash = next.toString();
      const url = `${window.location.pathname}${window.location.search}${hash ? `#${hash}` : ''}`;
      window.history.replaceState(window.history.state, '', url);
    },
  };
})();
