"""Authenticated, same-origin, download of a committed contract PDF."""
import asyncio
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import Response

from .security import AccessDenied
from .telemetry import span, trace_id


def contract_download_router(identity, contracts, cookie, locks):
    router = APIRouter()

    @router.post('/api/contracts/{request_id}/pdf')
    async def download_application_pdf(request: Request, request_id: str):
        headers = {'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'}
        session = identity.sessions.get(request.cookies.get(cookie, ''))
        origin = str(request.base_url).rstrip('/')
        if not session or request.headers.get('X-Lumen-PDF') != '1' or request.headers.get('origin') != origin:
            return Response(status_code=403, headers=headers)
        try:
            if str(UUID(request_id)) != request_id:
                raise ValueError('request ID')
            async with locks.setdefault(session.sid, asyncio.Lock()):
                if identity.sessions.get(session.sid) is not session:
                    return Response(status_code=403, headers=headers)
                session.require_login()
                with span('lumen.contract.download', **{'user.id': session.subject, 'contracts.id': request_id}):
                    session.traces.append(trace_id())
                    session.traces[:] = session.traces[-100:]
                    document = await contracts.download(session, request_id)
                if identity.sessions.get(session.sid) is not session:
                    return Response(status_code=403, headers=headers)
                session.require_login()
            headers['Content-Disposition'] = f'attachment; filename="lumen-{request_id}.pdf"'
            return Response(document, media_type='application/pdf', headers=headers)
        except AccessDenied as exc:
            return Response(str(exc), status_code=403, media_type='text/plain', headers=headers)
        except ValueError:
            return Response(status_code=403, headers=headers)

    return router
