/*
 * Floor plan: the switch between the 3D room and the 2D plan, hovering the plan, finding a rack
 * by name, and the rack table under both.
 *
 * Picking a legend band is not here. It is the same behaviour on all three levels and lives in
 * legend.js, driven by data attributes; this file only has to compose with it, which it does by
 * owning a different class. The band recedes a rack with `is-filtered`, the search with
 * `is-searched-out`, and a rack is on show when it carries neither. Neither has to know the
 * other exists. The table rows carry the same attributes as the racks, so both narrowings reach
 * them too, and there they hide the row rather than fade it.
 *
 * Everything the card can say is already in the markup. A rack carries its name, its overlay
 * reading and the facts behind it on its own data attributes, so hovering costs no request and
 * works the same whether the page was rendered a second ago or came back from the cache.
 */
(function () {
  'use strict';

  const svg = document.querySelector('.lens-floor');
  if (!svg) return;

  const plan = document.querySelector('[data-lens-plan]');
  const hover = document.querySelector('[data-lens-hover]');
  const find = document.querySelector('[data-lens-find]');
  // The box, not the input inside it: the stylesheet draws the warning on the bordered label.
  const findBox = find ? find.closest('.lens-find') : null;
  const racks = Array.from(svg.querySelectorAll('.lens-rack'));
  const table = document.querySelector('[data-lens-rack-table]');
  const rows = table ? Array.from(table.querySelectorAll('tbody tr')) : [];
  const rowCount = document.querySelector('[data-lens-rack-count]');
  // The cabling on the plan: a run names its two racks, an exit the one rack it leaves.
  const cabling = Array.from(svg.querySelectorAll('.lens-floor-run, .lens-floor-exit'));
  const rackById = new Map(racks.map((rack) => [rack.dataset.rackId, rack]));

  let term = '';
  const searchHandlers = [];

  function esc(value) {
    const node = document.createElement('span');
    node.textContent = value == null ? '' : String(value);
    return node.innerHTML;
  }

  /* ----------------------------------------------------------------------
   * Finding a rack
   * ------------------------------------------------------------------- */

  // A name or an asset tag: the label on the cabinet, or the sticker on its door.
  function matches(name, assetTag) {
    return !term || (name || '').toLowerCase().includes(term) || (assetTag || '').toLowerCase().includes(term);
  }

  function applySearch() {
    svg.classList.toggle('lens-floor--filtering', Boolean(term));
    racks.concat(rows).forEach(function (node) {
      node.classList.toggle('is-searched-out', !matches(node.dataset.name, node.dataset.assetTag));
    });
    if (window.lensState) window.lensState.set('find', term ? [term] : []);
    searchHandlers.forEach((handler) => handler(term));
    report();
  }

  // What survives all three narrowings: the legend band, the find box and the Tags finder.
  function receded(node) {
    return ['is-filtered', 'is-searched-out', 'is-unfocused'].some((name) => node.classList.contains(name));
  }

  function shown(nodes) {
    return nodes.filter((node) => !receded(node));
  }

  /* Whether anything is left after both filters, and how many rows the table still holds.
   *
   * Counted over the two classes together rather than over the search alone: with a band picked
   * and a name typed, a search that matches only racks in another band leaves the room empty,
   * and the box has to say so or it looks like a plan that failed to load. */
  function report() {
    // A cable recedes unless every rack it joins is on show, which is the rule the 3D room keeps.
    cabling.forEach(function (line) {
      const ends = [line.dataset.rackA, line.dataset.rackB, line.dataset.rackId].filter(Boolean);
      line.classList.toggle('is-receded', ends.some((id) => !rackById.has(id) || receded(rackById.get(id))));
    });
    if (findBox) findBox.classList.toggle('is-empty', Boolean(term) && shown(racks).length === 0);
    if (rowCount) {
      const visible = shown(rows).length;
      rowCount.textContent = visible === rows.length ? String(rows.length) : `${visible} of ${rows.length}`;
    }
  }

  if (find) {
    find.addEventListener('input', function () {
      term = find.value.trim().toLowerCase();
      applySearch();
    });
    // A term carried in the URL, from a reload or a shared link.
    term = ((window.lensState && window.lensState.get('find')[0]) || '').trim().toLowerCase();
    find.value = term;
  }

  // A band was picked or cleared, so the "nothing matches" message and the row count may have
  // changed even though the term did not.
  document.addEventListener('lens:filter', function (event) {
    if (event.detail.group === 'racks') report();
  });

  // Tags, or a custom field offered as a filter: any finder on this page narrows the racks.
  document.addEventListener('lens:finder', report);

  document.addEventListener('keydown', function (event) {
    if (event.key !== 'Escape' || !term) return;
    term = '';
    if (find) find.value = '';
    applySearch();
  });

  /* ----------------------------------------------------------------------
   * Sorting the table
   *
   * Every cell that sorts carries its value in `data-sort-value`, so a column of "38% · 12U
   * free" sorts on 38 rather than on its text. Names sort naturally, so R2 comes before R10, and
   * an empty value sorts last whichever way round, because "no data" is never the answer to
   * "which is fullest" or "which is emptiest".
   * ------------------------------------------------------------------- */

  function sortBy(header) {
    const headers = Array.from(header.parentNode.children);
    const index = headers.indexOf(header);
    const direction = header.getAttribute('aria-sort') === 'ascending' ? 'descending' : 'ascending';
    const numeric = header.dataset.sort === 'number';
    headers.forEach((th) => th.dataset.sort && th.setAttribute('aria-sort', 'none'));
    header.setAttribute('aria-sort', direction);

    const valueOf = (row) => row.children[index].dataset.sortValue || '';
    const sign = direction === 'ascending' ? 1 : -1;
    rows.sort(function (a, b) {
      const x = valueOf(a);
      const y = valueOf(b);
      if (!x || !y) return x === y ? 0 : x ? -1 : 1;
      const order = numeric ? Number(x) - Number(y) : x.localeCompare(y, undefined, { numeric: true });
      return order * sign;
    });
    const body = table.tBodies[0];
    rows.forEach((row) => body.appendChild(row));
  }

  if (table) {
    table.querySelectorAll('th[data-sort] button').forEach(function (button) {
      button.addEventListener('click', () => sortBy(button.closest('th')));
    });
  }

  /* ----------------------------------------------------------------------
   * The hover card
   * ------------------------------------------------------------------- */

  /* What hovering a rack shows.
   *
   * The same card the world map uses, for the same reason: at plan scale a cabinet is a box with
   * a name in it, and "which of these is the one I want" is not answered by a name. The facts
   * come from the server already filtered to what is recorded, so a sparse inventory shows a
   * short card rather than a column of dashes.
   */
  function cardFor(rack) {
    let facts = [];
    try {
      facts = JSON.parse(rack.dataset.facts || '[]');
    } catch (error) {
      facts = [];
    }
    const rows = facts
      .map(([label, value]) => `<tr><th>${esc(label)}</th><td>${esc(value)}</td></tr>`)
      .join('');
    const reading = rack.dataset.value
      ? `<div class="lens-card__reading"><span class="lens-swatch" style="background: ${esc(
          rack.dataset.colour
        )};"></span>${esc(rack.dataset.value)}</div>`
      : '';
    return (
      `<div class="lens-card__head"><strong>${esc(rack.dataset.name)}</strong></div>` +
      reading +
      (rows ? `<table class="lens-card__facts">${rows}</table>` : '') +
      '<div class="lens-card__action">Click to look inside</div>'
    );
  }

  /* Place the card beside the rack, inside the plan.
   *
   * Measured against the plan rather than the page, so scrolling does not leave it behind, and
   * flipped to the other side when it would run off an edge: a rack against the right-hand wall
   * is exactly the one whose card would otherwise be half off screen. */
  function place(rack) {
    const box = rack.getBoundingClientRect();
    const frame = plan.getBoundingClientRect();
    const card = hover.getBoundingClientRect();
    const gap = 12;

    let left = box.right - frame.left + gap;
    if (left + card.width > frame.width) left = box.left - frame.left - card.width - gap;
    left = Math.max(0, Math.min(left, frame.width - card.width));

    let top = box.top - frame.top + box.height / 2 - card.height / 2;
    top = Math.max(0, Math.min(top, frame.height - card.height));

    hover.style.left = `${left}px`;
    hover.style.top = `${top}px`;
  }

  /* Light the cabling of one rack, or of none: its runs to other racks and its exits. */
  function lightCabling(rack) {
    const id = rack ? rack.dataset.rackId : null;
    cabling.forEach(function (line) {
      const ends = [line.dataset.rackA, line.dataset.rackB, line.dataset.rackId];
      line.classList.toggle('is-lit', id !== null && ends.includes(id));
    });
  }

  function show(rack) {
    hover.innerHTML = cardFor(rack);
    hover.hidden = false;
    // Placed after the content is in, so the measurement is of the card that will be shown
    // rather than of the one before it.
    place(rack);
    lightCabling(rack);
  }

  function hide() {
    hover.hidden = true;
    lightCabling(null);
  }

  /* The rack an event is about. Keyboard focus lands on the link around the rack rather than on
   * the rack itself, so a focus event is looked up inside its target as well as above it. */
  function rackOf(target) {
    return target.closest('.lens-rack') || (target.querySelector ? target.querySelector('.lens-rack') : null);
  }

  if (hover && plan) {
    svg.addEventListener('pointerover', function (event) {
      const rack = event.target.closest('.lens-rack');
      if (rack && !receded(rack) && !svg.classList.contains('is-panning')) show(rack);
    });
    svg.addEventListener('pointerout', function (event) {
      const rack = event.target.closest('.lens-rack');
      if (rack && !rack.contains(event.relatedTarget)) hide();
    });
    // The keyboard gets the same card: a plan whose detail is only reachable with a pointer is a
    // plan half the people using it cannot read.
    svg.addEventListener('focusin', function (event) {
      const rack = rackOf(event.target);
      if (rack) show(rack);
    });
    svg.addEventListener('focusout', hide);
    svg.addEventListener('pointerleave', hide);
  }

  /* ----------------------------------------------------------------------
   * 3D or 2D
   *
   * Both are on the page from the start, so switching costs no request and keeps everything the
   * reader has narrowed: the legend, the finders and the find box act on the plan's racks and
   * on the table, and the 3D room reads the same picks. The choice is kept in the URL hash with
   * the rest, so a reload or a shared link opens the same view.
   * ------------------------------------------------------------------- */

  const views = document.querySelectorAll('[data-lens-floor-panel]');
  const switches = document.querySelectorAll('[data-lens-floor-view]');

  /* Show one view. `keep` records it in the URL; a view the page fell back to is not the
     reader's choice, and keeping it would open the plan again after 3D has been fixed. */
  function showView(name, { keep = true } = {}) {
    views.forEach((view) => (view.hidden = view.dataset.lensFloorPanel !== name));
    switches.forEach(function (button) {
      const on = button.dataset.lensFloorView === name;
      button.classList.toggle('active', on);
      button.setAttribute('aria-pressed', String(on));
    });
    if (keep && window.lensState) window.lensState.set('view', name === '2d' ? ['2d'] : []);
    if (hover) hide();
  }

  switches.forEach(function (button) {
    button.addEventListener('click', () => showView(button.dataset.lensFloorView));
  });

  // Read by the 3D room, which draws on a canvas the classes above cannot reach.
  window.lensFloor = {
    searchTerm: () => term,
    onSearch: (handler) => searchHandlers.push(handler),
    matchesSearch: matches,
    /* The 3D room could not be drawn. The plan takes its place, and the 3D button keeps the
       reason, so the switch does not look broken. */
    unavailable(reason) {
      switches.forEach(function (button) {
        if (button.dataset.lensFloorView !== '3d') return;
        button.disabled = true;
        button.title = reason;
      });
      showView('2d', { keep: false });
    },
  };

  showView(window.lensState && window.lensState.get('view')[0] === '2d' ? '2d' : '3d');
  applySearch();
})();
