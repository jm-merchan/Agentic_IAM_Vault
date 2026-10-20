# Reinstalación manual por script · 2026-10-16T06:53:46Z

[Guías](../../manual/README.md) · [Cómo repetir](../../manual/12-repeticion-script.md)

El ciclo completo terminó correctamente: retirada, instalación de los bloques Markdown y 102 comprobaciones funcionales. No se utilizó navegador, notebooks ni demo.sh start. La instalación configura Vault con su CLI y las APIs externas con curl.

- [Resultado conjunto](result.json).
- [Trazas para la demostración](TRAZAS.md) y [cotejo de los 96 bloques con las guías](guide-block-integrity.json).
- [Retirada](remove.json): 11 recursos Verify y 10 volúmenes inventariados; [plan](remove-plan.json).
- [Namespaces anteriores](before.json) y [nuevos](after.json), con UID distintos; [usuarios nuevos](users.json) y [agentes](agents.json).
- [Instalación](installation.json): 89 bloques en primer plano y 7 bloques de servicios en segundo plano, identificados por documento, número y SHA-256.
- [Workflows](workflows.json): permisos de los tres perfiles, solicitud sintética, protección de datos, OBO/RAR, agentes, modelos, bloqueos y trazas.
- [Salud de Lumen durante la instalación](health.json), [comprobación final de servicios](runtime-health.json) y [estado final sin bloqueos](final-state.json).

Se conservaron .env, cliente administrativo y esquema RAR de Verify, proyecto/cuenta/mapping WIF de OpenAI, perfil Minikube y recursos ajenos a Lumen. No se prueba aquí la creación inicial de esas cuentas externas. Los servicios quedan activos en localhost: Lumen 8088, Vault 8443 y Grafana 3000.

La prueba funcional usa los servicios reales de la aplicación. No inspecciona visualmente la UI ni genera capturas. Los IDs de traza del informe pertenecen a esta instalación; dejarán de estar en Tempo al retirar nuevamente sus volúmenes. Tokens y logs completos permanecen en el estado privado local.

Al cerrar la sesión que ejecutó el ensayo, su entorno terminó los procesos locales. Se reabrieron los mismos bloques de servicios en una sesión persistente, sin reprovisionar recursos ni cambiar la configuración. La comprobación final enlazada verifica Lumen, Vault, Grafana, Tempo, Loki y los pods activos.
