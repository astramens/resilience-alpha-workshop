FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY remediator.py ansible_runner.py ./
COPY ansible ./ansible
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp/rearm-ansible
RUN chmod -R a+rX /app
USER 65532:65532
EXPOSE 9000
CMD ["uvicorn", "remediator:app", "--host", "0.0.0.0", "--port", "9000", "--no-proxy-headers"]
