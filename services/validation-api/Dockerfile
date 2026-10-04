FROM python:3.12-slim

WORKDIR /app

# scripts/common/validation.py es la única fuente de verdad — se copia
# junto al servicio en vez de reimplementarse.
COPY services/validation-api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY scripts/common /app/scripts/common
COPY services/validation-api/app.py .

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
