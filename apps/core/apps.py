from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.core'
    verbose_name = 'Inventario'

    def ready(self):
        # Registrar señales de autenticación (decoradores @receiver)
        import apps.core.signals  # noqa: F401

        # Señal de bloqueo de axes (API propia de axes)
        try:
            from axes.signals import user_locked_out
            from apps.core.signals import on_axes_lockout
            user_locked_out.connect(on_axes_lockout)
        except ImportError:
            pass  # axes no instalado — ignorar silenciosamente
