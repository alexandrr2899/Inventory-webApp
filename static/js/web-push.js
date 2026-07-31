(function () {
  'use strict';

  var panel = document.getElementById('webPushPanel');
  if (!panel) return;

  var status = document.getElementById('pushStatus');
  var activate = document.getElementById('pushActivate');
  var deactivate = document.getElementById('pushDeactivate');
  var test = document.getElementById('pushTest');
  var message = document.getElementById('pushMessage');
  var installHint = document.getElementById('pushInstallHint');
  var preferences = document.getElementById('pushPreferences');

  function csrf() {
    var match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : '';
  }

  function post(url, data) {
    return fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf()},
      body: JSON.stringify(data || {})
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (body) {
        if (!response.ok) throw new Error(body.error || 'No se pudo completar la operación.');
        return body;
      });
    });
  }

  function applicationServerKey(value) {
    var padding = '='.repeat((4 - value.length % 4) % 4);
    var base64 = (value + padding).replace(/-/g, '+').replace(/_/g, '/');
    var raw = atob(base64);
    return Uint8Array.from(raw, function (char) { return char.charCodeAt(0); });
  }

  function show(text, kind) {
    if (!message) return;
    message.className = 'alert alert-' + (kind || 'info');
    message.textContent = text;
  }

  function sync(subscription) {
    var enabled = !!subscription;
    status.className = 'badge ' + (enabled ? 'text-bg-success' : 'text-bg-secondary');
    status.textContent = enabled ? 'Activo' : 'Inactivo';
    activate.classList.toggle('d-none', enabled);
    deactivate.classList.toggle('d-none', !enabled);
    test.classList.toggle('d-none', !enabled);
    panel._subscription = subscription || null;
  }

  function subscriptionJSON(subscription) {
    return subscription ? subscription.toJSON() : {};
  }

  var supported = 'serviceWorker' in navigator && 'PushManager' in window &&
                  'Notification' in window;
  if (!supported) {
    status.className = 'badge text-bg-danger';
    status.textContent = 'No compatible';
    activate.disabled = true;
    show('Este navegador no admite Web Push.', 'warning');
    return;
  }

  var isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
  var standalone = window.matchMedia('(display-mode: standalone)').matches ||
                   window.navigator.standalone === true;
  if (isIOS && !standalone) {
    installHint.classList.remove('d-none');
    activate.disabled = true;
  }

  navigator.serviceWorker.ready.then(function (registration) {
    panel._registration = registration;
    return registration.pushManager.getSubscription();
  }).then(sync).catch(function () {
    status.className = 'badge text-bg-danger';
    status.textContent = 'Error';
  });

  activate.addEventListener('click', function () {
    activate.disabled = true;
    Notification.requestPermission().then(function (permission) {
      if (permission !== 'granted') throw new Error('El permiso de notificaciones fue rechazado.');
      return panel._registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: applicationServerKey(panel.dataset.publicKey)
      });
    }).then(function (subscription) {
      return post(panel.dataset.subscribeUrl, subscriptionJSON(subscription))
        .then(function () { sync(subscription); });
    }).then(function () {
      show('Notificaciones activadas en este dispositivo.', 'success');
    }).catch(function (error) {
      show(error.message, 'danger');
    }).finally(function () {
      activate.disabled = false;
    });
  });

  deactivate.addEventListener('click', function () {
    var subscription = panel._subscription;
    if (!subscription) return;
    var data = subscriptionJSON(subscription);
    subscription.unsubscribe().then(function () {
      return post(panel.dataset.unsubscribeUrl, {endpoint: data.endpoint});
    }).then(function () {
      sync(null);
      show('Este dispositivo fue desactivado.', 'success');
    }).catch(function (error) {
      show(error.message, 'danger');
    });
  });

  test.addEventListener('click', function () {
    var data = subscriptionJSON(panel._subscription);
    test.disabled = true;
    post(panel.dataset.testUrl, {endpoint: data.endpoint}).then(function () {
      show('La notificación de prueba fue encolada.', 'success');
    }).catch(function (error) {
      show(error.message, 'danger');
    }).finally(function () {
      test.disabled = false;
    });
  });

  preferences.addEventListener('change', function () {
    var data = {};
    preferences.querySelectorAll('.push-pref').forEach(function (input) {
      data[input.dataset.field] = input.checked;
    });
    post(panel.dataset.preferencesUrl, data).then(function () {
      show('Preferencias guardadas.', 'success');
    }).catch(function (error) {
      show(error.message, 'danger');
    });
  });
})();
