"""Render catalogue facts and proposal state only after real authorized operations."""
from __future__ import annotations

import re
import unicodedata

from .security import AccessDenied
from .i18n import Translator
from .telemetry import operation


def normalized(value):
    return ' '.join(''.join(
        c for c in unicodedata.normalize('NFD', value.casefold())
        if not unicodedata.combining(c)
    ).split())


def markdown(value):
    return re.sub(r'([\\`*_{}\[\]()#+.!|<>])', r'\\\1', str(value)).replace('\n', ' ')


def price(plan, language='es'):
    return Translator(language).number(plan['price_kwh'])


def table(plans, language='es'):
    t = Translator(language)
    return ('| Plan | €/kWh | ' + t('Descripción') + ' |\n|---|---:|---|\n'
            + '\n'.join(f'| {markdown(p["name"])} | {price(p, language)} | {markdown(t(p["description"]))} |'
                        for p in plans))


@operation('lumen.catalogue.response')
async def catalogue_reply(services, session, decision, language=None):
    t = Translator(language or session.language)
    preparing = decision.operation == 'prepare_request'
    if preparing and services.role(session) != 'readwrite':
        session.pending = None
        return t('Tu perfil permite consultar los planes, pero no preparar ni guardar solicitudes. '
                 'Para tramitar una solicitud de demostración, entra con el usuario escritor.')
    # Every displayed price and every proposal needs a fresh authorized DB read.
    if preparing:
        session.pending = None
    try:
        plans = await services.plans(session)
    except AccessDenied:
        return t('No he podido consultar el catálogo con tus permisos actuales. '
                 'No puedo confirmar precios ni preparar una propuesta. Puedes volver a intentarlo.')
    selected = next((p for p in plans if normalized(p['name']) == normalized(decision.plan_name)), None)
    if not plans:
        return t('El catálogo está vacío. No hay planes disponibles para preparar una propuesta.')
    if decision.plan_name and selected is None:
        return (t('No encuentro ese plan en el catálogo actual. Elige uno de estos planes:')
                + '\n\n' + table(plans, t.language) + '\n\n' + t('Son datos ficticios de demostración.'))
    if not preparing:
        return ('**' + t('Catálogo de demostración') + '**\n\n' + table([selected] if selected else plans, t.language)
                + '\n\n' + t('Precios ficticios consultados ahora en el catálogo.'))
    if selected is None:
        return (t('Elige el plan para tu solicitud:') + '\n\n' + table(plans, t.language)
                + '\n\n' + t('Todavía no hay ninguna propuesta preparada. Son planes ficticios de demostración.'))
    services.prepare_request(session, selected['id'], t('Solicitud de {plan}', plan=selected['name']))
    if not session.pending or session.pending.get('plan_id') != selected['id']:
        raise AccessDenied('No se ha podido preparar la propuesta. Vuelve a intentarlo.')
    return ('**' + t('Propuesta preparada: {plan}', plan=markdown(selected['name'])) + '**\n\n'
            + '- ' + t('Precio') + ': **' + price(selected, t.language) + ' €/kWh**.\n'
            + '- ' + t('Energía renovable') + ': ' + t('Sí' if selected['renewable'] else 'No') + '.\n'
            + '- ' + markdown(t(selected['description'])) + '.\n\n'
            + t('Pulsa **Continuar solicitud** en la tarjeta para abrir el formulario. '
                'Allí podrás completar tus datos y revisar antes de guardar.') + '\n\n'
            + t('Todavía no se ha guardado ninguna solicitud. Es una demostración, sin contratación real.'))
