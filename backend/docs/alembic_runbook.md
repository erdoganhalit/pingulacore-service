# Alembic Runbook

Bu proje için şema değişikliği tek kaynağı Alembic revision dosyalarıdır.

## 1) Yeni/Geliştirme DB

```bash
cd backend
uv run alembic upgrade head
```

## 2) Mevcut veri dolu DB (baseline geçişi)

Bu adım sadece ilk geçişte bir kez yapılır.

```bash
cd backend
uv run alembic stamp head
```

Ardından yeni release'lerde backend container açılışında otomatik:

```bash
alembic upgrade head
```

## 3) Developer migration üretme akışı

```bash
cd backend
uv run alembic revision --autogenerate -m "add_<feature>"
uv run alembic upgrade head
uv run alembic check
```

`alembic check` başarısızsa model değişikliği için migration eksiktir.

## 4) CI kuralı

CI, `alembic check` ile migration disiplini uygular.
Model değiştiği halde revision dosyası yoksa pipeline fail olur.
