FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py security.py face_auth.py face_rules.py ./
RUN useradd --system --uid 10001 app
USER app
EXPOSE 8000
CMD ["python", "lab_entrypoint.py"]

COPY common.py customer_auth.py auth_app.py shop.py payments.py monitoring_status.py ./
USER 10001:10001

COPY recovery.py ./
COPY lab_redos.py ./
COPY lab_entrypoint.py ./
