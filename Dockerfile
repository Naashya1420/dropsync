# DropSync demo server: builds the web app and serves it with the FastAPI service.
# Only what the demo needs at runtime is copied in (published profiles, metrics, road graph).

FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements-deploy.txt .
RUN pip install --no-cache-dir -r requirements-deploy.txt
COPY backend/ backend/
COPY pipeline/__init__.py pipeline/config.py pipeline/
COPY data/study_area.json data/
COPY data/out/meta.json data/out/profiles.json data/out/sites.json data/out/lab.json data/out/
COPY data/eval/ data/eval/
COPY data/osm/city/graph.graphml data/osm/city/restaurants.json data/osm/city/meta.json data/osm/city/
COPY --from=web /web/dist web/dist
RUN useradd -m app && mkdir -p data/field && chown -R app data
USER app
EXPOSE 8000
# hosts (Render, etc.) pass the port in $PORT
CMD ["sh", "-c", "uvicorn backend.app:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
