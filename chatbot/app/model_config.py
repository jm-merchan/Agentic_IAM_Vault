"""Server-owned provider profiles; a session stores only a provider identifier."""
from .security import AccessDenied

PROVIDER_LABELS = {'openai': 'OpenAI', 'xai': 'xAI', 'anthropic': 'Claude'}


def model_profiles(config):
    if 'models' in config:
        return config['models']
    legacy = config.get('model', {})
    provider = legacy.get('provider')
    return {provider: legacy} if provider in PROVIDER_LABELS else {}


def model_config(config, provider=None):
    provider = provider or config.get('model', {}).get('provider')
    profiles = model_profiles(config)
    if provider not in PROVIDER_LABELS or provider not in profiles:
        raise AccessDenied('Este proveedor todavía no está configurado. Elige otro en el banner.')
    profile = profiles[provider]
    if profile.get('provider') != provider:
        raise AccessDenied('La configuración del proveedor no coincide con su identidad.')
    return dict(profile)


def select_provider(config, session, provider):
    session.require_login()
    if provider not in PROVIDER_LABELS:
        raise AccessDenied('El proveedor seleccionado no está soportado.')
    model_config(config, provider)
    session.model_provider = provider
