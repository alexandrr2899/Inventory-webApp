(function () {
  var btn = document.getElementById('btnBuscarGlobal');
  var overlay = document.getElementById('buscadorOverlay');
  if (!btn || !overlay) return;

  var input = document.getElementById('buscadorInput');
  var out = document.getElementById('buscadorResultados');
  var url = btn.getAttribute('data-buscar-url');
  var timer = null, filas = [], sel = -1;

  function abrir() {
    overlay.hidden = false;
    input.value = ''; out.innerHTML = ''; filas = []; sel = -1;
    setTimeout(function () { input.focus(); }, 10);
  }
  function cerrar() { overlay.hidden = true; }

  function money(v) {
    return 'L ' + Number(v).toLocaleString('es-HN', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  }

  function fila(opts) {
    var a = document.createElement(opts.href ? 'a' : 'div');
    a.className = 'buscador-row';
    if (opts.href) a.href = opts.href;
    var name = document.createElement('span');
    name.className = 'br-name'; name.textContent = opts.nombre;
    a.appendChild(name);
    if (opts.meta) {
      var m = document.createElement('span');
      m.className = 'br-meta ' + (opts.metaClass || ''); m.textContent = opts.meta;
      a.appendChild(m);
    }
    if (opts.abono) {
      var q = document.createElement('button');
      q.type = 'button'; q.className = 'br-quick'; q.textContent = '+ Abono';
      q.addEventListener('click', function (e) {
        e.preventDefault(); e.stopPropagation(); cerrar();
        document.dispatchEvent(new CustomEvent('buscador:abono',
          {detail: {clienteId: opts.abono.id, nombre: opts.nombre}}));
      });
      a.appendChild(q);
    }
    filas.push(a);
    return a;
  }

  function seccion(titulo) {
    var s = document.createElement('div');
    s.className = 'buscador-sec'; s.textContent = titulo;
    return s;
  }

  function render(data) {
    out.innerHTML = ''; filas = []; sel = -1;
    if (data.clientes.length) {
      out.appendChild(seccion('Clientes'));
      data.clientes.forEach(function (c) {
        out.appendChild(fila({
          nombre: c.nombre, href: c.url,
          meta: Number(c.saldo) > 0 ? 'Debe ' + money(c.saldo) : 'Al día',
          metaClass: Number(c.saldo) > 0 ? 'br-debe' : 'br-ok',
          abono: c.puede_abonar ? {id: c.id} : null,
        }));
      });
    }
    if (data.facturas.length) {
      out.appendChild(seccion('Facturas'));
      data.facturas.forEach(function (f) {
        out.appendChild(fila({
          nombre: '#' + f.numero + ' · ' + f.cliente, href: f.url,
          meta: f.estado, metaClass: 'br-badge',
        }));
      });
    }
    if (!data.clientes.length && !data.facturas.length) {
      var e = document.createElement('div');
      e.className = 'buscador-empty'; e.textContent = 'Sin resultados';
      out.appendChild(e);
    }
  }

  function buscar() {
    var q = input.value.trim();
    if (q.length < 2) { out.innerHTML = ''; filas = []; return; }
    fetch(url + '?q=' + encodeURIComponent(q), {headers: {'X-Requested-With': 'XMLHttpRequest'}})
      .then(function (r) { return r.ok ? r.json() : {clientes: [], facturas: []}; })
      .then(render)
      .catch(function () { out.innerHTML = ''; });
  }

  function mover(d) {
    if (!filas.length) return;
    if (sel >= 0) filas[sel].classList.remove('hl');
    sel = (sel + d + filas.length) % filas.length;
    filas[sel].classList.add('hl');
    filas[sel].scrollIntoView({block: 'nearest'});
  }

  btn.addEventListener('click', abrir);
  overlay.addEventListener('click', function (e) { if (e.target === overlay) cerrar(); });
  input.addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(buscar, 200); });
  input.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { cerrar(); }
    else if (e.key === 'ArrowDown') { e.preventDefault(); mover(1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); mover(-1); }
    else if (e.key === 'Enter' && sel >= 0 && filas[sel].href) { window.location = filas[sel].href; }
  });
  document.addEventListener('keydown', function (e) {
    if (overlay.hidden && (e.key === '/' || ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k'))) {
      var t = document.activeElement;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
      e.preventDefault(); abrir();
    }
  });
})();
