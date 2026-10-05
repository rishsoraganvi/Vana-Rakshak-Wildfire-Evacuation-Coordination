FROM python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f

WORKDIR /app
COPY packages/wildfire_core /app/packages/wildfire_core
COPY apps/api_gateway /app/apps/api_gateway
COPY config /app/config
RUN pip install --no-cache-dir /app/packages/wildfire_core /app/apps/api_gateway

EXPOSE 8000
CMD ["uvicorn", "api_gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]
