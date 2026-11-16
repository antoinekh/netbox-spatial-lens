/*
 * Zooming into a floor plan, and moving around it once zoomed.
 *
 * The plan is drawn in room centimetres and fitted to the card, which is the right first view and
 * the wrong only one: in a thirty-metre hall a cabinet is a few pixels wide. This changes the SVG
 * viewBox and nothing else, so the racks, the hover card and the editor's own arithmetic (which
 * reads `getScreenCTM`) keep working at any zoom.
 *
 * - The buttons zoom about the centre, and the last one fits the room again.
 * - Ctrl or Cmd with the wheel zooms about the pointer. A plain wheel still scrolls the page.
 * - Once zoomed, dragging moves the plan. A drag that moved is not a click, so it does not open
 *   the rack it started on. In the editor a drag on a rack moves the rack instead.
 */
(function () {
  'use strict';

  // How far in the plan can go, as a multiple of the fitted view.
  const MAX_ZOOM = 12;
  const STEP = 1.4;
  // Pixels a pointer must travel before a press becomes a drag rather than a click.
  const DRAG_THRESHOLD = 4;

  document.querySelectorAll('svg[data-lens-zoomable]').forEach(setup);

  function setup(svg) {
    // Kept as written, because the parsed values are single precision and writing them back
    // turns -38.9 into -38.900001525878906.
    const original = svg.getAttribute('viewBox');
    const base = svg.viewBox.baseVal;
    const home = { x: base.x, y: base.y, w: base.width, h: base.height };
    let view = { ...home };

    function fit() {
      view = { ...home };
      svg.setAttribute('viewBox', original);
      svg.classList.remove('is-zoomed');
    }

    function render() {
      svg.setAttribute('viewBox', `${view.x} ${view.y} ${view.w} ${view.h}`);
      svg.classList.toggle('is-zoomed', view.w < home.w - 1e-6);
    }

    /* Keep the view inside the room's own box: zoomed in, it can move but not leave the plan. */
    function place(x, y, w) {
      const h = (w * home.h) / home.w;
      view = {
        x: Math.min(Math.max(x, home.x), home.x + home.w - w),
        y: Math.min(Math.max(y, home.y), home.y + home.h - h),
        w: w,
        h: h,
      };
      render();
    }

    function zoomAt(factor, cx, cy) {
      const w = Math.min(Math.max(view.w / factor, home.w / MAX_ZOOM), home.w);
      const k = w / view.w;
      place(cx - (cx - view.x) * k, cy - (cy - view.y) * k, w);
    }

    function toPlan(event, matrix) {
      const point = svg.createSVGPoint();
      point.x = event.clientX;
      point.y = event.clientY;
      return point.matrixTransform(matrix || svg.getScreenCTM().inverse());
    }

    const controls = svg.closest('.lens-plan')?.querySelector('[data-lens-zoom-controls]');
    if (controls) {
      controls.addEventListener('click', function (event) {
        const button = event.target.closest('[data-lens-zoom]');
        if (!button) return;
        const action = button.dataset.lensZoom;
        if (action === 'fit') {
          fit();
          return;
        }
        zoomAt(action === 'in' ? STEP : 1 / STEP, view.x + view.w / 2, view.y + view.h / 2);
      });
    }

    svg.addEventListener(
      'wheel',
      function (event) {
        if (!event.ctrlKey && !event.metaKey) return;
        event.preventDefault();
        const point = toPlan(event);
        zoomAt(event.deltaY < 0 ? STEP : 1 / STEP, point.x, point.y);
      },
      { passive: false }
    );

    let drag = null;

    svg.addEventListener('pointerdown', function (event) {
      if (event.button !== 0 || !svg.classList.contains('is-zoomed')) return;
      // The editor drags racks itself.
      if (svg.classList.contains('lens-floor--editing') && event.target.closest('.lens-rack, .lens-calibration')) return;
      // A layer being calibrated is dragged, wherever on it the press lands.
      if (svg.classList.contains('lens-floor--calibrating') && event.target.closest('.lens-layers image')) return;
      drag = {
        id: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        // Measured against the view as it was when the drag began, since the drag changes it.
        matrix: svg.getScreenCTM().inverse(),
        origin: null,
        view: { ...view },
        moved: false,
      };
      drag.origin = toPlan(event, drag.matrix);
    });

    svg.addEventListener('pointermove', function (event) {
      if (!drag || event.pointerId !== drag.id) return;
      if (!drag.moved) {
        if (Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY) < DRAG_THRESHOLD) return;
        drag.moved = true;
        svg.setPointerCapture(event.pointerId);
        svg.classList.add('is-panning');
      }
      const point = toPlan(event, drag.matrix);
      place(drag.view.x - (point.x - drag.origin.x), drag.view.y - (point.y - drag.origin.y), drag.view.w);
    });

    function endDrag(event) {
      if (!drag || event.pointerId !== drag.id) return;
      if (svg.hasPointerCapture(event.pointerId)) svg.releasePointerCapture(event.pointerId);
      svg.classList.remove('is-panning');
      // Swallow the click that ends a drag, so moving the plan never opens a rack.
      if (drag.moved) {
        svg.addEventListener(
          'click',
          function (click) {
            click.preventDefault();
            click.stopPropagation();
          },
          { capture: true, once: true }
        );
      }
      drag = null;
    }

    svg.addEventListener('pointerup', endDrag);
    svg.addEventListener('pointercancel', endDrag);
  }
})();
