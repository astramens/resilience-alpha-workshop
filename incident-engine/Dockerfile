FROM python:3.12-slim
WORKDIR /app
RUN mkdir /state && chown 65532:65532 /state
COPY engine.py ./
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 65532:65532
CMD ["python", "engine.py"]
