"""Live reproduction of compare -> continue -> choose, for each configured model."""
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from app.agent import reply
from app.security import Identity, Session, load_config
from app.services import Services
from app.telemetry import records_for, span, trace_id


async def main():
    config = load_config()
    identity = Identity(config)
    services = Services(config, identity)
    private = Path(os.environ["MANUAL"])
    destination = Path(os.environ["LUMEN_ROOT"]) / "chatbot/docs/catalogue-verification.json"
    destination.unlink(missing_ok=True)
    checks = []
    turns = []

    def session_for(role, provider):
        tokens = json.loads((private / f"human-{role}.json").read_text())
        claims = identity.validate(tokens["access_token"], config["oidc"]["client_id"])
        id_claims = identity.validate(tokens["id_token"], config["oidc"]["client_id"])
        assert claims["sub"] == id_claims["sub"]
        assert id_claims["nonce"] == (private / f"login-{role}/nonce").read_text()
        return Session("catalogue-" + role + "-" + provider, subject=claims["sub"], name=role,
                       groups=claims["groups"], access_token=tokens["access_token"],
                       expires_at=min(claims["exp"], id_claims["exp"]), model_provider=provider)

    async def turn(session, message, expected_operation):
        with span("lumen.verify.catalogue", **{"model.provider": session.model_provider}):
            tid = trace_id()
            answer = await reply(services, session, message)
        spans = records_for({tid})
        routes = [s["attributes"].get("request.operation") for s in spans
                  if s["name"] == "guardrail.energy_scope"]
        assert expected_operation in routes, (session.model_provider, message, routes)
        queries = [s for s in spans if s["name"] == "mysql.query"]
        if services.role(session) == "readwrite":
            assert queries, "Missing actual catalogue query"
            assert all(s["attributes"]["db.operation.name"] == "SELECT" for s in queries)
        else:
            assert not queries, "Read-only proposal must be rejected before database access"
        assert "debo corregir" not in answer.lower()
        session.messages.extend([{"role": "user", "content": message},
                                 {"role": "assistant", "content": answer}])
        turns.append({"provider": session.model_provider, "role": session.name, "request": message,
                      "answer": answer, "trace_id": tid, "operation": expected_operation,
                      "mysql_selects": len(queries)})
        print(f"{session.model_provider} · {session.name} · {expected_operation}: OK", flush=True)
        return answer

    for provider in ("anthropic", "openai", "xai"):
        writer = session_for("writer", provider)
        await turn(writer, "Compara los planes del catálogo", "catalog")
        assert writer.pending is None
        choice = await turn(writer, "Continuar solicitud", "prepare_request")
        assert writer.pending is None and "Elige el plan" in choice
        answer = await turn(writer, "Luz Equilibrio", "prepare_request")
        assert writer.pending and writer.pending["plan_id"] == 1
        assert "Propuesta preparada" in answer and "Continuar solicitud" in answer
        assert writer.catalogue_evidence and writer.catalogue_evidence["plans"]
        checks.append({"provider": provider, "writer_proposal_backed_by_catalogue": True})
        reader = session_for("reader", provider)
        answer = await turn(reader, "Prepara una solicitud con Luz Equilibrio", "prepare_request")
        assert reader.pending is None and "no preparar ni guardar" in answer
        assert "Continuar solicitud" not in answer
        checks.append({"provider": provider, "reader_cannot_prepare": True})
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "all_passed": True,
              "checks": checks, "turns": turns, "stored_requests": 0}
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"Live verification completed. Report: {destination}")


asyncio.run(main())
