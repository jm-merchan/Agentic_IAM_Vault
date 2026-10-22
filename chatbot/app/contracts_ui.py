"""Writer requests a contract; Verify confirms Validator; MySQL commits before PDF."""
from nicegui import ui
from .i18n import Translator
from .security import AccessDenied

STATUSES={
 'waiting':'Esperando confirmación de Validador en Verify',
 'ready':'Contratación registrada en MySQL. Contrato PDF disponible.',
 'denied':'Validador ha rechazado la contratación. El borrador se conserva.',
 'expired':'La petición ha caducado. El borrador se conserva.',
 'error':'No se ha completado el proceso. Actualiza la bandeja para comprobar si se registró el contrato.',
}

async def download_contract(contract_id, t):
    result=await ui.run_javascript(f'''return await (async () => {{
        const r=await fetch('/api/contracts/{contract_id}/pdf',{{method:'POST',headers:{{'X-Lumen-PDF':'1'}},credentials:'same-origin'}});
        if(!r.ok) return {{ok:false,error:await r.text()}};
        const url=URL.createObjectURL(await r.blob()); const a=document.createElement('a');
        a.href=url; a.download='lumen-contrato-{contract_id}.pdf'; document.body.appendChild(a);
        a.click(); a.remove(); setTimeout(()=>URL.revokeObjectURL(url),10000); return {{ok:true}};
    }})();''',timeout=60)
    if not result or not result.get('ok'):
        ui.notify(t((result or {}).get('error') or 'No se ha podido descargar el contrato.'),type='warning')
        return False
    return True


def contract_controls(services,session,guard,run_action,row,language,*,on_download=None):
    t=Translator(language)
    contracts=services.contracts
    if not contracts.config or not contracts.writer(session) or row.get('subject_id') != session.subject:
        return
    with ui.column().classes('w-full gap-2 mt-3'):
        if row.get('contract_id'):
            ui.label(t('Contratación registrada')+' · '+str(row.get('confirmed_at',''))).classes('text-sm muted')
            async def download():
                guard(); button.disable()
                try:
                    if not await download_contract(row['contract_id'],t):
                        recover.set_visibility(contracts.eligible(session))
                finally:
                    button.enable()
                    if on_download: on_download()
            button=ui.button(t('Descargar contrato PDF'),icon='picture_as_pdf',on_click=download).props('no-caps').classes('primary')
            recover=ui.button(t('Recuperar PDF con CIBA'),icon='refresh',on_click=lambda:begin()).props('flat no-caps')
            recover.set_visibility(False)
        else:
            ui.label(t('Borrador · guardar no formaliza el contrato.')).classes('text-sm muted')
            if not contracts.config.get('enabled'):
                ui.label(t('Contratación CIBA pendiente de la verificación inicial.')).classes('text-sm muted')
                return
            if not contracts.eligible(session):
                ui.label(t('Activa Estándar o Creación de solicitudes para contratar.')).classes('text-sm muted')
                return
            button=ui.button(t('Contratar'),icon='assignment_turned_in',on_click=lambda:begin()).props('no-caps').classes('primary')
            ui.label(t('Validador confirmará en Verify antes de formalizar este borrador.')).classes('text-sm muted')
        for item in contracts.list_for(session):
            if item['application_id']==row['application_id'] and item['status']=='waiting':
                ui.button(t('Ver contratación pendiente'),on_click=lambda rid=item['id']:open_status(rid)).props('flat no-caps')

    async def begin():
        guard();button.disable()
        try:
            item=await run_action('lumen.contract.request',lambda:contracts.start(session,row['application_id'],language))
            open_status(item['id'])
        except AccessDenied as exc: ui.notify(t(str(exc)),type='warning')
        except Exception: ui.notify(t('No se ha podido iniciar la contratación.'),type='negative')
        finally: button.enable()

    def open_status(request_id):
        item=contracts.owned(session,request_id)
        with ui.dialog() as dialog,ui.card().classes('application-dialog'):
            ui.label(t('Contratar borrador')).classes('text-2xl')
            ui.label(row['plan_name']).classes('text-lg')
            ui.label(t('Validador')+': '+contracts.config['validator_username']).classes('text-sm break-all')
            ui.label(t('Comprueba que el mensaje en Verify coincide:')).classes('muted')
            ui.label(item.binding_message).classes('text-lg font-semibold break-all')
            status=ui.label(t(STATUSES[item.status])).props('role=status aria-live=polite')
            with ui.expansion(t('Cómo se autoriza la contratación'),icon='account_tree').classes('w-full'):
                for text in (
                    '1. Writer solicita contratar su borrador. Su credencial habitual no puede formalizarlo.',
                    '2. Verify autentica a Validador mediante CIBA y obtiene su confirmación.',
                    '3. Vault valida ese JWT en auth/ciba-contract/login y emite una credencial MySQL limitada.',
                    '4. MySQL ejecuta formalize y guarda status = contratada. Repetir no crea otro contrato.',
                    '5. El PDF se publica después del commit. Writer lo descarga con OBO desde su espacio de contratos.'):
                    ui.label(t(text)).classes('text-sm')
                ui.label(t('CIBA no amplía los permisos habituales de Writer. Esta operación usa una identidad y una credencial separadas.')).classes('text-sm muted')
                ui.label(t('Caduca en un máximo de diez minutos. Cerrar esta ventana detiene la consulta; puedes volver a abrirla.')).classes('text-sm muted')
            links=ui.column().classes('w-full gap-1')
            def show_trace():
                links.clear()
                tid=next((tid for tid in reversed(item.traces) if tid),None)
                if tid:
                    label='Ver traza de contratación' if item.status=='ready' else 'Ver última traza CIBA'
                    with links:
                        ui.link(t(label),'/traces/'+tid,new_tab=True)
            show_trace()
            async def refresh():
                try:
                    guard()
                    result=await run_action('lumen.contract.confirm',lambda:contracts.poll(session,request_id))
                    status.set_text(t(STATUSES[result['status']]))
                    download.set_visibility(result['status']=='ready')
                    if result['status']!='waiting': timer.deactivate()
                except AccessDenied as exc:
                    timer.deactivate();status.set_text(t(str(exc)))
                except Exception:
                    timer.deactivate();status.set_text(t(STATUSES['error']))
                finally:
                    show_trace()
            async def download_now():
                guard()
                download.disable()
                try: await download_contract(item.contract_id,t)
                finally:
                    download.enable()
                    if on_download: on_download()
            download=ui.button(t('Descargar contrato PDF'),icon='picture_as_pdf',on_click=download_now).props('no-caps').classes('primary')
            download.set_visibility(item.status=='ready')
            ui.button(t('Volver a la bandeja'),on_click=lambda:ui.navigate.to('/solicitudes')).props('flat no-caps')
            ui.button(t('Cerrar'),on_click=dialog.close).props('flat no-caps')
            timer=ui.timer(5,refresh,active=item.status=='waiting')
        dialog.on('hide',lambda:(timer.deactivate(),dialog.delete()))
        dialog.open()
