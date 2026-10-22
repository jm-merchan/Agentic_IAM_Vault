"""One operator-selected step per invocation; no Markdown extraction or auto-rebuild."""
import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Step:
    id: str
    title: str
    effect: str
    command: tuple
    chapter: str


def step(key, title, effect, script, chapter, *args):
    return Step(key, title, effect, ("bash", script, *args), chapter)


STEPS = (
    step("entorno", "Comprobar entorno", "Comprueba herramientas, entradas y motor de contenedores; todavía no exige IDs WIF.", "scripts/manual/guided-actions.sh", "00-entorno", "entorno"),
    step("vault", "Preparar Vault", "Crea o reutiliza Vault en workshop; inicia, desbloquea y comprueba licencia y conexión local.", "scripts/demo/vault.sh", "01-vault"),
    step("mysql", "Preparar MySQL y KMIP", "Crea o reutiliza MySQL Enterprise y su conexión KMIP; comprueba la contraseña configurada.", "scripts/demo/mysql.sh", "02-mysql"),
    step("credenciales", "Importar entradas en Vault", "Copia las entradas de .env a verify/secrets. Conserva las contraseñas de usuarios que ya están guardadas.", "scripts/demo/bootstrap.sh", "00-entorno"),
    step("verify-base", "Configurar RAR y perfil OAuth", "Obtiene un token administrativo nuevo; comprueba o crea vault:path_access y configura el perfil OAuth de Vault.", "verify/scripts/configure-base.sh", "03-verify"),
    step("oidc", "Configurar aplicación OIDC", "Reutiliza o crea vault-chatbot-oidc, configura PKCE y may_act y guarda sus credenciales en Vault.", "chatbot/scripts/02-verify-apps.sh", "03-verify", "oidc"),
    step("research", "Configurar aplicación research", "Reutiliza o crea vault-chatbot-research y guarda sus credenciales en Vault.", "chatbot/scripts/02-verify-apps.sh", "03-verify", "research"),
    step("sts", "Configurar STS", "Reutiliza el cliente guardado en Vault si aparece en el inventario del tenant. Si hay duplicados sin esa referencia, se detiene.", "chatbot/scripts/02-verify-apps.sh", "03-verify", "sts"),
    step("usuarios", "Configurar usuarios y grupos", "Busca reader, writer y supervisor antes de crear. Activa solo los pendientes y completa IDs y membresías.", "chatbot/scripts/03-verify-users.sh", "03-verify"),
    step("dependencias", "Instalar entorno Python", "Instala las dependencias fijadas del chatbot en /tmp/vault-chatbot-venv.", "chatbot/scripts/install.sh", "10-aplicacion"),
    step("database", "Configurar datos y roles Database", "Prepara tablas de demostración y roles RO/RW. La cuenta administrativa se crea y rota solo si falta la conexión.", "chatbot/scripts/01-database.sh", "02-mysql"),
    step("proteccion", "Configurar Transit y Transform", "Prepara los motores y la tabla de solicitudes cifradas; conserva claves y transformaciones existentes.", "chatbot/scripts/06-data-protection.sh", "05-proteccion"),
    step("agentes", "Registrar agentes en Vault", "Comprueba ambas credenciales antes de escribir entidades, aliases, políticas, registros y configuración runtime.", "chatbot/scripts/04-vault-agents.sh", "04-vault-iam"),
    step("agentes-tarea", "Preparar agentes opcionales por tarea", "Añade Consulta, Creación y Revelado. Se activan desde la interfaz con un nuevo login; el modo inicial sigue siendo el actual.", "chatbot/scripts/configure-task-agents.sh", "14-agentes-por-tarea"),
    step("rar-parametros", "Preparar laboratorio de parámetros RAR", "Añade los campos opcionales al esquema conocido de Verify y prepara dos perfiles ficticios cifrados. Conserva clientes, ACL y techos del agente.", "chatbot/scripts/configure-rar-lab.sh", "15-parametros-rar"),
    step("grupos", "Sincronizar grupos en Vault", "Configura grupos externos y sus políticas a partir del directorio de Verify.", "chatbot/scripts/05-sync-groups.sh", "04-vault-iam"),
    step("espacios-personales", "Preparar espacios personales de secretos", "Añade una política por identidad, techos limitados al nuevo prefijo KV y tres secretos ficticios. Conserva los datos existentes.", "chatbot/scripts/configure-personal-spaces.sh", "16-espacios-personales"),
    step("contratacion", "Preparar contratación con CIBA", "Writer solicita contratar. Verify confirma a Validador; Vault entrega una credencial SQL de formalización. El contrato permite descargar su PDF.", "chatbot/scripts/configure-contracts.sh", "17-contratacion-ciba"),
    step("xai-motor", "Configurar motor xAI", "Registra el plugin, configura su credencial de gestión y conserva el rol existente.", "scripts/demo/xai.sh", "06-xai"),
    step("xai-agente", "Configurar agente xAI", "Configura la aplicación Verify y el agente xAI. El catálogo conjunto se publicará en modelos.", "chatbot/scripts/configure-xai.sh", "06-xai"),
    step("spiffe-openai", "Preparar SPIFFE para OpenAI", "Configura issuer, firma y rol lumen-openai en verify/spiffe.", "scripts/manual/guided-actions.sh", "07-openai-spiffe", "spiffe-openai"),
    step("spiffe-claude", "Preparar SPIFFE para Claude", "Configura el rol independiente lumen-anthropic en el mismo issuer.", "scripts/manual/guided-actions.sh", "08-claude-spiffe", "spiffe-claude"),
    step("publicar-jwks", "Publicar discovery y JWKS", "Arranca el publicador y ngrok. Comprueba que las rutas privadas de Vault no se publican.", "scripts/demo/ngrok.sh", "07-openai-spiffe"),
    step("openai-recursos", "Preparar proyecto y cuenta OpenAI", "Reutiliza o crea proyecto y cuenta de servicio; guarda IDs en .env. Revoca la clave estática emitida al crear una cuenta.", "scripts/demo/openai-admin.sh", "07-openai-spiffe"),
    step("openai-mapping", "Completar mapping OpenAI", "Pausa de consola: configura WIF según 07 y guarda OPENAI_IDENTITY_PROVIDER_ID en .env. Este paso comprueba las entradas; la prueba real está al final.", "scripts/manual/guided-actions.sh", "07-openai-spiffe", "openai-mapping"),
    step("openai-agente", "Configurar agente OpenAI", "Configura la aplicación Verify, agente y perfil SPIFFE de OpenAI.", "chatbot/scripts/configure-openai.sh", "07-openai-spiffe"),
    step("claude-jwks", "Sincronizar claves públicas de Claude", "Actualiza las claves del emisor existente mediante el perfil ant lumen-admin y verifica su configuración. Requiere el inicio de sesión administrativo inicial descrito en 08.", "scripts/demo/claude-issuer.sh", "08-claude-spiffe"),
    step("claude-agente", "Configurar agente Claude", "Configura el agente con los IDs del emisor, regla y cuenta ya creados según 08; el paso anterior sincroniza sus claves.", "chatbot/scripts/configure-anthropic.sh", "08-claude-spiffe"),
    step("modelos", "Publicar catálogo de los tres proveedores", "Comprueba las tres credenciales y publica conjuntamente OpenAI, xAI y Claude en chatbot/model.", "chatbot/scripts/configure-models.sh", "10-aplicacion"),
    step("auditoria", "Habilitar auditoría Vault", "Configura el dispositivo de auditoría utilizado por el laboratorio.", "chatbot/scripts/enable-audit.sh", "09-observabilidad"),
    step("observabilidad", "Desplegar observabilidad", "Aplica Alloy, Loki, Tempo y Grafana; conserva la credencial existente de Grafana.", "chatbot/scripts/deploy-observability.sh", "09-observabilidad"),
    step("arrancar", "Arrancar Lumen y conexiones locales", "Prepara procesos gestionados por launchd, renueva sus conexiones y arranca Lumen en 8088.", "scripts/demo/start.sh", "10-aplicacion"),
    step("runtime", "Comprobar runtime", "Comprueba salud, catálogo completo y ausencia de credenciales administrativas en el proceso.", "scripts/manual/guided-actions.sh", "10-aplicacion", "runtime"),
    step("probar-infraestructura", "Probar Database y research", "Emite credenciales temporales, prueba privilegios MySQL y accesos del agente research, realiza una búsqueda Tavily y revoca los leases de la prueba.", "chatbot/scripts/test-infrastructure.sh", "10-aplicacion"),
    step("probar-obo", "Probar permisos de los tres usuarios", "Inicia sesión PKCE con los usuarios de laboratorio y comprueba los nueve permisos de cada uno mediante los servicios de la aplicación.", "scripts/manual/guided-actions.sh", "10-aplicacion", "obo"),
    step("probar-xai", "Probar xAI", "Emite credenciales dinámicas y realiza inferencia real. Consume uso del proveedor.", "chatbot/scripts/verify-xai.sh", "06-xai"),
    step("probar-openai", "Probar OpenAI WIF", "Comprueba intercambio SPIFFE e inferencia real. Consume uso del proveedor.", "chatbot/scripts/verify-openai.sh", "07-openai-spiffe"),
    step("probar-claude", "Probar Claude WIF", "Comprueba intercambio SPIFFE e inferencia real. Consume uso del proveedor; falla si las claves de Claude están desactualizadas.", "chatbot/scripts/verify-anthropic.sh", "08-claude-spiffe"),
)


def stamp():
    return datetime.now(timezone.utc).isoformat()


class Guide:
    def __init__(self, root=ROOT, state_dir=None):
        self.root = Path(root).resolve()
        base = state_dir or os.environ.get("LUMEN_STATE_DIR") or str(
            Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "lumen-vault-demo")
        self.base = Path(base).expanduser().resolve()
        self.private = self.base / "manual/guided"
        self.path = self.private / "progress.json"

    def load(self):
        if not self.path.exists():
            return {"version": 1, "root": str(self.root), "cursor": 0, "steps": {}}
        data = json.loads(self.path.read_text())
        if data.get("version") != 1 or data.get("root") != str(self.root):
            raise ValueError("El progreso pertenece a otro workspace o formato. Usa otro LUMEN_STATE_DIR.")
        if not isinstance(data.get("cursor"), int) or not 0 <= data["cursor"] <= len(STEPS):
            raise ValueError("Cursor de progreso no válido; conserva el archivo para diagnosticarlo.")
        return data

    def save(self, data):
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=2) + "\n")
        temporary.chmod(0o600)
        temporary.replace(self.path)

    @contextmanager
    def locked(self):
        self.private.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.private.chmod(0o700)
        with (self.private / "lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError("Hay otro paso en ejecución; espera a que termine.")
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def select(self, value):
        # The menu displays 01, 02, ...; accept those exact labels too.
        if value.isdecimal():
            value = str(int(value))
        for i, item in enumerate(STEPS):
            if value in (item.id, str(i + 1)):
                return i
        raise ValueError("Paso desconocido: " + value)

    def next_index(self, data):
        # A failure keeps the cursor here. Starting at an intermediate step does
        # not mark earlier work as completed or unexpectedly wrap around to it.
        i = data["cursor"]
        while i < len(STEPS) and data["steps"].get(STEPS[i].id, {}).get("status") == "ok":
            i += 1
        return i

    def status(self):
        data = self.load()
        current = self.next_index(data)
        print("Historial de ejecución (no certifica el estado actual de los servicios):")
        for i, item in enumerate(STEPS):
            result = data["steps"].get(item.id, {})
            label = {"ok": "OK", "failed": "FALLO", "running": "INCOMPLETO"}.get(result.get("status"), "pendiente")
            print(f'{"→" if i == current else " "} {i+1:02} {item.id:23} {label:10} {item.title}')
        print(f"Progreso y logs privados: {self.private}")

    def describe(self, index, code=False):
        item = STEPS[index]
        print(f"\n{index+1:02}/{len(STEPS)} · {item.title} [{item.id}]")
        print(item.effect)
        print(f"Guía: docs/manual/{item.chapter}.md")
        print("Ejecuta: " + shlex.join(item.command))
        if code:
            print((self.root / item.command[1]).read_text())

    def run(self, index):
        with self.locked():
            data = self.load()
            item = STEPS[index]
            self.describe(index)
            (self.private / "logs").mkdir(exist_ok=True, mode=0o700)
            log = self.private / "logs" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + item.id + ".log")
            record = {"status": "running", "started": stamp(), "log": str(log),
                      "attempt": data["steps"].get(item.id, {}).get("attempt", 0) + 1}
            data["cursor"] = index
            data["steps"][item.id] = record
            self.save(data)
            env = dict(os.environ, LUMEN_STATE_DIR=str(self.base), LUMEN_GUIDED="1")
            # Wrappers must establish their own environment, even from zsh or
            # after an earlier interactive Bash has exited.
            command = ["bash", str(self.root / "scripts/manual/guided-run.sh"), *item.command]
            print(f"Log: {log}", flush=True)
            try:
                with log.open("w") as output:
                    log.chmod(0o600)
                    process = subprocess.Popen(command, cwd=self.root, env=env,
                                               stdin=subprocess.DEVNULL, stdout=output,
                                               stderr=subprocess.STDOUT, start_new_session=True)
                    try:
                        while True:
                            try:
                                code = process.wait(timeout=20)
                                break
                            except subprocess.TimeoutExpired:
                                print(f"Sigue en curso: {item.id}. Log: {log}", flush=True)
                    except KeyboardInterrupt:
                        os.killpg(process.pid, signal.SIGTERM)
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            os.killpg(process.pid, signal.SIGKILL)
                            process.wait()
                        code = 130
            except OSError as exc:
                log.write_text(str(exc) + "\n")
                code = 1
            record.update(status="ok" if code == 0 else "failed", finished=stamp(), exit_code=code)
            data["cursor"] = index + 1 if code == 0 else index
            self.save(data)
            if code:
                print(f"El paso {item.id} no terminó. No se ejecuta ningún paso posterior.")
                print(f"Detalle privado: {log}")
                print(f"Tras corregir la causa: bash scripts/manual/paso-a-paso.sh ejecutar {item.id}")
            else:
                print(f"OK · {item.id}")
                if item.id == "claude-jwks":
                    print(f"Claves sincronizadas. Informe: {self.base / 'claude/issuer-sync.json'}")
            return code

    def menu(self, start=None):
        if not sys.stdin.isatty():
            raise ValueError("El menú necesita una terminal. Usa lista, ver ID o ejecutar ID.")
        if start is not None:
            with self.locked():
                data = self.load()
                data["cursor"] = start
                self.save(data)
        print("Un paso por vez. Enter ejecuta; v muestra código; l lista; un número selecciona; q sale.")
        selected = start
        while True:
            index = selected if selected is not None else self.next_index(self.load())
            if index >= len(STEPS):
                print("Fin del recorrido seleccionado. 'lista' muestra también los pasos anteriores que no ejecutaste.")
                return 0
            self.describe(index)
            try:
                choice = input("\n[Enter / v / l / número / q] > ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nPuedes volver a abrir este mismo script para continuar.")
                return 0
            if choice in ("q", "salir"):
                return 0
            if choice == "v":
                self.describe(index, code=True)
            elif choice == "l":
                self.status()
            elif choice:
                try:
                    selected = self.select(choice)
                except ValueError as exc:
                    print(exc)
            else:
                code = self.run(index)
                # Stay on a failed step, and ask again; never retry a write
                # merely because a network request timed out.
                selected = index if code else None


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description="Lumen: ejecución guiada, un paso cada vez.")
    parser.add_argument("action", nargs="?", default="menu",
                        choices=("menu", "lista", "estado", "ver", "ejecutar", "siguiente", "desde"))
    parser.add_argument("step", nargs="?")
    args = parser.parse_args()
    guide = Guide()
    try:
        if args.action in ("ver", "ejecutar", "desde") and not args.step:
            parser.error("Este comando requiere el número o ID de un paso.")
        if args.action in ("lista", "estado"):
            guide.status()
        elif args.action == "ver":
            guide.describe(guide.select(args.step), code=True)
        elif args.action == "ejecutar":
            return guide.run(guide.select(args.step))
        elif args.action == "siguiente":
            index = guide.next_index(guide.load())
            if index < len(STEPS):
                return guide.run(index)
            print("Fin del recorrido seleccionado. Consulta 'lista'.")
        else:
            return guide.menu(guide.select(args.step) if args.action == "desde" else None)
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
