FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir -e .

# Schemes are data, not code: mounted at runtime so a user can supply their own
# locale list without rebuilding the image.
EXPOSE 8000
CMD ["uvicorn", "llmlc.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
