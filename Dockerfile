# --- Map viewer (React + TypeScript), built to static files ---------------------------------
FROM node:22-alpine AS viewer
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# The viewer bundles the sample files for its "Try a sample" buttons.
COPY samples/ ../samples/
RUN npm run build

# --- API ------------------------------------------------------------------------------------
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

# Shapely, pyproj and pyogrio ship manylinux wheels that bundle GEOS, PROJ and GDAL,
# so no system packages are needed.
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install .
COPY --from=viewer /build/frontend/dist ./frontend/dist

# Create the upload directory in the image so named volumes mounted there inherit its owner.
RUN useradd --create-home --uid 1000 api && mkdir -p /srv/data/uploads && chown -R api /srv/data
USER api

ENV GEOAPI_DATABASE_URL=sqlite:////srv/data/geoapi.db \
    GEOAPI_STORAGE_DIR=/srv/data/uploads \
    GEOAPI_FRONTEND_DIR=/srv/frontend/dist
VOLUME ["/srv/data"]

EXPOSE 8000
# PORT is provided by hosts such as Render, Railway and Fly.io. Proxy headers make redirects
# keep the public https:// scheme behind their load balancers.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
