/*
 * A PDF chosen for a background layer, turned into a PNG before the form is sent.
 *
 * The server stores images only. An architectural drawing usually arrives as a PDF, so its first
 * page is drawn here with pdf.js and the PNG takes the place of the file in the form. pdf.js
 * loads from the `pdfjs_base` setting, and only when a PDF is chosen.
 */
(function () {
  'use strict';

  const config = JSON.parse(document.getElementById('lens-layer-upload-config').textContent);
  const input = document.querySelector('input[type="file"][name="file"]');
  if (!input) return;

  // The longer side of the PNG, in pixels: enough to read a drawing of a whole hall when zoomed
  // in, and inside what every browser can draw on one canvas.
  const LONG_SIDE = 4096;

  input.accept = '.png,.jpg,.jpeg,.webp,.gif,.pdf,image/png,image/jpeg,image/webp,image/gif,application/pdf';

  const note = document.createElement('div');
  note.className = 'form-text';
  note.setAttribute('role', 'status');
  input.insertAdjacentElement('afterend', note);

  function say(text, failed) {
    note.textContent = text;
    note.classList.toggle('text-danger', Boolean(failed));
  }

  async function firstPage(file) {
    const pdfjs = await import(`${config.pdfjsBase}build/pdf.min.mjs`);
    pdfjs.GlobalWorkerOptions.workerSrc = `${config.pdfjsBase}build/pdf.worker.min.mjs`;
    const pdf = await pdfjs.getDocument({ data: await file.arrayBuffer() }).promise;
    const page = await pdf.getPage(1);
    const natural = page.getViewport({ scale: 1 });
    const viewport = page.getViewport({ scale: LONG_SIDE / Math.max(natural.width, natural.height) });
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(viewport.width);
    canvas.height = Math.round(viewport.height);
    await page.render({ canvasContext: canvas.getContext('2d'), viewport: viewport }).promise;
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'));
    return { blob: blob, pages: pdf.numPages, width: canvas.width, height: canvas.height };
  }

  input.addEventListener('change', async function () {
    const file = input.files[0];
    say('');
    if (!file || !(file.type === 'application/pdf' || /\.pdf$/i.test(file.name))) return;

    if (!config.pdfjsBase) {
      input.value = '';
      return say('PDF conversion is turned off here. Export the PDF to PNG, then choose the PNG.', true);
    }

    const submit = input.form.querySelectorAll('button[type="submit"]');
    submit.forEach((button) => { button.disabled = true; });
    say(`Converting ${file.name}…`);
    try {
      const page = await firstPage(file);
      const files = new DataTransfer();
      files.items.add(new File([page.blob], file.name.replace(/\.pdf$/i, '.png'), { type: 'image/png' }));
      input.files = files.files;
      const of = page.pages > 1 ? `page 1 of ${page.pages}` : 'the page';
      say(`Converted ${of} of ${file.name} to a PNG of ${page.width} × ${page.height} pixels.`);
    } catch (error) {
      input.value = '';
      say(`${file.name} could not be converted. Export the PDF to PNG, then choose the PNG.`, true);
      console.warn('netbox-spatial-lens could not convert the PDF:', error);
    } finally {
      submit.forEach((button) => { button.disabled = false; });
    }
  });
})();
