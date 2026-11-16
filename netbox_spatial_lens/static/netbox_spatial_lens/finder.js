/*
 * Finding one thing among hundreds, and narrowing the drawing to a handful of them.
 *
 * The same behaviour wherever a list is too long to read: a button, a search box under it, and
 * rows you tick. Written once, the way `legend.js` is, and it knows nothing about sites,
 * circuits or cables.
 *
 * A finder declares the group it narrows with `data-lens-finder`, and which data attribute
 * carries identity on the things it narrows with `data-lens-finder-key`. Anything on the page
 * carrying `data-lens-filterable="<that group>"` and that attribute joins in, and recedes when
 * it is not among the picks. Empty means all of them, never none.
 *
 * It composes with the legends rather than competing with them: this owns `is-unfocused`, the
 * legend owns `is-filtered`, and a thing has to survive both to stay lit. Pages that draw
 * somewhere a class cannot reach, such as the map's own canvas layers, listen for
 * `lens:finder` instead, which carries the same decision.
 */
(function () {
  'use strict';

  const finders = document.querySelectorAll('[data-lens-finder]');
  if (!finders.length) return;

  // group -> Set of picked ids, as strings. Empty means "all of them", never "none".
  const picked = new Map();

  /* node -> the Set of finder groups that currently leave it out.
   *
   * A rack can be narrowed by several finders at once: by Tags and by a custom field. It is out
   * of focus while any one of them excludes it, so each finder records its own verdict here
   * rather than setting the shared class, which the next finder would overwrite. */
  const excludedBy = new WeakMap();

  function setExcluded(node, group, excluded) {
    let groups = excludedBy.get(node);
    if (!groups) {
      groups = new Set();
      excludedBy.set(node, groups);
    }
    if (excluded) groups.add(group);
    else groups.delete(group);
    node.classList.toggle('is-unfocused', groups.size > 0);
  }

  function rowsOf(finder) {
    return finder.querySelectorAll('[data-lens-pick]');
  }

  function apply(group) {
    const finder = document.querySelector(`[data-lens-finder="${group}"]`);
    const chosen = picked.get(group);
    const key = finder.dataset.lensFinderKey;

    // An element can belong to several groups (`~=`), and can carry several ids separated by
    // spaces, as a rack carries its tags. It stays in focus if any of its ids is picked.
    document.querySelectorAll(`[data-lens-filterable~="${group}"]`).forEach(function (node) {
      const ids = String(node.dataset.lensPick || (key ? node.dataset[key] : '') || '')
        .split(/\s+/)
        .filter(Boolean);
      setExcluded(node, group, Boolean(chosen.size) && !ids.some((id) => chosen.has(id)));
    });

    rowsOf(finder).forEach(function (row) {
      row.setAttribute('aria-checked', String(chosen.has(row.dataset.lensPick)));
    });
    finder.classList.toggle('is-picking', Boolean(chosen.size));

    summarise(finder);
    finder.querySelector('[data-lens-finder-clear]').hidden = !chosen.size;

    if (window.lensState) window.lensState.set(`pick-${group}`, [...chosen]);

    document.dispatchEvent(
      new CustomEvent('lens:finder', {
        detail: { group: group, picked: [...chosen] },
      })
    );
  }

  /* What the button and the foot of the panel say: how many rows are ticked, or how many the
     legend has left to tick. */
  function summarise(finder) {
    const chosen = picked.get(finder.dataset.lensFinder);
    const rows = [...rowsOf(finder)];
    const total = rows.length;
    const offered = rows.filter((row) => !row.classList.contains('is-filtered')).length;
    // The button says how far the drawing is narrowed while its panel is shut: "2/28" once two
    // rows are ticked, and the plain total when none is.
    const count = finder.querySelector('[data-lens-finder-count]');
    if (count) {
      count.textContent = chosen.size ? `${chosen.size}/${total}` : String(total);
      count.classList.toggle('text-bg-primary', Boolean(chosen.size));
      count.classList.toggle('text-bg-secondary', !chosen.size);
    }
    const noun = finder.dataset.lensFinderNoun || 'row';
    const nouns = `${noun}${total === 1 ? '' : 's'}`;
    let summary = offered < total ? `${offered} of ${total} ${nouns}` : `${total} ${nouns}`;
    if (chosen.size) summary = `${chosen.size} of ${total} picked`;
    finder.querySelector('[data-lens-finder-summary]').textContent = summary;
  }

  // A legend band changes which rows are offered.
  document.addEventListener('lens:filter', () => finders.forEach(summarise));

  function filterRows(finder, term) {
    const needle = term.trim().toLowerCase();
    let shown = 0;
    rowsOf(finder).forEach(function (row) {
      const hit = !needle || (row.dataset.lensName || '').toLowerCase().includes(needle);
      row.classList.toggle('is-hidden', !hit);
      if (hit) shown += 1;
    });
    finder.querySelector('[data-lens-finder-empty]').hidden = shown > 0;
  }

  function closeFinders(except) {
    finders.forEach(function (finder) {
      if (finder === except) return;
      finder.querySelector('[data-lens-finder-panel]').hidden = true;
      finder.querySelector('[data-lens-finder-toggle]').setAttribute('aria-expanded', 'false');
    });
  }

  finders.forEach(function (finder) {
    const group = finder.dataset.lensFinder;
    const toggle = finder.querySelector('[data-lens-finder-toggle]');
    const panel = finder.querySelector('[data-lens-finder-panel]');
    const search = finder.querySelector('[data-lens-finder-search]');
    picked.set(group, new Set());

    toggle.addEventListener('click', function () {
      const open = panel.hidden;
      closeFinders(finder);
      panel.hidden = !open;
      toggle.setAttribute('aria-expanded', String(open));
      // A panel opened to find something should be ready to be typed into.
      if (open) search.focus();
      // Right-aligned if opening it left would run off the edge of the card.
      const box = panel.getBoundingClientRect();
      finder.classList.toggle('lens-finder--right', !open ? false : box.right > window.innerWidth - 8);
    });

    search.addEventListener('input', () => filterRows(finder, search.value));

    finder.addEventListener('click', function (event) {
      if (event.target.closest('.lens-cable__open')) return; // a real link; let it navigate
      const row = event.target.closest('[data-lens-pick]');
      if (!row) return;
      const id = row.dataset.lensPick;
      const chosen = picked.get(group);
      if (chosen.has(id)) chosen.delete(id);
      else chosen.add(id);
      apply(group);
    });

    finder.addEventListener('keydown', function (event) {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      const row = event.target.closest('[data-lens-pick]');
      if (!row) return;
      event.preventDefault();
      row.click();
    });

    finder.querySelector('[data-lens-finder-clear]').addEventListener('click', function () {
      picked.get(group).clear();
      apply(group);
    });
  });

  // Clicking away puts the lists back. They are a way to reach the drawing, not a place to stay.
  document.addEventListener('click', function (event) {
    if (!event.target.closest('[data-lens-finder]')) closeFinders(null);
  });

  // Escape clears here as it does everywhere else in the lens: the lists close and every tick
  // goes, so the drawing is whole again.
  document.addEventListener('keydown', function (event) {
    if (event.key !== 'Escape') return;
    closeFinders(null);
    picked.forEach(function (chosen, group) {
      if (!chosen.size) return;
      chosen.clear();
      apply(group);
    });
  });

  /* Ticks carried in the URL, applied once every script on the page is listening, for the
   * same reason the legend waits (see `legend.js`). Only ids that are still rows are kept. */
  document.addEventListener('DOMContentLoaded', function () {
    if (!window.lensState) return;
    finders.forEach(function (finder) {
      const group = finder.dataset.lensFinder;
      const rows = new Set([...rowsOf(finder)].map((row) => row.dataset.lensPick));
      const wanted = window.lensState.get(`pick-${group}`).filter((id) => rows.has(id));
      if (!wanted.length) return;
      wanted.forEach((id) => picked.get(group).add(id));
      apply(group);
    });
  });

  // Read by the pages that compose a narrowing of their own with this one.
  window.lensFinder = {
    picked: (group) => picked.get(group) || new Set(),
    inFocus: function (group, id) {
      const chosen = picked.get(group);
      return !chosen || !chosen.size || chosen.has(String(id));
    },
  };
})();
