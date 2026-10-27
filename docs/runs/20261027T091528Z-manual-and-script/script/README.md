# Validación manual · 2026-10-27T10:13:57Z

[Guías](../../../manual/README.md) · [Cómo repetir](../../../manual/13-repeticion-script.md)

La verificación terminó con 137 comprobaciones funcionales. Los tres proveedores se seleccionan por sesión usando el catálogo conjunto. Las claves públicas del nuevo Vault deben haberse actualizado en el emisor Claude antes de esta fase.

- [Resultado conjunto](result.json) y [estado de verificación](verification-state.json).
- [Workflows](workflows.json): OIDC/OBO, datos protegidos, modelos, bloqueos y trazas.
- [Usuarios](users.json), [agentes](agents.json) y [estado final sin bloqueos](final-state.json).

Si esta ejecución incluye instalación o reconstrucción, sus informes installation.json, before.json, after.json y remove.json permanecen en este mismo directorio. El resultado solo afirma reconstrucción cuando se dispone de las evidencias de retirada e identidades anteriores y nuevas. Tokens, cookies y logs completos permanecen en el estado privado local. La prueba funcional no inspecciona visualmente la interfaz.
