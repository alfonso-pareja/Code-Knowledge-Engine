# Code Knowledge Engine

**Code Knowledge Engine (CKE)** convierte uno o varios proyectos de software en una base de conocimiento consultable. Permite encontrar implementaciones, explorar dependencias y hacer preguntas sobre el código, con referencias al proyecto, archivo y líneas que respaldan cada resultado.

Es una herramienta **local-first de recuperación aumentada por generación (RAG) para código fuente**. En la configuración de esta guía, el procesamiento, los embeddings, el almacenamiento y las respuestas se ejecutan en tu equipo mediante Python, SQLite, Qdrant y Ollama.

## Para qué sirve

Comprender una aplicación distribuida entre distintos repositorios requiere localizar archivos, seguir dependencias y reunir contexto antes de implementar un cambio. Las búsquedas textuales ayudan cuando conoces los nombres exactos, pero pueden quedarse cortas cuando solo conoces el comportamiento que buscas.

CKE reúne esos proyectos en una misma **base de conocimiento o KB** y permite:

- Buscar lógica de negocio con palabras clave o preguntas en lenguaje natural.
- Encontrar funciones, clases y archivos relevantes entre varios repositorios.
- Obtener explicaciones basadas en fragmentos reales de código.
- Explorar relaciones estáticas de imports para orientar una revisión de dependencias.
- Proporcionar evidencia a clientes compatibles con MCP, como Copilot o Codex.
- Trabajar sobre archivos con cambios locales sin exigir commits ni modificar las fuentes.

Ejemplos de preguntas:

> ¿Dónde se validan los parámetros de búsqueda?
>
> ¿Cómo se registran las fuentes de una base de conocimiento?
>
> ¿Qué archivos participan en la generación de embeddings?

La herramienta recupera evidencia para ayudarte a investigar. La calidad de una respuesta depende de los archivos indexados, la recuperación y el modelo elegido; conviene comprobar las citas antes de tomar decisiones.

## Cómo funciona

1. **Registro:** agrupas carpetas locales, workspaces o repositorios Git dentro de una KB.
2. **Chunking:** CKE lee archivos permitidos, calcula hashes y genera fragmentos con referencias de origen. SQLite conserva esos fragmentos y la búsqueda textual.
3. **Indexación vectorial:** un modelo de embeddings convierte los fragmentos en vectores y CKE los guarda en Qdrant.
4. **Recuperación:** la consulta se compara con los fragmentos mediante búsqueda textual, semántica o híbrida.
5. **Respuesta:** un modelo de generación recibe la pregunta y el contexto recuperado para elaborar una explicación con citas.

Los dos modelos cumplen funciones distintas:

| Componente | Ejemplo de esta guía | Función |
|---|---|---|
| Modelo de embeddings | `embeddinggemma` en Ollama | Representar fragmentos y consultas como vectores para buscar por similitud. |
| Modelo de respuestas | `llama3.2` en Ollama | Elaborar una explicación a partir de la evidencia recuperada. |
| SQLite con FTS5 | Incluido con Python cuando FTS5 está disponible | Guardar fragmentos, referencias, relaciones y búsqueda textual. |
| Qdrant | Contenedor Docker | Guardar y consultar los vectores. |
| Knowledge Explorer | Servidor HTTP de CKE | Buscar, consultar evidencia, configurar IA y explorar imports desde el navegador. |

CLI, visor y MCP reutilizan el mismo servicio de recuperación. Las KB se consultan por separado.

## Requisitos

- **macOS o Linux:** se utilizan permisos, descriptores de archivos y bloqueos POSIX.
- **Python 3.11 o superior**, con `venv` y SQLite con FTS5.
- **Git**, para clonar este proyecto y trabajar con fuentes Git.
- **Docker con Docker Compose:** por ejemplo, Docker Desktop en macOS o Docker Engine con el plugin Compose en Linux.
- **Ollama:** para ejecutar los dos modelos locales.
- Espacio disponible para los modelos, los índices y el volumen de Qdrant. El tiempo de procesamiento y el consumo de memoria dependen del equipo y del código incorporado.

Enlaces de instalación: [Python](https://www.python.org/downloads/), [Git](https://git-scm.com/downloads), [Docker](https://docs.docker.com/get-started/get-docker/) y [Ollama](https://ollama.com/download).

**La configuración local no necesita una API key ni una suscripción a un servicio de IA.** Se necesita conexión a Internet para descargar las herramientas, las dependencias, los modelos y la imagen de Qdrant.

## Puesta en marcha paso a paso con Ollama

### 1. Descargar el proyecto e instalar la CLI

Sustituye `URL_DEL_REPOSITORIO` por la URL de este repositorio en GitHub:

```bash
git clone URL_DEL_REPOSITORIO code-knowledge-engine-python
cd code-knowledge-engine-python

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e .

cke init
```

Ejecuta los pasos siguientes desde esta carpeta y con el entorno virtual activado. Si otro programa ya instaló un comando llamado `cke`, utiliza `.venv/bin/cke` para seleccionar esta implementación.

### 2. Iniciar Ollama

Instala [Ollama](https://ollama.com/download) y abre su aplicación. Si prefieres iniciarlo desde la terminal:

```bash
ollama serve
```

Ese comando permanece activo; utiliza otra terminal para continuar y activa allí el entorno virtual:

```bash
cd /ruta/al/code-knowledge-engine-python
source .venv/bin/activate
```

Si aparece `address already in use` en el puerto `11434`, puede que Ollama ya esté ejecutándose. Compruébalo antes de iniciar otra instancia:

```bash
ollama list
```

### 3. Descargar los modelos

```bash
ollama pull llama3.2
ollama pull embeddinggemma
ollama list
```

La lista debe incluir ambos modelos; pueden aparecer con el sufijo `:latest`.

### 4. Configurar los modelos en CKE

```bash
cke config set \
  --provider ollama \
  --model llama3.2 \
  --embedding-provider ollama \
  --embedding-model embeddinggemma
```

Este comando guarda la elección y muestra instrucciones de preparación. No instala herramientas ni descarga modelos automáticamente.

### 5. Iniciar Qdrant

Con Docker en ejecución, abre una terminal en la carpeta que contiene `docker-compose.yml`:

```bash
docker compose up -d
docker compose ps
```

Qdrant debe aparecer en ejecución. La configuración del proyecto publica su API únicamente en `127.0.0.1:6333` y conserva los datos en un volumen Docker.

### 6. Comprobar la instalación

```bash
cke config check
```

Verifica los siguientes valores:

| Campo | Valor esperado |
|---|---|
| `fts5` | `true` |
| `ollama.available` | `true` |
| `ollama.missing_models` | `[]` |
| `qdrant.available` | `true` |

`api_key_configured: false` es normal en este ejemplo local. También puedes consultar la configuración con `cke config show` y las comprobaciones con `cke doctor`.

### 7. Crear una KB y registrar una fuente

Para una primera prueba reproducible, utiliza **el propio código de CKE** como fuente. El punto `.` representa la carpeta actual del proyecto:

```bash
cke kb create demo
cke source add . --type local --kb demo --id engine
cke source list --kb demo
```

Los identificadores de KB deben comenzar con una letra minúscula o un dígito y contener solamente letras minúsculas, dígitos, guiones o guiones bajos. `demo` y `my-projects` son ejemplos válidos.

Más adelante puedes crear otra KB y registrar tus propias carpetas, como se explica en la sección de fuentes.

### 8. Generar los fragmentos

```bash
cke chunks --kb demo
```

Este paso escanea las fuentes, genera o reutiliza fragmentos y publica la evidencia en SQLite. Revisa `total_chunks`: debe ser mayor que cero. `chunks_created: 0` es normal si ya se habían procesado los mismos archivos sin cambios.

### 9. Generar el índice vectorial

```bash
cke index --kb demo
```

CKE envía los fragmentos al modelo **local** `embeddinggemma` y guarda sus vectores en Qdrant. Muestra el lote actual, los chunks completados, el porcentaje y el tiempo transcurrido. El proceso puede tardar: espera el resultado final antes de utilizar búsqueda semántica.

Si una entrada supera el contexto de Ollama, CKE la divide y combina los vectores de sus segmentos sin truncar el contenido original. Los fragmentos largos tienen una representación agregada aproximada; sus archivos y líneas de origen se conservan.

### 10. Buscar y hacer una pregunta

Para recuperar fragmentos sin generar una explicación:

```bash
cke search "¿Cómo se registran las fuentes?" --kb demo --mode semantic
```

Para recuperar evidencia y obtener una respuesta con `llama3.2`:

```bash
cke ask "¿Cómo se registran las fuentes de una base de conocimiento?" --kb demo
```

`ask` utiliza por defecto el modo híbrido del perfil local. Las respuestas incluyen evidencia y citas como `[S1]`. Si no hay evidencia suficiente o las citas no son válidas, CKE devuelve una abstención.

### 11. Abrir Knowledge Explorer

```bash
cke viewer serve --port 8765
```

Abre [http://127.0.0.1:8765](http://127.0.0.1:8765) y:

1. Selecciona la KB `demo` en **Búsqueda**.
2. Escribe una consulta y elige el modo de recuperación.
3. Pulsa **Buscar** para ver los fragmentos o **Generar respuesta** para consultar al modelo.
4. Utiliza **Imports** para explorar relaciones estáticas y **Configuración IA** para cambiar proveedores y modelos.

El servidor permanece activo en esa terminal. Si actualizas el código del servidor, detenlo con `Ctrl+C` y vuelve a iniciarlo para cargar los cambios.

## Uso diario y actualización de índices

En una terminal nueva, activa el entorno virtual e inicia los servicios que no estén activos:

```bash
source .venv/bin/activate
docker compose up -d
# Abre Ollama si no está ejecutándose.
cke config check
cke viewer serve --port 8765
```

No necesitas repetir la descarga de modelos ni indexar si la evidencia y el modelo de embeddings siguen vigentes. Después de modificar los archivos que quieras consultar:

```bash
cke chunks --kb demo
cke index --kb demo
```

El chunking reutiliza el análisis de archivos sin cambios. Si la generación vectorial ya está vigente, `index` reutiliza sus vectores; si cambió, reconstruye los vectores de esa KB. Cambiar solamente el modelo de respuestas no requiere reindexar.

Una publicación vectorial incompleta queda invalidada para evitar resultados inconsistentes. Puedes reintentar `cke index`; actualmente no reanuda desde el último lote persistido.

Para detener el visor, utiliza `Ctrl+C`. Para detener Qdrant conservando sus datos:

```bash
docker compose stop
```

## Incorporar tus propios proyectos

Los siguientes ejemplos son independientes: sustituye las rutas y la URL Git por ubicaciones existentes. No necesitas agregar todas las variantes.

### Carpeta local

```bash
cke kb create my-projects
cke source add /ruta/a/tu/proyecto --type local --kb my-projects --id app
cke chunks --kb my-projects
cke index --kb my-projects
```

La carpeta puede estar fuera de CKE y no necesita ser un repositorio Git. Los cambios locales sin commit se leen mediante hashes de contenido.

### Workspace con varios repositorios

```bash
cke source add /ruta/a/tu/workspace --type workspace --kb my-projects --id workspace
```

CKE descubre repositorios Git dentro del workspace. Evita registrar al mismo tiempo el workspace y sus hijos si no deseas cobertura duplicada.

### Repositorio Git remoto

```bash
cke source add URL_GIT_DEL_REPOSITORIO --type git --ref main --kb my-projects --id library
cke chunks --kb my-projects --sync
cke index --kb my-projects
```

`--sync` autoriza clonar u obtener cambios y actualizar exclusivamente la copia administrada dentro de `CKE_HOME/mirrors`. Utiliza SSH o un gestor de credenciales; no incluyas tokens en la URL.

### Retirar una fuente

```bash
cke source remove --kb my-projects --id library
cke chunks --kb my-projects
cke index --kb my-projects
```

Retirar el registro no borra el repositorio original. El reprocesamiento retira su evidencia publicada y actualiza el índice vectorial.

## Modos de búsqueda

| Modo | Comportamiento | Requisitos |
|---|---|---|
| `keyword` | Busca palabras mediante SQLite FTS5; combina términos con OR. | Chunks publicados en SQLite. |
| `semantic` | Compara embeddings de la consulta y los fragmentos. | Modelo de embeddings y Qdrant con índice vigente. |
| `hybrid` | Combina resultados textuales y semánticos mediante reciprocal rank fusion. | Los dos mecanismos anteriores. |

Ejemplo con filtros:

```bash
cke search "validación de consultas" --kb demo --mode hybrid --repo engine --language python --limit 8
```

`--repo` acepta un identificador de fuente o proyecto. Las consultas admiten hasta 2.000 caracteres y el límite de resultados está entre 1 y 100.

## Proveedores y agentes alternativos

Los modelos de respuestas y embeddings se configuran por separado. La configuración es global para la instalación y puede verse en el visor o con `cke config show`.

| Proveedor | Comportamiento |
|---|---|
| `ollama` | Genera respuestas localmente. |
| `openai` | Usa la API de OpenAI con una API key y autorización explícita para enviar código. |
| `copilot` / `codex` | Entrega evidencia al agente; el modelo se selecciona en el cliente. |
| `chatgpt` | Prepara contexto para copiar en ChatGPT; no invoca automáticamente tu sesión. |

Por ejemplo, para preparar contexto sin modelos locales ni búsqueda vectorial:

```bash
cke config set --provider copilot
cke ask "¿Cómo funciona la búsqueda?" --kb demo
```

Ese perfil utiliza búsqueda textual y no requiere Ollama, Qdrant ni `cke index`. Si quieres volver a la configuración local, repite el paso 4.

La opción `openai` requiere `OPENAI_API_KEY` en el entorno del proceso y `--allow-cloud-code`. Los embeddings en la nube envían los chunks; la generación envía el contexto recuperado. Las claves no se guardan en la configuración ni se devuelven al navegador. Un archivo `.env` no se carga automáticamente. La integración utiliza la API, no una sesión de ChatGPT.

## MCP para clientes compatibles

CKE incluye un servidor MCP de solo lectura por **stdio**. Configura el cliente con el path absoluto del ejecutable y las KB autorizadas; adapta este bloque al formato requerido por tu cliente:

```json
{
  "command": "/ruta/al/code-knowledge-engine-python/.venv/bin/cke",
  "args": ["mcp", "serve"],
  "env": {"CKE_MCP_ALLOWED_KBS": "demo"}
}
```

Sin `CKE_MCP_ALLOWED_KBS` no se expone ninguna KB. El cliente puede transmitir los fragmentos a su proveedor de modelos: habilítalo solo con la autorización correspondiente. El servidor stdio no se conecta directamente a ChatGPT web; CKE no publica un servidor MCP remoto ni abre túneles automáticamente.

Herramientas disponibles: `list_knowledge_bases`, `list_sources`, `search_code`, `get_source`, `find_symbol`, `get_graph`, `get_dependencies`, `trace_flow` y `analyze_impact`. Las dos últimas recorren imports candidatos; no reconstruyen procesos de ejecución.

## Datos, privacidad y exclusiones

Por defecto, los datos se guardan fuera del proyecto en `~/.cke-python`:

| Ubicación | Contenido |
|---|---|
| `catalog.json` | KB y fuentes registradas. |
| `settings.json` | Proveedores y modelos, sin API keys. |
| `knowledge.sqlite` | Fragmentos, referencias, relaciones y estado de publicación. |
| `snapshots/` | Manifiestos con hashes y referencias a las fuentes. |
| `mirrors/` | Copias administradas de fuentes Git. |

Qdrant conserva los vectores y sus payloads en el volumen Docker configurado. Estos datos pueden contener código privado: no los incluyas en el repositorio público.

- CKE no ejecuta checkout, reset, clean ni escrituras sobre fuentes locales.
- Se excluyen `.env*`, claves privadas, directorios generados y archivos con ciertos patrones de secretos.
- Se respetan exclusiones Git y se rechazan lecturas mediante enlaces simbólicos dentro de las fuentes.
- El filtro básico de secretos no sustituye un escáner de seguridad.
- Ollama y Qdrant usan loopback por defecto; sus URLs externas requieren una allowlist explícita.
- El visor valida Host/Origin y está destinado a un usuario local de confianza. No tiene autenticación multiusuario; no lo publiques mediante un proxy o túnel.

Puedes añadir exclusiones con `CKE_EXCLUDE` —patrones separados por comas— o un archivo `.ckeignore` en la fuente. CKE lo lee, nunca lo crea. Ejemplo de patrones `fnmatch`:

```text
**/fixtures/*
config/private.json
```

Variables principales: `CKE_HOME`, `OLLAMA_URL`, `QDRANT_URL`, `CKE_EMBEDDING_MODEL`, `CKE_COLLECTION`, `CKE_EXCLUDE`, `CKE_ALLOWED_ENDPOINTS`, `CKE_MCP_ALLOWED_KBS` y `OPENAI_API_KEY`. La configuración guardada selecciona los modelos; `CKE_EMBEDDING_MODEL` actúa como valor predeterminado cuando no existe un perfil guardado.

## Problemas frecuentes

| Síntoma | Comprobación o acción |
|---|---|
| `cke: command not found` | Activa `.venv` o utiliza `.venv/bin/cke`. |
| Advertencia SQLite de Node.js | Verifica `which cke`; utiliza el ejecutable Python del entorno virtual. |
| `address already in use` al iniciar Ollama | Ejecuta `ollama list`; si responde, no inicies otra instancia. |
| `no configuration file provided` | Ejecuta Docker Compose desde la carpeta que contiene `docker-compose.yml`. |
| `Connection refused` | Ejecuta `cke config check` e inicia el servicio indicado. |
| Modelos ausentes | Ejecuta los comandos `ollama pull` indicados en `config check`. |
| Índice vectorial ausente o desactualizado | Ejecuta `cke index --kb demo` después de `cke chunks`. |
| Error de dimensiones del modelo | Evita reutilizar una colección fijada con `CKE_COLLECTION` para modelos incompatibles. |
| Indexación lenta | Revisa el lote y tiempo mostrados; las entradas largas pueden requerir varias llamadas a Ollama. |
| Error HTTP | Revisa el proveedor y la operación del mensaje. Los errores de contexto de Ollama se dividen automáticamente; otros fallos requieren diagnóstico. |
| Cambié la configuración pero el visor no se actualiza | Recarga la página; reinicia el servidor si cambiaste código o variables de entorno. |

## Arquitectura y límites actuales

| Módulo | Responsabilidad |
|---|---|
| `sources/` | Descubrir proyectos, recorrer archivos y generar manifiestos. |
| `chunking/` | Extraer evidencia mediante estrategias y análisis sintáctico. |
| `storage/` | Publicación SQLite, FTS5 y generaciones vectoriales. |
| `retrieval/` | Recuperación compartida, filtros y fusión de resultados. |
| `answers/` | Contexto acotado, generación de respuestas y validación de citas. |
| `integrations/` | Ollama, OpenAI, Qdrant, MCP y transporte. |
| `viewer/` | Adaptador HTTP y recursos estáticos del visor. |
| `settings.py` / `providers.py` | Configuración y selección de proveedores. |
| `knowledge.py` | Navegación y relaciones estáticas. |
| `cli.py` | Argumentos y delegación a servicios. |

Python utiliza `ast` de la biblioteca estándar. El soporte sintáctico adicional de TypeScript, TSX, JavaScript y JSX es opcional:

```bash
python -m pip install -e '.[ast]'
```

Otros archivos UTF-8 utilizan un fallback textual. Los límites predeterminados son 1 MiB por archivo y 100.000 archivos por proyecto. No se descargan gramáticas durante la indexación.

El grafo muestra candidatos estáticos de imports, hasta 60 nodos visibles; no resuelve completamente aliases, HTTP, colas ni llamadas dinámicas. Las citas validan que la evidencia exista, pero no prueban automáticamente cada afirmación del modelo. El visor no mantiene memoria conversacional.

SQLite y Qdrant no forman una transacción distribuida: durante una reconstrucción, la búsqueda semántica de esa generación se bloquea hasta completar el índice. La preparación de publicaciones mantiene datos en memoria; el rendimiento depende del tamaño de las fuentes.

## Desarrollo y validación

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q src
```

Si tienes Node.js instalado, puedes comprobar la sintaxis del JavaScript del visor:

```bash
node --check src/cke/viewer/static/app.js
```

Las pruebas usan proyectos temporales y proveedores simulados; no requieren Ollama ni Qdrant. El caso opcional de Tree-sitter se omite si no están instaladas las gramáticas.

Para medir la recuperación, prepara un dataset JSON con consultas y archivos esperados:

```json
[
  {"query": "registrar fuentes", "expected_files": ["src/cke/catalog.py"]}
]
```

```bash
cke evaluate --kb demo --dataset /ruta/evaluation.json --mode keyword --limit 8
```

Se reportan Recall@K, MRR y latencia media. Esta evaluación compara rutas relativas, por lo que debe interpretarse con cuidado cuando distintos proyectos tienen archivos con el mismo nombre.
