<h1 align="center">LifeTree · 人生树</h1>

<p align="center">
  <em>Un sistema de información inteligente enfocado en la toma de decisiones personales a medio y largo plazo: agrega datos públicos y privados, combina grafos de conocimiento con razonamiento causal, y proporciona un sandbox de decisión dinámica para las grandes elecciones de la vida.</em>
</p>

<p align="center">
  <a href="https://github.com/CaryK753/LifeTree/actions"><img alt="CI" src="https://github.com/CaryK753/LifeTree/actions/workflows/build-and-push.yml/badge.svg" /></a>
  <img alt="Python" src="https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white" />
  <img alt="Next.js" src="https://img.shields.io/badge/Next.js-16-000000?logo=next.js&logoColor=white" />
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-0.110+-009688?logo=fastapi&logoColor=white" />
  <img alt="PostgreSQL" src="https://img.shields.io/badge/PostgreSQL-16%20pgvector-4169E1?logo=postgresql&logoColor=white" />
  <img alt="Neo4j" src="https://img.shields.io/badge/Neo4j-5-008CC1?logo=neo4j&logoColor=white" />
  <img alt="Redis" src="https://img.shields.io/badge/Redis-7-DC382D?logo=redis&logoColor=white" />
  <img alt="Docker" src="https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white" />
  <img alt="License" src="https://img.shields.io/badge/License-AGPL_v3-blue" />
  <img alt="PWA" src="https://img.shields.io/badge/PWA-ready-5A0FC8?logo=pwa&logoColor=white" />
</p>

<p align="center">
  <strong>Idiomas / Languages:</strong>
  <a href="README.zh-CN.md">简体中文</a> ·
  <a href="README.zh-TW.md">繁體中文</a> ·
  <a href="README.en.md">English</a> ·
  <a href="README.es.md">Español</a> ·
  <a href="README.de.md">Deutsch</a> ·
  <a href="README.fr.md">Français</a>
</p>

<p align="center">
  <img src="docs/assets/brand-hero.jpg" alt="LifeTree · 人生树" width="100%" />
</p>
---

## Tabla de Contenidos

- [Introducción del Proyecto](#introducción-del-proyecto)
- [Arquitectura del Sistema](#arquitectura-del-sistema)
- [Stack Tecnológico](#stack-tecnológico)
- [Características](#características)
- [Inicio Rápido](#inicio-rápido)
- [Despliegue Docker con Un Clic](#despliegue-docker-con-un-clic)
- [Desarrollo Local](#desarrollo-local)
- [Configuración](#configuración)
- [Sistema de Plugins](#sistema-de-plugins)
- [License](#license)

---

## Introducción del Proyecto

**LifeTree** es un sistema de información inteligente enfocado en la toma de decisiones personales a medio y largo plazo. No es una simple lista de tareas o herramienta de notas, sino un sandbox de decisión dinámica que integra grafos de conocimiento, razonamiento causal, redes bayesianas y simulación de Monte Carlo.

### ¿Qué Problema Resuelve?

Cuando enfrentamos grandes elecciones de vida — rutas de inmigración, transiciones profesionales, inversiones en educación, planificación familiar — a menudo:

- **Información Fragmentada**: Los datos relevantes están dispersos en marcadores del navegador, historiales de chat y documentos, difíciles de sistematizar
- **Razonamiento Unilateral**: Solo vemos los beneficios a corto plazo, ignorando los riesgos a largo plazo y los costos de oportunidad
- **Decisiones Estáticas**: Una vez tomada la decisión, no se revisa dinámicamente con base en nueva información

LifeTree resuelve estos problemas mediante:

1. **Agregación de Información**: Captura automáticamente datos públicos (RSS / web / API), ingresa manualmente información privada (documentos / imágenes / notas), y los estructura uniformemente como nodos del grafo de conocimiento
2. **Modelado Causal**: Modela objetivo → ruta → requisito → factor de riesgo como grafo dirigido, usando redes bayesianas para cuantificar la incertidumbre
3. **Simulación de Escenarios**: Simulación de Monte Carlo para probabilidad de éxito, exposición al riesgo y costo temporal bajo diferentes rutas de elección
4. **Alerta Dinámica**: Tareas programadas de Celery monitorean la frescura de la información (modelo de vida media), disparando automáticamente recálculo de riesgo y alertas por correo
5. **Asesor de IA**: ReAct Agent basado en LangGraph que puede invocar más de 15 herramientas integradas para consultar el grafo de conocimiento, crear nuevos nodos, buscar en la web y extraer contenido de páginas

### Escenario de Ejemplo

Este repositorio incluye datos de ejemplo del **Trabajador Calificado Federal (FSW) de Canadá**, cubriendo:

- Objetivo: Inmigrar a Canadá vía el canal FSW
- Ruta: Entrada al pool EE → Invitación ITA → Presentación de documentos → Examen médico → Desembarque
- Requisitos: CLB 9 / Credencial ECA / Prueba de experiencia laboral / Prueba de fondos
- Factores de riesgo: Deducción de puntos por edad, fluctuación de puntaje de idioma, cambios de política, competencia por cuotas

---

## Arquitectura del Sistema

```mermaid
graph TB
    subgraph Client["Cliente Frontend (Next.js 16)"]
        UI[Páginas: Dashboard / Grafo / Chat / Escenario / Fuentes]
        PWA[PWA: Caché sin conexión + Push]
        SSE_C[Cliente SSE: Chat en streaming]
    end

    subgraph API["API Backend (FastAPI)"]
        REST[REST API: CRUD / Consulta]
        CHAT[Chat SSE: Chat LLM en streaming]
        CRAWLER[Crawler API: Búsqueda/Captura Tavily]
    end

    subgraph Agent["Asesor IA (LangGraph ReAct)"]
        GRAPH[create_react_agent]
        TOOLS[15+ Herramientas integradas<br/>Consulta / Escritura / Memoria / Web]
        LLM[LLM: OpenAI / Anthropic / Bailian]
    end

    subgraph Worker["Tareas Asíncronas (Celery)"]
        BEAT[Beat: Tareas programadas]
        TASKS[Tasks: Captura / Recálculo de riesgo /<br/>Limpieza vida media / Notificación]
    end

    subgraph Storage["Capa de Datos"]
        PG[(PostgreSQL 16<br/>+ pgvector)]
        NEO[(Neo4j 5<br/>Grafo de Conocimiento)]
        REDIS[(Redis 7<br/>Broker + Caché)]
        MINIO[(MinIO<br/>Almacenamiento de objetos)]
    end

    subgraph External["Servicios Externos"]
        TAVILY[Tavily API<br/>Búsqueda + Captura]
        SMTP[SMTP<br/>Alertas por correo]
        LLM_API[Proveedor LLM<br/>OpenAI / Bailian / Anthropic]
    end

    UI --> REST
    UI --> CHAT
    UI --> CRAWLER
    PWA --> UI
    SSE_C --> CHAT

    CHAT --> GRAPH
    GRAPH --> TOOLS
    GRAPH --> LLM
    LLM --> LLM_API
    TOOLS --> REST
    TOOLS --> CRAWLER
    CRAWLER --> TAVILY

    REST --> PG
    REST --> NEO
    TOOLS --> PG
    TOOLS --> NEO

    BEAT --> TASKS
    TASKS --> PG
    TASKS --> NEO
    TASKS --> CRAWLER
    TASKS --> SMTP
    TASKS --> REDIS

    CHAT --> REDIS
    REST --> REDIS
```

### Flujo de Datos

```mermaid
sequenceDiagram
    participant U as Usuario
    participant F as Frontend
    participant B as API Backend
    participant A as Agente IA
    participant DB as PostgreSQL
    participant T as Tavily

    U->>F: Ingresar pregunta en página de chat
    F->>B: POST /api/v1/chat/stream (SSE)
    B->>A: create_react_agent.astream_events()
    A->>A: Razonamiento: ¿Se necesitan herramientas?
    A->>DB: Llamar list_pathways / list_risk_factors
    DB-->>A: Devolver datos del grafo de conocimiento
    A->>T: Llamar web_search (si se necesita info externa)
    T-->>A: Devolver resultados de búsqueda
    A-->>B: Streaming de texto + llamadas a herramientas
    B-->>F: SSE: delta + tool_call chunks
    F-->>U: Efecto máquina de escribir + UI de herramientas inline
```

---

## Stack Tecnológico

| Capa | Tecnología | Descripción |
|---|---|---|
| **Frontend** | Next.js 16 (App Router) | React 19, standalone output, PWA |
| | Vercel AI SDK | Componentes de chat en streaming (Thread / Message / Composer) |
| | Tailwind CSS + Radix UI | Sistema de temas (claro/oscuro/sistema) |
| | Cytoscape.js + React Flow | Visualización de grafo de conocimiento + árbol de escenarios |
| | ECharts | Gráficos estadísticos |
| | SWR | Obtención y caché de datos |
| | i18n | 6 idiomas: zh-CN / zh-TW / EN / ES / DE / FR |
| **Backend** | FastAPI | REST + SSE + IA en streaming |
| | SQLAlchemy + Alembic | ORM + migraciones |
| | Pydantic v2 | Validación de datos |
| | Instructor | Salida estructurada LLM |
| | LangGraph | ReAct Agent + orquestación de herramientas |
| | Celery + Beat | Tareas asíncronas + tareas programadas |
| **Base de Datos** | PostgreSQL 16 + pgvector | Datos relacionales + búsqueda vectorial |
| | Neo4j 5 | Grafo de conocimiento (APOC) |
| | Redis 7 | Celery broker + caché |
| | MinIO | Almacenamiento de objetos (carga de archivos) |
| **LLM** | Compatible con OpenAI | Soporta OpenAI / DeepSeek / Zhipu / vLLM |
| | Anthropic Claude | Protocolo nativo |
| | Alibaba Cloud Bailian DashScope | Chat / Vision / Embedding / Rerank |
| **Despliegue** | Docker Compose | Lanzamiento de pila completa con un clic |
| | GitHub Actions | CI/CD construcción de imágenes multi-arquitectura |
| | GHCR | Registro de imágenes |

---

## Características

### Módulos Centrales

- **Brújula de Objetivos**: Gestión de objetivos estilo dashboard, seguimiento de progreso, fechas límite y estado de riesgo
- **Grafo de Conocimiento**: Layout de fuerza dirigida Cytoscape, nodos = entidades, aristas = relaciones, exploración por clic
- **Asesor de IA**: Chat en streaming, más de 15 herramientas integradas (consulta / escritura / memoria / búsqueda web / captura web), renderizado inline de UI de llamadas a herramientas
- **Simulación de Escenarios**: React Flow + layout en árbol dagre, simulación Monte Carlo, anillos de probabilidad de ramas + indicadores de riesgo
- **Gestión de Fuentes**: Calificación de credibilidad (alta / media / baja / marcada por usuario), gestión de vida media de información (modelo de decaimiento exponencial)
- **Alerta de Riesgo**: Centro de notificaciones, niveles de severidad (urgente / advertencia / información), envío por correo SMTP
- **Entrada de Información**: Carga por arrastrar y soltar (PDF / Word / Excel / PPT / imágenes), análisis Mineru, extracción estructurada por IA

### Herramientas Integradas de IA

| Herramienta | Tipo | Descripción |
|---|---|---|
| `list_pathways` | Consulta | Listar todas las rutas de un objetivo |
| `list_requirements` | Consulta | Listar requisitos de entrada de una ruta |
| `list_risk_factors` | Consulta | Listar factores de riesgo |
| `list_recent_events` | Consulta | Listar eventos recientes |
| `get_scenario_summary` | Consulta | Obtener resumen de escenario |
| `run_scenario_reasoning` | Razonamiento | Ejecutar razonamiento Bayesiano/Monte Carlo |
| `create_goal` / `create_pathway` / `create_requirement` / `create_risk_factor` | Escritura | Crear nodos del grafo de conocimiento |
| `list_memories` / `remember` / `forget` | Memoria | Gestión de memoria a largo plazo del usuario |
| `web_search` | Web | Búsqueda web Tavily |
| `web_fetch` | Web | Captura de contenido web Tavily |

### Características PWA

- Caché sin conexión (App Shell + recursos estáticos + respuestas API)
- Chat en streaming omite caché (`/api/v1/chat/stream` directo al backend)
- Instalación en escritorio / pantalla de inicio móvil
- Color de tema se adapta a modo claro/oscuro
- Barra lateral en modo drawer: en modo PWA o ancho de ventana < 1024px, la barra lateral se oculta por defecto y se desliza mediante el `SidebarToggleButton` de la esquina superior izquierda de cada página. Un script inline + las clases `html.pwa` / `html.drawer-mode` evitan el parpadeo antes de la hidratación.
- Detección de `navigator.standalone` en iOS, cubre casos que la media query `display-mode` no detecta.
- Padding de área segura para notch / indicador de inicio.

---

## Inicio Rápido

### Requisitos Previos

- Docker + Docker Compose
- O: Python 3.11+, Node.js 20+, pnpm/npm (solo para desarrollo local)

### Opción 1: Lanzamiento Docker Un Clic (Recomendado)

`docker-compose.yml` usa por defecto las imágenes pre-construidas de GHCR (`ghcr.io/caryk753/lifetree-backend`, `ghcr.io/caryk753/lifetree-frontend`), con un solo comando levanta toda la pila:

```bash
# 1. Clonar el repositorio
git clone https://github.com/CaryK753/LifeTree.git
cd LifeTree

# 2. Configurar variables de entorno
cp .env.example .env
# Editar .env, completar al menos una LLM API Key

# 3. Lanzamiento con un clic de pila completa (infraestructura + backend + worker + frontend)
docker compose up -d

# 4. Inicializar la base de datos (primera ejecución)
docker compose exec backend python scripts/init_db.py

# 5. Cargar datos de ejemplo (opcional)
docker compose exec backend python scripts/seed_fsw.py
```

> ¿Quieres fijar una versión? Sobrescribe el tag de imagen con variables de entorno:
> ```bash
> BACKEND_IMAGE_TAG=0.1.0 FRONTEND_IMAGE_TAG=0.1.0 docker compose up -d
> ```

Después del lanzamiento, visitar:
- Frontend: http://localhost:3000
- API Backend: http://localhost:8000
- Documentación API: http://localhost:8000/docs
- Flower (monitor Celery): http://localhost:5555
- Consola MinIO: http://localhost:9001
- Navegador Neo4j: http://localhost:7474

### Opción 2: Construir Imágenes Localmente

Si necesitas modificar código del backend / frontend o depurar, pasa `--build` para que compose construya con el Dockerfile local:

```bash
cp .env.example .env
# Editar .env, completar al menos una LLM API Key
docker compose up -d --build
docker compose exec backend python scripts/init_db.py
```

### Opción 3: Desarrollo Local

Consultar la sección [Desarrollo Local](#desarrollo-local).

---

## Despliegue Docker con Un Clic

El `docker-compose.yml` completo incluye los siguientes servicios:

| Servicio | Imagen | Puerto | Descripción |
|---|---|---|---|
| `postgres` | `pgvector/pgvector:pg16` | 5432 | PG + extensión vectorial pgvector |
| `neo4j` | `neo4j:5.20` | 7687, 7474 | Grafo de conocimiento + APOC |
| `redis` | `redis:7-alpine` | 6379 | Celery broker + caché |
| `minio` | `minio/minio:latest` | 9000, 9001 | Almacenamiento de objetos |
| `backend` | `ghcr.io/caryk753/lifetree-backend` | 8000 | Aplicación FastAPI |
| `worker` | `ghcr.io/caryk753/lifetree-backend` | - | Celery Worker |
| `beat` | `ghcr.io/caryk753/lifetree-backend` | - | Programador Celery Beat |
| `flower` | `mher/flower:latest` | 5555 | Monitor Celery |
| `frontend` | `ghcr.io/caryk753/lifetree-frontend` | 3000 | Next.js standalone |

```bash
# Iniciar todos los servicios (por defecto usa imágenes GHCR pre-construidas)
docker compose up -d

# Forzar construcción local y luego iniciar
docker compose up -d --build

# Ver logs
docker compose logs -f backend frontend

# Detener
docker compose down

# Detener y limpiar volúmenes de datos
docker compose down -v
```

### Control de Tag de Imagen

Por defecto se usa `latest`, se puede fijar una versión con variables de entorno:

```bash
BACKEND_IMAGE_TAG=0.1.0 FRONTEND_IMAGE_TAG=0.1.0 docker compose up -d
```

Si necesitas descargar las imágenes manualmente (por ejemplo, para un entorno offline):

```bash
docker pull ghcr.io/caryk753/lifetree-backend:latest
docker pull ghcr.io/caryk753/lifetree-frontend:latest
```

---

## Desarrollo Local

### 1. Iniciar Infraestructura

```bash
cp .env.example .env
# Editar .env, completar LLM_API_KEY etc.

# Iniciar solo servicios de infraestructura
docker compose up -d postgres neo4j redis minio
```

### 2. Iniciar Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Crear tablas (primera ejecución)
python scripts/init_db.py

# Iniciar API
uvicorn app.main:app --reload --port 8000

# En otra terminal: iniciar Celery Worker + Beat
celery -A app.workers.celery_app worker -l info
celery -A app.workers.celery_app beat -l info
```

### 3. Iniciar Frontend

```bash
cd frontend
npm install
npm run dev
```

### 4. Cargar Datos de Ejemplo

```bash
cd backend
python scripts/seed_fsw.py
```

Abrir http://localhost:3000 para ver el dashboard Brújula de Objetivos.

---

## Configuración

### Configuración LLM

Configurar el Proveedor LLM en la página de ajustes (`/settings`):

1. **Agregar Proveedor**: Seleccionar protocolo (compatible OpenAI / Anthropic / Alibaba Cloud Bailian), completar baseURL y API Key
2. **Agregar Modelo**: Completar ID del modelo (ej. `gpt-4o-mini`), marcar capacidades (chat / vision / embedding / rerank)
3. **Asignar Roles**: Seleccionar un modelo para cada rol

Proveedores Soportados:
- **Compatible OpenAI**: OpenAI / DeepSeek / Zhipu / OneAPI / vLLM
- **Anthropic**: Serie Claude (chat / vision)
- **Alibaba Cloud Bailian**: Qwen / gte-rerank / qwen3-rerank
  - Chat / Vision / Embedding vía protocolo compatible OpenAI
  - Rerank auto-enrutado al endpoint nativo `/api/v1/services/rerank/text-rerank/text-rerank`
  - Embedding por defecto 1024 dimensiones

### Configuración de Búsqueda Tavily

Completar Tavily API Key en la página de ajustes para habilitar:
- Herramientas `web_search` y `web_fetch` del Asesor IA
- Captura de fuentes (RSS / crawling web)

### Configuración de Correo SMTP

Configurar SMTP en la página de ajustes para habilitar el envío de alertas de riesgo por correo. Soporta envío de correos de prueba para verificar la configuración (la verificación de permisos se realiza antes del envío). Campos de configuración:

- Dirección del servidor SMTP, puerto
- Nombre de usuario, contraseña
- Correo del remitente, nombre del remitente
- Usar TLS (STARTTLS, puerto 587) / Usar SSL (puerto 465)

### Autenticación y Modo Multiusuario

LifeTree soporta dos modos de uso, controlados por la variable de entorno `LIFETREE_USE_MODE` (por defecto `single`), persistidos en la base de datos `app_config.use_mode`, conmutables vía `PUT /settings/use-mode`:

- **Modo un solo usuario (`single`, por defecto)**: no requiere inicio de sesión — el backend sirve los datos mediante el fallback de usuario predeterminado. Los usuarios que deseen un ámbito de datos personal pueden iniciar sesión manualmente desde el menú de usuario. AuthGate no muestra el diálogo de inicio de sesión.
- **Modo multiusuario (`multi`)**: requiere inicio de sesión — el diálogo de AuthGate no se puede cerrar. El rol de administrador se controla con la variable de entorno `LIFETREE_ADMIN_USER_IDS`.

Métodos de inicio de sesión soportados:

- Correo + contraseña (tokens JWT access/refresh), con flujo opcional de registro por código de verificación por correo (`send-code` / `register-with-code`)
- OAuth: Google / GitHub / Microsoft, endpoints `/auth/oauth/{id}/start` y `/auth/oauth/{id}/callback`

Aislamiento de datos: events / sources / plugins / conversaciones de chat se aíslan por `user_id`. Los datos de chat en el frontend se particionan por `lifetree.chat.conversations.v2.<userId>` en localStorage; los usuarios no autenticados usan el ámbito `default`.

### Configuración de Plataforma de Administrador

En modo multiusuario, los administradores tienen acceso a una página dedicada de configuración de plataforma para gestionar:

- API keys de modelos y servicios (OpenAI / Anthropic / Alibaba Cloud Bailian / Tavily / SMTP, etc.)
- Gestión de usuarios (`GET/PATCH/DELETE /admin/users`) y estadísticas de plataforma (`GET /admin/stats`)

Los usuarios no administradores no pueden ver las API keys configuradas por el administrador en la página de ajustes.

### Variables de Entorno

Para la lista completa de variables, ver [`.env.example`](.env.example).

---

## Sistema de Plugins

El sistema de plugins de LifeTree permite conectar a cualquier fuente de datos (RSS, scraper web, API, etc.) mediante scripts de Python personalizados, estructurando automáticamente la información externa en eventos, métricas, aserciones y relaciones del grafo de conocimiento. Soporta tanto plugins integrados como subidos por el usuario.

### Contrato del Plugin

Cada plugin es un archivo Python que implementa los siguientes métodos estáticos:

```python
from app.services.plugins import Plugin, PluginManifest, PluginParam

class Plugin:
    @staticmethod
    def manifest() -> PluginManifest:
        """Devuelve los metadatos del plugin: nombre, descripción, definición de parámetros."""

    @staticmethod
    def fetch(params: dict) -> str | bytes:
        """Captura datos crudos, devuelve texto o bytes."""

    @staticmethod
    def transform(raw, llm) -> str:  # opcional
        """Opcional: preprocesa los datos crudos con un LLM antes de pasarlos al servicio de estructuración."""
```

- **Plugins integrados**: ubicados en `backend/plugins/`, se distribuyen con la imagen. Ver [`sample_rss_feed.py`](backend/plugins/sample_rss_feed.py) y [`sample_web_scraper.py`](backend/plugins/sample_web_scraper.py).
- **Plugins subidos por el usuario**: se suben vía el endpoint `/plugins/upload`, se almacenan en `backend/plugins/user_uploaded/{plugin_id}.py`, con metadatos en la tabla `user_plugins`. Docker Compose configura un named volume para `/app/plugins/user_uploaded/` para que los plugins personalizados persistan tras reinicios del contenedor.

### Subida de Plugins

La página de plugins soporta la subida directa de archivos `.py` — no es necesario reconstruir la imagen para añadir plugins personalizados. La subida pasa por múltiples comprobaciones de seguridad:

1. **Comprobación de sintaxis AST**: rechaza código fuente que no se pueda analizar.
2. **Lista de importaciones prohibidas**: bloquea módulos peligrosos incluyendo `os` / `sys` / `subprocess` / `shutil` / `ctypes` / `socket` / `multiprocessing` / `importlib` / `pickle` / `marshal` / `pty` / `posix` / `nt` / `resource`.
3. **Comprobación de builtins peligrosos**: intercepta llamadas `eval` / `exec` / `__import__`.
4. **Validación del contrato**: debe exponer una clase `Plugin` válida con un método `manifest()`.
5. **Verificación de carga en módulo temporal**: importa el módulo desde una ruta temporal para asegurar que `manifest()` es invocable.

Endpoints de la API:

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/plugins/upload` | Sube un plugin de usuario (soporta `overwrite=true`) |
| `DELETE` | `/plugins/{id}` | Borrado lógico de un plugin de usuario (los plugins integrados no se pueden borrar) |
| `PATCH` | `/plugins/{id}/enabled` | Habilitar / deshabilitar un plugin de usuario |
| `POST` | `/plugins/{id}/run` | Captura + transformación + ingesta |

### Contribuir Plugins

Se aceptan Pull Requests para plugins personalizados:

1. Haz un fork del repositorio y crea el archivo del plugin en `backend/plugins/` (el nombre debe ser snake_case en minúsculas, p. ej. `my_feed.py`).
2. Implementa el contrato del plugin — asegúrate de que `manifest()` y `fetch()` funcionan correctamente.
3. Describe el propósito, parámetros y forma de probar el plugin en la descripción del PR.
4. Tras la revisión, se fusionará con la rama principal y se publicará con la siguiente versión.

---

## License

GNU Affero General Public License v3.0 — see [LICENSE](LICENSE) file for details.

---

<p align="center">
  <em>LifeTree · Que cada decisión importante esté basada en evidencia</em>
</p>
