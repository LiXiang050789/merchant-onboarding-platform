#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "[1/5] start mysql + mongo"
docker compose -f deploy/docker-compose.yml up -d mysql mongo

echo "[2/5] load 10w seed into MySQL"
backend/.venv/bin/python scripts/load_seed.py --reset

echo "[3/5] run backend smoke tests"
backend/.venv/bin/pytest backend/tests/test_docs.py backend/tests/test_frontend_contract.py --junitxml=artifacts/test/demo_smoke.xml

echo "[4/5] run P6 evidence scripts"
PYTHONPATH=/home/lx/spark/python/lib/pyspark.zip:/home/lx/spark/python/lib/py4j-0.10.9.7-src.zip \
SPARK_HOME=/home/lx/spark \
backend/.venv/bin/python scripts/compare_spark_python.py
backend/.venv/bin/python scripts/rag_demo.py
backend/.venv/bin/python scripts/forecast_reports.py

echo "[5/5] start services"
echo "Backend:  backend/.venv/bin/uvicorn backend.app.main:app --host 127.0.0.1 --port 8000"
echo "Frontend: cd frontend && npm run dev"
echo "Demo login: admin@example.com / seed-pass"
