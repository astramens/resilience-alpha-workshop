FROM python:3.12-slim
WORKDIR /app
COPY sanitize.py gateway.py collector.py ./
RUN mkdir /state && chown 65532:65532 /state
USER 65532:65532
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
CMD ["python", "collector.py"]
