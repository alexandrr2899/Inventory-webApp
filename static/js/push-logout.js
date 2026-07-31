(function () {
  'use strict';

  function csrf() {
    var match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : '';
  }

  document.querySelectorAll('.push-logout').forEach(function (link) {
    link.addEventListener('click', function (event) {
      if (!('serviceWorker' in navigator) || !('PushManager' in window)) return;
      event.preventDefault();
      var destination = link.href;
      var finished = false;
      function finish() {
        if (finished) return;
        finished = true;
        window.location.assign(destination);
      }
      // El cierre de sesión nunca debe quedar bloqueado si el service worker o
      // la red no responden.
      window.setTimeout(finish, 1500);
      navigator.serviceWorker.ready.then(function (registration) {
        return registration.pushManager.getSubscription();
      }).then(function (subscription) {
        if (!subscription) return null;
        var endpoint = subscription.endpoint;
        return subscription.unsubscribe().then(function () {
          return fetch(link.dataset.pushUnsubscribeUrl, {
            method: 'POST',
            credentials: 'same-origin',
            keepalive: true,
            headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf()},
            body: JSON.stringify({endpoint: endpoint})
          }).catch(function () {});
        });
      }).catch(function () {}).finally(finish);
    });
  });
})();
