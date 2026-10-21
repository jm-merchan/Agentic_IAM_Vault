# Imágenes Vault 2.2.0 con el plugin xAI

Las dos ediciones se publican en el repositorio Docker Hub existente
[`josemerchan/vault-xai`](https://hub.docker.com/r/josemerchan/vault-xai/tags).
Ambas contienen el plugin para `linux/amd64` y `linux/arm64`.

| Imagen | Versión del binario | Uso |
|---|---|---|
| `josemerchan/vault-xai:2.2.0-ent` | `2.2.0+ent` | Enterprise; requiere licencia con las funciones usadas |
| `josemerchan/vault-xai:2.2.0` | `2.2.0` | Community; no sustituye Enterprise en la demo completa |

El tag de contenedor usa `-ent`, como las imágenes oficiales, mientras que el
binario muestra `+ent`. Lumen necesita Enterprise para Agentic IAM, namespaces,
KMIP y Transform.

La publicación **no actualiza el clúster existente**. La versión predeterminada
del despliegue se conserva en `2.1.2-ent`; migrar Raft a otra versión se evalúa
por separado. El primer punto de agentes por tarea funciona con la versión
actual y no depende de esa migración.

## Reproducir la construcción

Se necesita Podman, Go, jq y el repositorio del plugin. El script usa únicamente
su revisión Git confirmada y rechaza cambios pendientes en archivos seguidos;
los binarios se compilan desde esa revisión en un contexto temporal.

```bash
bash scripts/build-vault-images.sh --build
```

Por defecto lee `$HOME/Projects/vault-plugin-secrets-xai`. Se puede elegir otra
ruta mediante `XAI_PLUGIN_REPO`. `VAULT_PUBLISH_REPOSITORY` permite seleccionar
el destino; el valor predeterminado es `docker.io/josemerchan/vault-xai`.

Para probar la edición Enterprise, preparar un archivo privado de licencia
desde la configuración de la demo:

```bash
bash -c 'source scripts/demo/common.sh; load_inputs; mkdir -p "$LUMEN_STATE_DIR/images/vault-2.2.0"; printf "VAULT_LICENSE=%s\n" "$VAULT_LICENSE" > "$LUMEN_STATE_DIR/images/vault-2.2.0/license.env"'
```

```bash
bash scripts/test-vault-images.sh
```

Arranca cuatro servidores dev aislados, sin puertos publicados. Cada uno
registra y carga el plugin; al terminar elimina exclusivamente sus contenedores.
No llama a xAI ni se conecta al clúster de Lumen.

La publicación, con la sesión de Podman autenticada en Docker Hub, construye y
prueba ambas ediciones antes de subir sus manifiestos:

```bash
bash scripts/build-vault-images.sh --publish
```

Una repetición de `--publish` reemplaza esas mismas dos etiquetas por la
construcción comprobada. No escribe `latest` ni cambia etiquetas anteriores.
La licencia se usa únicamente en los contenedores de prueba; no entra en el
contexto de construcción ni en las imágenes publicadas.

```bash
rm -f "${LUMEN_STATE_DIR:-$HOME/.local/state/lumen-vault-demo}/images/vault-2.2.0/license.env"
```

Consultar [el informe de publicación](vault-images-2.2.0.json) para los digests,
la revisión del plugin y los manifiestos verificados en Docker Hub. Las pruebas
de imagen cubren arranque y carga del plugin; no constituyen una prueba de
migración Raft, KMIP o federación de un clúster existente.

Referencias: [notas de Vault 2.x](https://developer.hashicorp.com/vault/docs/updates/release-notes)
y [cambios importantes](https://developer.hashicorp.com/vault/docs/updates/important-changes).
