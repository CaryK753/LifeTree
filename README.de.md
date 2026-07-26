<h1 align="center">LifeTree · 人生树</h1>

<p align="center">
  <em>Ein intelligentes Informationssystem für mittel- bis langfristige persönliche Entscheidungsfindung: Aggregiert öffentliche und private Daten, kombiniert Wissensgraphen mit kausalem Reasoning und bietet einen dynamischen Entscheidungs-Sandbox für wichtige Lebensentscheidungen.</em>
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
  <strong>Sprachen / Languages:</strong>
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

## Inhaltsverzeichnis

- [Projektvorstellung](#projektvorstellung)
- [Systemarchitektur](#systemarchitektur)
- [Tech-Stack](#tech-stack)
- [Funktionen](#funktionen)
- [Schnellstart](#schnellstart)
- [Docker Ein-Klick-Bereitstellung](#docker-ein-klick-bereitstellung)
- [Lokale Entwicklung](#lokale-entwicklung)
- [Konfiguration](#konfiguration)
- [License](#license)

---

## Projektvorstellung

**LifeTree** ist ein intelligentes Informationssystem für mittel- bis langfristige persönliche Entscheidungsfindung. Es ist kein einfaches To-do-Listen- oder Notiztool, sondern ein dynamischer Entscheidungs-Sandbox, der Wissensgraphen, kausales Reasoning, Bayes'sche Netzwerke und Monte-Carlo-Simulation integriert.

### Welches Problem wird gelöst?

Beim Treffen wichtiger Lebensentscheidungen — Einwanderungswege, Karriereübergänge, Bildungsinvestitionen, Familienplanung — stehen wir oft vor:

- **Fragmentierte Informationen**: Relevante Daten sind über Browser-Lesezeichen, Chat-Verläufe und Dokumente verstreut, schwer zu systematisieren
- **Einseitiges Reasoning**: Wir sehen nur kurzfristige Vorteile und ignorieren langfristige Risiken und Opportunitätskosten
- **Statische Entscheidungen**: Nachdem eine Entscheidung getroffen wurde, wird sie nicht dynamisch aufgrund neuer Informationen revidiert

LifeTree löst diese Probleme durch:

1. **Informationsaggregation**: Automatisches Crawlen öffentlicher Daten (RSS / Web / API), manuelle Eingabe privater Daten (Dokumente / Bilder / Notizen), einheitliche Strukturierung als Wissensgraph-Knoten
2. **Kausale Modellierung**: Modelliert Ziel → Pfad → Anforderung → Risikofaktor als gerichteten Graphen, verwendet Bayes'sche Netzwerke zur Quantifizierung von Unsicherheit
3. **Szenario-Simulation**: Monte-Carlo-Simulation der Erfolgswahrscheinlichkeit, Risikoexposition und Zeitkosten unter verschiedenen Wahlpfaden
4. **Dynamische Warnung**: Celery-geplante Tasks überwachen die Informationsaktualität (Halbwertszeit-Modell), lösen automatisch Risikoneuberechnung und E-Mail-Warnungen aus
5. **KI-Berater**: LangGraph-basierter ReAct-Agent, der 15+ integrierte Tools aufrufen kann, um den Wissensgraphen abzufragen, neue Knoten zu erstellen, das Web zu durchsuchen und Seiteninhalte zu crawlen

### Beispielszenario

Dieses Repository enthält integrierte Beispieldaten für den **Kanadischen Federal Skilled Worker (FSW)**, der Folgendes abdeckt:

- Ziel: Einwanderung nach Kanada über den FSW-Kanal
- Pfad: EE-Pool-Eintritt → ITA-Einladung → Dokumenteneinreichung → Ärztliche Untersuchung → Landung
- Anforderungen: CLB 9 / ECA-Zertifikat / Arbeitsnachweis / Finanznachweis
- Risikofaktoren: Alterspunktabzüge, Schwankungen der Sprachscores, politische Änderungen, Quotenwettbewerb

---

## Systemarchitektur

```mermaid
graph TB
    subgraph Client["Frontend-Client (Next.js 16)"]
        UI[Seiten: Dashboard / Graph / Chat / Szenario / Quellen]
        PWA[PWA: Offline-Cache + Push]
        SSE_C[SSE-Client: Streaming-Chat]
    end

    subgraph API["Backend-API (FastAPI)"]
        REST[REST-API: CRUD / Abfrage]
        CHAT[Chat-SSE: Streaming-LLM-Chat]
        CRAWLER[Crawler-API: Tavily Suche/Fetch]
    end

    subgraph Agent["KI-Berater (LangGraph ReAct)"]
        GRAPH[create_react_agent]
        TOOLS[15+ Integrierte Tools<br/>Abfrage / Schreiben / Gedächtnis / Web]
        LLM[LLM: OpenAI / Anthropic / Bailian]
    end

    subgraph Worker["Asynchrone Tasks (Celery)"]
        BEAT[Beat: Geplante Tasks]
        TASKS[Tasks: Crawlen / Risiko-Neuberechnung /<br/>Halbwertszeit-Bereinigung / Benachrichtigung]
    end

    subgraph Storage["Datenschicht"]
        PG[(PostgreSQL 16<br/>+ pgvector)]
        NEO[(Neo4j 5<br/>Wissensgraph)]
        REDIS[(Redis 7<br/>Broker + Cache)]
        MINIO[(MinIO<br/>Objektspeicher)]
    end

    subgraph External["Externe Dienste"]
        TAVILY[Tavily-API<br/>Suche + Fetch]
        SMTP[SMTP<br/>E-Mail-Warnungen]
        LLM_API[LLM-Provider<br/>OpenAI / Bailian / Anthropic]
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

### Datenfluss

```mermaid
sequenceDiagram
    participant U as Benutzer
    participant F as Frontend
    participant B as Backend-API
    participant A as KI-Agent
    participant DB as PostgreSQL
    participant T as Tavily

    U->>F: Frage auf Chat-Seite eingeben
    F->>B: POST /api/v1/chat/stream (SSE)
    B->>A: create_react_agent.astream_events()
    A->>A: Reasoning: Werden Tools benötigt?
    A->>DB: list_pathways / list_risk_factors aufrufen
    DB-->>A: Wissensgraph-Daten zurückgeben
    A->>T: web_search aufrufen (wenn externe Infos nötig)
    T-->>A: Suchergebnisse zurückgeben
    A-->>B: Streaming-Text + Tool-Aufrufe
    B-->>F: SSE: delta + tool_call chunks
    F-->>U: Schreibmaschinen-Effekt + Inline-Tool-UI
```

---

## Tech-Stack

| Schicht | Technologie | Beschreibung |
|---|---|---|
| **Frontend** | Next.js 16 (App Router) | React 19, standalone output, PWA |
| | Vercel AI SDK | Streaming-Chat-Komponenten (Thread / Message / Composer) |
| | Tailwind CSS + Radix UI | Theme-System (hell/dunkel/System) |
| | Cytoscape.js + React Flow | Wissensgraph + Szenariobaum-Visualisierung |
| | ECharts | Statistische Diagramme |
| | SWR | Datenabruf und Caching |
| | i18n | 6 Sprachen: zh-CN / zh-TW / EN / ES / DE / FR |
| **Backend** | FastAPI | REST + SSE + Streaming-KI |
| | SQLAlchemy + Alembic | ORM + Migrationen |
| | Pydantic v2 | Datenvalidierung |
| | Instructor | LLM-strukturierte Ausgabe |
| | LangGraph | ReAct-Agent + Tool-Orchestrierung |
| | Celery + Beat | Asynchrone Tasks + geplante Tasks |
| **Datenbank** | PostgreSQL 16 + pgvector | Relationale Daten + Vektorsuche |
| | Neo4j 5 | Wissensgraph (APOC) |
| | Redis 7 | Celery-Broker + Cache |
| | MinIO | Objektspeicher (Datei-Uploads) |
| **LLM** | OpenAI-kompatibel | Unterstützt OpenAI / DeepSeek / Zhipu / vLLM |
| | Anthropic Claude | Natives Protokoll |
| | Alibaba Cloud Bailian DashScope | Chat / Vision / Embedding / Rerank |
| **Bereitstellung** | Docker Compose | Ein-Klick-Vollstack-Start |
| | GitHub Actions | CI/CD Multi-Arch-Image-Build |
| | GHCR | Image-Registry |

---

## Funktionen

### Kernmodule

- **Zielkompass**: Dashboard-artiges Zielmanagement, Fortschritts-, Frist- und Risikostatus-Tracking
- **Wissensgraph**: Cytoscape-Kraftgerichteter-Layout, Knoten = Entitäten, Kanten = Beziehungen, Klick-Erkundung
- **KI-Berater**: Streaming-Chat, 15+ integrierte Tools (Abfrage / Schreiben / Gedächtnis / Web-Suche / Web-Fetch), Inline-Rendern der Tool-Aufruf-UI
- **Szenario-Simulation**: React Flow + dagre-Baumlayout, Monte-Carlo-Simulation, Verzweigungswahrscheinlichkeitsringe + Risikoindikatoren
- **Quellenverwaltung**: Glaubwürdigkeitsbewertung (hoch / mittel / niedrig / benutzermarkiert), Informationshalbwertszeit-Management (exponentielles Zerfallsmodell)
- **Risikowarnung**: Benachrichtigungscenter, Schweregrad-Einstufung (dringend / Warnung / Info), SMTP-E-Mail-Versand
- **Informationseingabe**: Drag-and-Drop-Upload (PDF / Word / Excel / PPT / Bilder), Mineru-Parsing, KI-strukturierte Extraktion

### Integrierte KI-Tools

| Tool | Typ | Beschreibung |
|---|---|---|
| `list_pathways` | Abfrage | Alle Pfade für ein Ziel auflisten |
| `list_requirements` | Abfrage | Eintrittsanforderungen für einen Pfad auflisten |
| `list_risk_factors` | Abfrage | Risikofaktoren auflisten |
| `list_recent_events` | Abfrage | Letzte Ereignisse auflisten |
| `get_scenario_summary` | Abfrage | Szenariozusammenfassung abrufen |
| `run_scenario_reasoning` | Reasoning | Bayes'sche/Monte-Carlo-Reasoning ausführen |
| `create_goal` / `create_pathway` / `create_requirement` / `create_risk_factor` | Schreiben | Wissensgraph-Knoten erstellen |
| `list_memories` / `remember` / `forget` | Gedächtnis | Langzeitgedächtnis-Verwaltung des Benutzers |
| `web_search` | Web | Tavily-Websuche |
| `web_fetch` | Web | Tavily-Webinhalt-Fetch |

### PWA-Funktionen

- Offline-Cache (App Shell + statische Ressourcen + API-Antworten)
- Streaming-Chat umgeht Cache (`/api/v1/chat/stream` direkt zum Backend)
- Installation auf Desktop / mobilem Home-Screen
- Themefarbe passt sich an Hell-/Dunkel-Modus an

---

## Schnellstart

### Voraussetzungen

- Docker + Docker Compose
- Oder: Python 3.11+, Node.js 20+, pnpm/npm

### Option 1: Docker Ein-Klick-Start (Empfohlen)

```bash
# 1. Repository klonen
git clone https://github.com/CaryK753/LifeTree.git
cd LifeTree

# 2. Umgebungsvariablen konfigurieren
cp .env.example .env
# .env bearbeiten, mindestens einen LLM-API-Key ausfüllen

# 3. Ein-Klick-Vollstack-Start (Infrastruktur + Backend + Worker + Frontend)
docker compose up -d --build

# 4. Datenbank initialisieren (erster Lauf)
docker compose exec backend python scripts/init_db.py

# 5. Beispieldaten laden (optional)
docker compose exec backend python scripts/seed_fsw.py
```

Nach dem Start besuchen:
- Frontend: http://localhost:3000
- Backend-API: http://localhost:8000
- API-Dokumentation: http://localhost:8000/docs
- Flower (Celery-Monitor): http://localhost:5555
- MinIO-Konsole: http://localhost:9001
- Neo4j-Browser: http://localhost:7474

### Option 2: Lokale Entwicklung

Siehe Abschnitt [Lokale Entwicklung](#lokale-entwicklung).

---

## Docker Ein-Klick-Bereitstellung

Die vollständige `docker-compose.yml` umfasst folgende Dienste:

| Dienst | Image | Port | Beschreibung |
|---|---|---|---|
| `postgres` | `pgvector/pgvector:pg16` | 5432 | PG + pgvector-Vektorerweiterung |
| `neo4j` | `neo4j:5.20` | 7687, 7474 | Wissensgraph + APOC |
| `redis` | `redis:7-alpine` | 6379 | Celery-Broker + Cache |
| `minio` | `minio/minio:latest` | 9000, 9001 | Objektspeicher |
| `backend` | Lokaler Build | 8000 | FastAPI-Anwendung |
| `worker` | Lokaler Build | - | Celery-Worker |
| `beat` | Lokaler Build | - | Celery-Beat-Scheduler |
| `flower` | `mher/flower:latest` | 5555 | Celery-Monitor |
| `frontend` | Lokaler Build | 3000 | Next.js standalone |

```bash
# Alle Dienste starten
docker compose up -d --build

# Logs anzeigen
docker compose logs -f backend frontend

# Stoppen
docker compose down

# Stoppen und Datenvolumes löschen
docker compose down -v
```

### Vordefinierte Images verwenden (GHCR)

```bash
# Neueste Images pullen
docker pull ghcr.io/caryk753/lifetree-backend:latest
docker pull ghcr.io/caryk753/lifetree-frontend:latest

# In docker-compose.yml build durch image ersetzen
# backend:
#   image: ghcr.io/caryk753/lifetree-backend:latest
# frontend:
#   image: ghcr.io/caryk753/lifetree-frontend:latest
```

---

## Lokale Entwicklung

### 1. Infrastruktur starten

```bash
cp .env.example .env
# .env bearbeiten, LLM_API_KEY etc. ausfüllen

# Nur Infrastrukturdienste starten
docker compose up -d postgres neo4j redis minio
```

### 2. Backend starten

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Tabellen erstellen (erster Lauf)
python scripts/init_db.py

# API starten
uvicorn app.main:app --reload --port 8000

# In anderem Terminal: Celery-Worker + Beat starten
celery -A app.workers.celery_app worker -l info
celery -A app.workers.celery_app beat -l info
```

### 3. Frontend starten

```bash
cd frontend
npm install
npm run dev
```

### 4. Beispieldaten laden

```bash
cd backend
python scripts/seed_fsw.py
```

http://localhost:3000 öffnen, um das Zielkompass-Dashboard zu sehen.

---

## Konfiguration

### LLM-Konfiguration

LLM-Provider auf der Einstellungsseite (`/settings`) konfigurieren:

1. **Provider hinzufügen**: Protokoll wählen (OpenAI-kompatibel / Anthropic / Alibaba Cloud Bailian), baseURL und API-Key ausfüllen
2. **Modell hinzufügen**: Modell-ID ausfüllen (z.B. `gpt-4o-mini`), Fähigkeiten aktivieren (chat / vision / embedding / rerank)
3. **Rollen zuweisen**: Für jede Rolle ein Modell auswählen

Unterstützte Provider:
- **OpenAI-kompatibel**: OpenAI / DeepSeek / Zhipu / OneAPI / vLLM
- **Anthropic**: Claude-Serie (chat / vision)
- **Alibaba Cloud Bailian**: Qwen / gte-rerank / qwen3-rerank
  - Chat / Vision / Embedding über OpenAI-kompatibles Protokoll
  - Rerank wird automatisch an den nativen Endpunkt `/api/v1/services/rerank/text-rerank/text-rerank` geroutet
  - Embedding standardmäßig 1024 Dimensionen

### Tavily-Suchkonfiguration

Tavily-API-Key auf der Einstellungsseite ausfüllen, um zu aktivieren:
- `web_search`- und `web_fetch`-Tools des KI-Beraters
- Quellen-Crawling (RSS / Web-Crawling)

### SMTP-E-Mail-Konfiguration

SMTP auf der Einstellungsseite konfigurieren, um den Versand von Risikowarnungs-E-Mails zu aktivieren. Unterstützt den Versand von Test-E-Mails zur Konfigurationsprüfung.

### Umgebungsvariablen

Die vollständige Variablenliste finden Sie in [`.env.example`](.env.example).

---

## License

GNU Affero General Public License v3.0 — see [LICENSE](LICENSE) file for details.

---

<p align="center">
  <em>LifeTree · Jede wichtige Entscheidung evidenzbasiert treffen</em>
</p>
