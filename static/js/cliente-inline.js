(function () {
  var modalEl = document.getElementById('cliente-inline-modal');
  var form = document.getElementById('cliente-inline-form');
  if (!modalEl || !form || !window.bootstrap) return;

  var modal = new bootstrap.Modal(modalEl);
  var endpoint = modalEl.dataset.url;
  var targetSelect = null;
  var pendingDuplicate = null;
  var duplicateBox = document.getElementById('cliente-modal-duplicado');
  var duplicateName = modalEl.querySelector('[data-duplicado-nombre]');
  var alertBox = document.getElementById('cliente-modal-aviso');
  var submitButton = document.getElementById('cliente-inline-submit');
  var useExistingButton = document.getElementById('cliente-usar-existente');
  var forceButton = document.getElementById('cliente-forzar-creacion');
  var nameInput = document.getElementById('cliente-inline-nombre');

  function getCookie(name) {
    var value = '; ' + document.cookie;
    var parts = value.split('; ' + name + '=');
    if (parts.length === 2) return parts.pop().split(';').shift();
    return '';
  }

  function clearFeedback() {
    alertBox.classList.add('d-none');
    alertBox.textContent = '';
    duplicateBox.classList.add('d-none');
    if (duplicateName) duplicateName.textContent = '';
    pendingDuplicate = null;
    form.querySelectorAll('.is-invalid').forEach(function (el) {
      el.classList.remove('is-invalid');
    });
    form.querySelectorAll('[data-error-for]').forEach(function (el) {
      el.textContent = '';
    });
  }

  function resetModal() {
    form.reset();
    clearFeedback();
    if (submitButton) submitButton.disabled = false;
  }

  function showAlert(message) {
    alertBox.textContent = message;
    alertBox.classList.remove('d-none');
  }

  function setFieldErrors(errors) {
    Object.keys(errors || {}).forEach(function (field) {
      var feedback = form.querySelector('[data-error-for="' + field + '"]');
      var input = form.querySelector('[name="' + field + '"]');
      var messages = errors[field] || [];
      if (feedback && input) {
        feedback.textContent = messages.join(' ');
        input.classList.add('is-invalid');
      } else if (messages.length) {
        showAlert(messages.join(' '));
      }
    });
  }

  function optionExists(select, id) {
    return Array.prototype.some.call(select.options, function (option) {
      return option.value === String(id);
    });
  }

  function insertOptionAlphabetically(select, option) {
    var inserted = false;
    Array.prototype.some.call(select.options, function (existing) {
      if (!existing.value) return false;
      if (option.text.localeCompare(existing.text, 'es', { sensitivity: 'base' }) < 0) {
        select.insertBefore(option, existing);
        inserted = true;
        return true;
      }
      return false;
    });
    if (!inserted) select.appendChild(option);
  }

  function addClienteToSelects(cliente) {
    document.querySelectorAll('select.cliente-select').forEach(function (select) {
      if (optionExists(select, cliente.id)) return;
      var option = new Option(cliente.nombre, cliente.id);
      insertOptionAlphabetically(select, option);
    });
  }

  function selectCliente(cliente) {
    if (!targetSelect) return;
    addClienteToSelects(cliente);
    targetSelect.value = String(cliente.id);
    targetSelect.dispatchEvent(new Event('change', { bubbles: true }));
    modal.hide();
  }

  function formBody(force) {
    var body = new URLSearchParams(new FormData(form));
    if (force) body.set('forzar', '1');
    return body;
  }

  function submit(force) {
    clearFeedback();
    if (submitButton) submitButton.disabled = true;
    fetch(endpoint, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'X-CSRFToken': getCookie('csrftoken') },
      body: formBody(force)
    }).then(function (response) {
      return response.json().catch(function () {
        return {};
      }).then(function (data) {
        return { status: response.status, data: data };
      });
    }).then(function (result) {
      if (result.status === 201 && result.data.ok && result.data.cliente) {
        selectCliente(result.data.cliente);
        return;
      }
      if (result.status === 200 && result.data.duplicado) {
        pendingDuplicate = result.data.duplicado;
        if (duplicateName) duplicateName.textContent = pendingDuplicate.nombre;
        duplicateBox.classList.remove('d-none');
        return;
      }
      if (result.status === 400 && result.data.errors) {
        setFieldErrors(result.data.errors);
        return;
      }
      showAlert('No se pudo crear el cliente.');
    }).catch(function () {
      showAlert('No se pudo crear el cliente.');
    }).finally(function () {
      if (submitButton) submitButton.disabled = false;
    });
  }

  document.querySelectorAll('[data-cliente-inline][data-target]').forEach(function (button) {
    button.addEventListener('click', function () {
      targetSelect = document.getElementById(button.dataset.target);
      resetModal();
      modal.show();
    });
  });

  modalEl.addEventListener('shown.bs.modal', function () {
    if (nameInput) nameInput.focus();
  });

  form.addEventListener('submit', function (event) {
    event.preventDefault();
    submit(false);
  });

  if (useExistingButton) {
    useExistingButton.addEventListener('click', function () {
      if (pendingDuplicate) selectCliente(pendingDuplicate);
    });
  }

  if (forceButton) {
    forceButton.addEventListener('click', function () {
      submit(true);
    });
  }
})();
