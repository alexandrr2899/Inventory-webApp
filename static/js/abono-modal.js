// Totalizador del reparto: muestra en vivo cuánto se repartió a mano y cuánto resto
// queda (que el servidor auto-reparte por antigüedad o deja como saldo a favor).
// Vive fuera del IIFE del modal porque el formulario también se usa como página.
(function () {
  function fmt(n) {
    return 'L ' + n.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  }

  function refrescar(form) {
    var tabla = form.querySelector('[data-abono-reparto]');
    if (!tabla) return;
    var celdaTotal = tabla.querySelector('[data-abono-total]');
    var celdaResto = tabla.querySelector('[data-abono-resto]');
    if (!celdaTotal || !celdaResto) return;

    var total = 0;
    tabla.querySelectorAll('[data-abono-aplicar]').forEach(function (input) {
      var valor = parseFloat(input.value);
      if (isNaN(valor)) { input.classList.remove('is-invalid'); return; }
      total += valor;
      var max = parseFloat(input.getAttribute('max'));
      input.classList.toggle('is-invalid', !isNaN(max) && valor > max);
    });

    var monto = parseFloat((form.querySelector('[name="monto"]') || {}).value);
    if (isNaN(monto)) monto = 0;
    var resto = monto - total;
    celdaTotal.textContent = fmt(total);
    celdaTotal.classList.toggle('text-danger', resto < 0);
    celdaResto.textContent = resto < 0 ? fmt(resto) + ' (te pasaste)' : fmt(resto);
    celdaResto.classList.toggle('text-danger', resto < 0);
  }

  window.abonoRefrescarTotales = function () {
    document.querySelectorAll('form[data-abono-form]').forEach(refrescar);
  };

  document.addEventListener('input', function (e) {
    var form = e.target.closest('form[data-abono-form]');
    if (form && e.target.matches('[data-abono-aplicar], [name="monto"]')) refrescar(form);
  });
  document.addEventListener('DOMContentLoaded', window.abonoRefrescarTotales);
})();

(function () {
  var modalEl = document.getElementById('abonoModal');
  if (!modalEl || !window.bootstrap) return;

  var content = document.getElementById('abonoModalContent');
  var bsModal = new bootstrap.Modal(modalEl);
  // base URL con pk=0 en el medio (…/clientes/0/abono/); se reemplaza por el id real.
  var baseUrl = modalEl.getAttribute('data-abono-base-url');

  function urlFor(id) { return baseUrl.replace('/0/', '/' + id + '/'); }

  function csrf() {
    var m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? m[1] : '';
  }

  function limpiarErrores(form) {
    form.querySelectorAll('.js-abono-error').forEach(function (n) { n.remove(); });
  }

  function mostrarErrores(form, errors) {
    limpiarErrores(form);
    Object.keys(errors).forEach(function (campo) {
      var input = form.querySelector('[name="' + campo + '"]');
      var msg = document.createElement('div');
      msg.className = 'text-danger small js-abono-error';
      msg.textContent = errors[campo].join(' ');
      if (input && input.parentNode) input.parentNode.appendChild(msg);
      else form.prepend(msg);  // errores no ligados a un campo (p. ej. __all__)
    });
  }

  function wireForm() {
    var form = content.querySelector('form[data-abono-form]');
    if (!form) return;
    var cancel = content.querySelector('[data-abono-cancel]');
    if (cancel) cancel.addEventListener('click', function (e) { e.preventDefault(); bsModal.hide(); });
    if (window.abonoRefrescarTotales) window.abonoRefrescarTotales();
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var fd = new FormData(form);
      fetch(form.action, {
        method: 'POST', body: fd,
        headers: {'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': csrf()},
      }).then(function (r) {
        return r.json().then(function (data) { return {ok: r.ok, data: data}; });
      }).then(function (res) {
        if (res.ok && res.data.ok) {
          bsModal.hide();
          if (window.recargarTabCliente) window.recargarTabCliente();
          else window.location.reload();
        } else {
          // Mostrar los errores del formulario inline, conservando lo tipeado.
          mostrarErrores(form, (res.data && res.data.errors) || {});
        }
      }).catch(function () { alert('No se pudo registrar el abono.'); });
    });
  }

  window.abrirAbono = function (clienteId) {
    fetch(urlFor(clienteId), {headers: {'X-Requested-With': 'XMLHttpRequest'}})
      .then(function (r) { return r.text(); })
      .then(function (html) { content.innerHTML = html; bsModal.show(); wireForm(); })
      .catch(function () { alert('No se pudo abrir el abono.'); });
  };

  document.addEventListener('buscador:abono', function (e) {
    window.abrirAbono(e.detail.clienteId);
  });
  document.addEventListener('click', function (e) {
    var t = e.target.closest('[data-abrir-abono]');
    if (t) { e.preventDefault(); window.abrirAbono(t.getAttribute('data-abrir-abono')); }
  });
})();
