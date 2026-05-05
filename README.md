# Pingula Core Service

Pingula, FastAPI + React tabanlı bir soru üretim ve içerik yönetim platformudur.

Ana yetenekler:
- DB-first içerik modeli (`curriculum`, `property_definitions`, `yaml_templates`, `yaml_instances`)
- Full/Sub/Standalone pipeline akışları
- Legacy pipeline akışı (geometry + turkce)
- MinIO tabanlı asset saklama (`catalog`, `generated`, `rendered`)
- Katalog görsel yönetimi (listeleme, fuzzy arama, yükleme, silme)
- Kimlik doğrulama (register/login/token)

## Mimari Özeti

- Backend: FastAPI (`app/`)
- Frontend: React + Vite (`frontend/`)
- Veritabanı: PostgreSQL (önerilen), SQLite fallback (default)
- Object Storage: MinIO (S3 uyumlu)

Temel backend router’ları:
- `/v1/auth` (auth)
- `/v1/pipelines`, `/v1/sub-pipelines`, `/v1/runtime-info`
- `/v1/agents/*` (standalone agent endpointleri)
- `/v1/legacy/*` (legacy pipeline ve output erişimi)
- `/v1/catalog-assets/*` (katalog görsel yönetimi)
- `/v1/*` content/curriculum/template/instance/artifact uçları

## Gereksinimler

- Python `>=3.12`
- Node.js `>=20`
- `uv`
- Docker (Postgres + MinIO için önerilir)

## Hızlı Başlangıç (Local)

### 1) Altyapıyı kaldır

```bash
docker compose up -d
```

Bu compose dosyası şunları ayağa kaldırır:
- Postgres: `localhost:5434`
- MinIO S3 API: `localhost:9000`
- MinIO Console: `localhost:9001`

MinIO varsayılan:
- user: `pingula`
- password: `pingula-secret`

### 2) Ortam değişkenlerini hazırla

```bash
cp .env.example .env
```

Önerilen minimum `.env`:
- `DATABASE_URL=postgresql+psycopg://pingula:pingula@localhost:5434/pingula`
- `S3_ENDPOINT_URL=http://localhost:9000`
- `S3_ACCESS_KEY=pingula`
- `S3_SECRET_KEY=pingula-secret`
- `S3_BUCKET_CATALOG=catalog-assets`
- `S3_BUCKET_GENERATED=generated-assets`
- `S3_BUCKET_RENDERED=rendered-outputs`
- `GOOGLE_API_KEY` veya `ANTHROPIC_API_KEY` (opsiyonel ama gerçek model için gerekli)

Not:
- API key yoksa sistem varsayılan olarak `stub` moduna düşer.
- `AI_USE_STUB=1` ile manuel stub zorlanabilir.

### 3) Backend’i çalıştır

```bash
uv run uvicorn main:app --reload
```

Backend: `http://127.0.0.1:8000`

### 4) Frontend’i çalıştır

```bash
cd frontend
npm install
npm run dev
```

Frontend: `http://127.0.0.1:5173`

## Frontend Sayfaları (Güncel Navigasyon)

- Ana Sayfa
- Full Pipeline
- Sub-Pipelines
- Standalone Agents
- Müfredat Yönetimi
- Katalog Görselleri
- YAML Oluştur
- Legacy Pipeline

Ek not:
- `FilesPage` ve `TemplatesPage` kodda geçici olarak tutulur, ancak ana nav’dan kaldırılmıştır.

## Önemli Akışlar

### Full Pipeline

YAML instance girdi alır ve Question/Layout/HTML + render image üretir.

Önemli endpoint:
- `POST /v1/pipelines/full/run`

### Sub-Pipelines

- `POST /v1/pipelines/sub/yaml-to-question/run`
- `POST /v1/pipelines/sub/question-to-layout/run`
- `POST /v1/pipelines/sub/layout-to-html/run`

### Standalone Agents

- `POST /v1/agents/main/generate-question/run`
- `POST /v1/agents/main/generate-layout/run`
- `POST /v1/agents/main/generate-html/run`
- `POST /v1/agents/validation/extract-rules/run`
- `POST /v1/agents/validation/evaluate-rule/run`
- `POST /v1/agents/validation/validate-question-layout/run`
- `POST /v1/agents/validation/validate-layout-html/run`
- `POST /v1/agents/helper/generate-composite-image/run`

### Legacy Pipeline

Legacy output’lar disk/DB yerine ephemeral memory store’da tutulur.

Temel kurallar:
- session header: `X-Session-Id` (frontend bunu otomatik üretir)
- TTL: `30 dk`
- limit: `50MB/artifact`, `250MB/session`
- limit aşımında: en eski run paketleri paket bazında evict edilir

Önemli endpointler:
- `POST /v1/legacy/pipelines/{kind}/batch-run`
- `GET /v1/legacy/runs/{run_id}`
- `GET /v1/legacy/runs/{batch_id}/batch`
- `GET /v1/legacy/runs/{run_id}/download`

### Katalog Görselleri

Yeni katalog yönetim API’si:
- `GET /v1/catalog-assets` (cursor + limit + fuzzy query)
- `POST /v1/catalog-assets` (upload)
- `DELETE /v1/catalog-assets/{key}` (delete)
- `GET /v1/catalog-assets/{key}/content` (image content)

## İçerik Yönetimi (DB-first)

CRUD endpoint grupları:
- `properties`
- `yaml-templates`
- `yaml-instances`
- `curriculum nodes/tree`
- `artifacts`

Bu modelde pipeline girişleri dosya yerine DB kayıtlarından gelir (`yaml_instance_id`).

## Test ve Build

Backend test:

```bash
uv run pytest -q
```

Frontend:

```bash
cd frontend
npm run test
npm run build
```

## Dizin Yapısı

- `app/`: FastAPI backend
- `frontend/`: React UI
- `legacy_app/`: legacy pipeline modülleri
- `catalog/`: katalog kaynak görselleri
- `docs/`: proje dokümantasyonu

## Güvenlik Notu

- `.env` dosyasını repoya commit etmeyin.
- API anahtarları sızdıysa hemen rotate edin.
