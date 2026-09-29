FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

COPY pyproject.toml ./
COPY src/ ./src/
# The `lid` extra is not optional here, whatever it is called in pyproject.
# Without fasttext, GlotLID cannot load and probe/lid falls back to script-only:
# the gate keeps its script check and loses its language check entirely. That is
# a documented degraded mode for a machine that cannot run the model, not
# something a container should land in silently -- and the UI can start a scan.
RUN pip install --no-cache-dir -e ".[lid]"

# Schemes and results are data, not code: mounted at runtime so a user can supply
# their own locale list, and see their own scans, without rebuilding the image.
EXPOSE 8000
CMD ["uvicorn", "llmlc.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
