"""Autenticación y restricción de métodos para la API interna de Jaime."""

import secrets
from functools import wraps

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt


def _error(code, detail, status):
    payload = {'ok': False, 'error': code}
    if detail:
        payload['detail'] = detail
    return JsonResponse(payload, status=status)


def jaime_read_only(view_func):
    """Acepta exclusivamente GET con el Bearer token dedicado de Jaime."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if request.method != 'GET':
            response = _error(
                'method_not_allowed',
                'Esta API es exclusivamente de consulta y solo acepta GET.',
                405,
            )
            response['Allow'] = 'GET'
            return response

        configured_token = str(getattr(settings, 'JAIME_API_TOKEN', '') or '')
        authorization = request.headers.get('Authorization', '')
        scheme, separator, supplied_token = authorization.partition(' ')
        token_is_valid = (
            bool(configured_token)
            and separator == ' '
            and scheme == 'Bearer'
            and bool(supplied_token)
            and secrets.compare_digest(supplied_token, configured_token)
        )
        if not token_is_valid:
            return _error('unauthorized', None, 401)

        return view_func(request, *args, **kwargs)

    # Solo estas vistas quedan exentas de CSRF. Al ser estrictamente GET, nunca
    # hay una operación de escritura que dependa de esa protección.
    return csrf_exempt(wrapper)
