"""Exercise NiceGUI callbacks without a browser or real CIBA notifications."""
import asyncio
from unittest.mock import AsyncMock

import pytest
from nicegui import ui
from nicegui.testing.user_simulation import user_simulation

from app.contracts_ui import contract_controls
from test_contracts import setup


@pytest.mark.asyncio
@pytest.mark.parametrize('language,start,heading,download', [
    ('es','Contratar','Contratar borrador','Descargar contrato PDF'),
    ('en','Finalize contract','Finalize draft contract','Download contract PDF'),
])
async def test_draft_button_opens_ciba_dialog_and_pdf_waits_for_commit(language,start,heading,download):
    manager,session,item=setup()
    item.traces=['a'*32,'b'*32]
    manager.services.contracts=manager
    manager.start=AsyncMock(return_value=item.public())
    confirmed_in_verify=False
    async def confirmed(*args):
        if confirmed_in_verify:
            item.status='ready'
            item.contract_id=item.id
            item.traces.append('c'*32)
        return item.public()
    manager.poll=AsyncMock(side_effect=confirmed)
    async def run_action(name,action):
        return await action()
    def page():
        contract_controls(manager.services,session,lambda:None,run_action,
                          {'application_id':item.application_id,'subject_id':session.subject,
                           'plan_name':'Luz Noche'},language)
    async with user_simulation(page) as user:
        await user.open('/')
        await user.should_see(start)
        user.find(start,kind=ui.button).click()
        await user.should_see(heading)
        await user.should_see(item.binding_message)
        await user.should_not_see(download)
        links=user.find(kind=ui.link).elements
        assert len(links)==1
        assert next(iter(links)).props['href']=='/traces/'+'b'*32
        confirmed_in_verify=True
        await asyncio.sleep(5.2)
        await user.should_see(download)
        await user.should_see('Ver traza de contratación' if language=='es' else 'View contracting trace')
        links=user.find(kind=ui.link).elements
        assert len(links)==1
        assert next(iter(links)).props['href']=='/traces/'+'c'*32
        manager.start.assert_awaited_once_with(session,item.application_id,language)
        user.find('Cerrar' if language=='es' else 'Close',kind=ui.button).click()


@pytest.mark.asyncio
async def test_other_writers_draft_has_no_contract_controls():
    manager,session,item=setup()
    manager.services.contracts=manager
    def page():
        ui.label('Inbox')
        contract_controls(manager.services,session,lambda:None,AsyncMock(),
                          {'application_id':item.application_id,'subject_id':'another-writer',
                           'plan_name':'Luz Noche'},'es')
    async with user_simulation(page) as user:
        await user.open('/')
        await user.should_see('Inbox')
        await user.should_not_see('Contratar')
