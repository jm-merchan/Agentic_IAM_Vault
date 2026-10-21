"""Structured application data stays outside the model's conversation and tools."""
from __future__ import annotations

import base64
import json
import re
import secrets
from uuid import UUID

from .security import AccessDenied
from .telemetry import operation
from .task_agents import task_allows

PROFILE_KEY = 'lumen-applications'
TRANSFORMS = {'dni': 'lumen-dni', 'iban': 'lumen-iban'}
STEPS = ['Tarifa', 'Vivienda', 'Titular', 'Pago', 'Revisión']
DEMO_FORM = {
    'plan_id': 2, 'street': 'Calle del Sol', 'number': '24', 'floor': '2 A',
    'postal_code': '28013', 'city': 'Madrid', 'province': 'Madrid',
    'full_name': 'Alex Ejemplo Laboratorio', 'dni': '12345678Z',
    'email': 'alex@example.invalid', 'phone': '600000000',
    'iban': 'ES9121000418450200051332', 'note': 'Solicitud ficticia de demostración.',
}


def generate_demo_form():
    """Generate synthetic lab suggestions locally, with valid document/check digits."""
    number = secrets.randbelow(100_000_000)
    dni = f'{number:08d}' + 'TRWAGMYFPDXBNJZSQVHLCKE'[number % 23]
    # Use a lab bank code, then calculate the Spanish account and IBAN checks.
    bank_branch = '0000' + f'{secrets.randbelow(10_000):04d}'
    account = f'{secrets.randbelow(10_000_000_000):010d}'

    def account_check(digits):
        check = 11 - sum(int(digit) * weight for digit, weight in
                         zip(digits, (1, 2, 4, 8, 5, 10, 9, 7, 3, 6))) % 11
        return str(0 if check == 11 else 1 if check == 10 else check)

    bban = bank_branch + account_check('00' + bank_branch) + account_check(account) + account
    iban = f'ES{98 - int(bban + "142800") % 97:02d}{bban}'
    name = secrets.choice(('Alex', 'Sam', 'Noa', 'Dani'))
    return {
        **DEMO_FORM,
        'street': secrets.choice(('Calle de la Energía', 'Avenida del Sol', 'Calle del Viento')),
        'number': str(secrets.randbelow(99) + 1),
        'floor': f'{secrets.randbelow(8) + 1} {secrets.choice("ABC")}',
        'full_name': f'{name} Ejemplo Laboratorio',
        'dni': dni,
        'email': f'{name.lower()}.{secrets.token_hex(3)}@example.invalid',
        'phone': '600' + f'{secrets.randbelow(1_000_000):06d}',
        'iban': iban,
    }


def validate_form(data, step=None):
    """Normalize server-side; validate individual steps and the complete submission."""
    out = {k: str(data.get(k, '')).strip() for k in DEMO_FORM if k != 'plan_id'}
    try:
        out['plan_id'] = int(data.get('plan_id', 0))
    except (ValueError, TypeError):
        out['plan_id'] = 0
    if step in (None, 0) and out['plan_id'] not in {1, 2, 3}:
        raise AccessDenied('Selecciona una tarifa del catálogo.')
    if step in (None, 1):
        if not 3 <= len(out['street']) <= 140 or not 1 <= len(out['number']) <= 12:
            raise AccessDenied('Introduce la calle y el número del suministro.')
        if len(out['floor']) > 30 or not re.fullmatch(r'(0[1-9]|[1-4]\d|5[0-2])\d{3}', out['postal_code']):
            raise AccessDenied('Revisa el piso y el código postal español de cinco cifras.')
        if not all(2 <= len(out[k]) <= 80 for k in ('city', 'province')):
            raise AccessDenied('Introduce localidad y provincia.')
    out['dni'] = re.sub(r'[\s-]', '', out['dni']).upper()
    out['phone'] = re.sub(r'[\s()-]', '', out['phone']).removeprefix('+34')
    if step in (None, 2):
        if not 5 <= len(out['full_name']) <= 120:
            raise AccessDenied('Introduce el nombre y los apellidos del titular.')
        doc = out['dni']
        if not re.fullmatch(r'(\d{8}|[XYZ]\d{7})[A-Z]', doc):
            raise AccessDenied('Introduce un DNI o NIE válido, incluida su letra.')
        number = str('XYZ'.index(doc[0])) + doc[1:8] if doc[0] in 'XYZ' else doc[:8]
        if 'TRWAGMYFPDXBNJZSQVHLCKE'[int(number) % 23] != doc[-1]:
            raise AccessDenied('La letra del DNI/NIE no es correcta.')
        if len(out['email']) > 160 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', out['email']):
            raise AccessDenied('Introduce un correo electrónico válido.')
        if not re.fullmatch(r'[6789]\d{8}', out['phone']):
            raise AccessDenied('Introduce un teléfono español de nueve cifras.')
    out['iban'] = re.sub(r'\s', '', out['iban']).upper()
    if step in (None, 3):
        iban = out['iban']
        if not re.fullmatch(r'ES\d{22}', iban):
            raise AccessDenied('Introduce un IBAN español: ES y 22 cifras.')
        rearranged = iban[4:] + iban[:4]
        numeric = ''.join(str(ord(c) - 55) if c.isalpha() else c for c in rearranged)
        if int(numeric) % 97 != 1:
            raise AccessDenied('El IBAN no supera la comprobación de sus dígitos de control.')
    if len(out['note']) > 500:
        raise AccessDenied('La nota puede tener hasta 500 caracteres.')
    return out


def document_hint(value):
    return '••••••' + value[-3:]


def iban_hint(value):
    return value[:2] + '•• •••• •••• •••• •••• ' + value[-4:]


class ApplicationServices:
    def can_reveal(self, session):
        session.require_login()
        return task_allows(session, 'reveal') and bool(set(session.groups).intersection(self.config['runtime']['groups'].get('sensitive', [])))

    async def protected_write(self, session, path, payload):
        token = await self.exchange(session, path, ['update'])
        return (await self.vault_post(path, token, payload))['data']

    @operation('application.save')
    async def save_application(self, session, form, application_id):
        if not task_allows(session, 'write'):
            raise AccessDenied('Este agente no puede crear solicitudes. Selecciona Creación de solicitudes.')
        if self.role(session) != 'readwrite':
            raise AccessDenied('Tu perfil permite consultar solicitudes, pero no guardarlas.')
        try:
            UUID(application_id)
        except (ValueError, TypeError):
            raise AccessDenied('La referencia de la solicitud no es válida.') from None
        data = validate_form(form)
        # A server-issued ID is reused on retry; no duplicate database rows or contracts.
        existing = await self.database(session, 'SELECT application_id FROM energy_applications WHERE application_id=%s AND subject_id=%s', (application_id, session.subject))
        if existing:
            return application_id
        profile = {k: v for k, v in data.items() if k not in {'dni', 'iban', 'plan_id'}}
        encoded = base64.b64encode(json.dumps(profile, ensure_ascii=False).encode()).decode()
        protected = await self.protected_write(session, 'transit/encrypt/' + PROFILE_KEY, {'plaintext': encoded})
        values = {}
        for field, transformation in TRANSFORMS.items():
            result = await self.protected_write(session, 'transform/encode/' + transformation,
                                                {'value': data[field], 'transformation': transformation})
            values[field] = result['encoded_value']
        await self.database(session, '''INSERT INTO energy_applications
            (application_id,subject_id,plan_id,profile_ciphertext,dni_token,iban_token,dni_hint,iban_hint)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE application_id=application_id''',
            (application_id, session.subject, data['plan_id'], protected['ciphertext'],
             values['dni'], values['iban'], document_hint(data['dni']), iban_hint(data['iban'])), write=True)
        self.event(session, 'Solicitud guardada', 'Perfil cifrado y documentos tokenizados · MySQL')
        return application_id

    @operation('application.list_masked')
    async def applications(self, session):
        # Shared lab queue: this projection never retrieves clear personal information.
        return await self.database(session, '''SELECT a.application_id,a.plan_id,a.status,a.created_at,
            a.dni_hint,a.iban_hint,p.name AS plan_name,p.price_kwh
            FROM energy_applications a JOIN energy_plans p ON p.id=a.plan_id
            ORDER BY a.created_at DESC LIMIT 30''')

    @operation('application.reveal')
    async def reveal_application(self, session, application_id):
        self.role(session)
        rows = await self.database(session, '''SELECT profile_ciphertext,dni_token,iban_token
            FROM energy_applications WHERE application_id=%s''', (application_id,))
        if not rows:
            raise AccessDenied('No se ha encontrado la solicitud.')
        # A real OBO request lets Vault enforce denial even when the UI is bypassed.
        row = rows[0]
        result = await self.protected_write(session, 'transit/decrypt/' + PROFILE_KEY,
                                            {'ciphertext': row['profile_ciphertext']})
        profile = json.loads(base64.b64decode(result['plaintext'], validate=True))
        for field, transformation in TRANSFORMS.items():
            decoded = await self.protected_write(session, 'transform/decode/' + transformation,
                                                 {'value': row[field + '_token'], 'transformation': transformation})
            profile[field] = decoded['decoded_value']
        self.event(session, 'Datos revelados', 'Vault ha autorizado descifrado y destokenización mediante OBO')
        return profile
