/* qr-scanner.js — escáner QR compartido sobre html5-qrcode.
   Expone window.QRScanner. Requiere Html5Qrcode (CDN) y Bootstrap. */
(function () {
  'use strict';

  var reader = null;      // instancia Html5Qrcode
  var running = false;
  var config = { mode: 'single', onItem: null };
  var lastText = '';      // debounce de códigos repetidos
  var lastAt = 0;

  function el(id) { return document.getElementById(id); }

  function parseItemId(text) {
    var path;
    try { path = new URL(text, window.location.origin).pathname; }
    catch (e) { path = String(text); }
    var m = path.match(/\/inventario\/(\d+)\//);
    return m ? m[1] : null;
  }

  function notify(message, type) {
    var box = el('qr-notify');
    if (!box) return;
    type = type || 'info';
    var div = document.createElement('div');
    div.className = 'alert alert-' + type + ' py-2 mb-0';
    div.textContent = message;
    box.innerHTML = '';
    box.appendChild(div);
    if (type === 'success' || type === 'info') {
      setTimeout(function () {
        if (box.firstChild) box.innerHTML = '';
      }, 2500);
    }
  }

  function flash(node) {
    if (!node) return;
    node.classList.remove('qr-flash');
    void node.offsetWidth;           // reinicia la animación
    node.classList.add('qr-flash');
    setTimeout(function () { node.classList.remove('qr-flash'); }, 1400);
  }

  function onDecode(decodedText) {
    var now = Date.now();
    if (decodedText === lastText && now - lastAt < 1500) return; // mismo código en cuadro
    lastText = decodedText;
    lastAt = now;

    var id = parseItemId(decodedText);
    if (!id) { notify('QR no reconocido.', 'warning'); return; }
    if (typeof config.onItem === 'function') config.onItem(id);
    if (config.mode === 'single') stop();  // navbar: detener tras un escaneo válido
  }

  function start() {
    var target = el('qr-reader');
    if (!target) return;
    if (!window.isSecureContext) {
      notify('El escáner requiere HTTPS.', 'danger');
      return;
    }
    if (typeof Html5Qrcode === 'undefined') {
      notify('No se pudo cargar el lector de QR.', 'danger');
      return;
    }
    reader = new Html5Qrcode('qr-reader');
    running = true;
    reader.start(
      { facingMode: 'environment' },
      { fps: 10, qrbox: 250 },
      onDecode,
      function () { /* fallo por cuadro: ignorar */ }
    ).catch(function () {
       running = false;
       notify('No se pudo acceder a la cámara. Permití el acceso en tu navegador.', 'danger');
     });
  }

  function stop() {
    if (reader && running) {
      running = false;
      reader.stop().then(function () { reader.clear(); reader = null; })
                   .catch(function () { reader = null; });
    }
  }

  function open(opts) {
    config.mode = (opts && opts.mode) || 'single';
    config.onItem = (opts && opts.onItem) || null;
    lastText = ''; lastAt = 0;
    var box = el('qr-notify'); if (box) box.innerHTML = '';
    var modalEl = el('qrScannerModal');
    if (!modalEl) return;
    bootstrap.Modal.getOrCreateInstance(modalEl).show();
  }

  function close() {
    var modalEl = el('qrScannerModal');
    if (modalEl) bootstrap.Modal.getOrCreateInstance(modalEl).hide();
  }

  // Ciclo de vida ligado al modal
  document.addEventListener('DOMContentLoaded', function () {
    var modalEl = el('qrScannerModal');
    if (modalEl) {
      modalEl.addEventListener('shown.bs.modal', start);
      modalEl.addEventListener('hidden.bs.modal', stop);
    }
    var btn = el('btnQrScan');
    if (btn) {
      btn.addEventListener('click', function () {
        open({ mode: 'single', onItem: function (id) {
          window.location.href = '/inventario/' + id + '/';
        }});
      });
    }
  });

  window.QRScanner = {
    open: open, close: close, notify: notify, flash: flash, parseItemId: parseItemId,
  };
})();
