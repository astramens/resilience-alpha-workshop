import os
import secrets
import threading
import time
import docker
import requests
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel

app = FastAPI(title="RESILIENCE-ALPHA Remediation")
BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")
lock = threading.Lock()
last_restart = 0.0
TOKEN = os.environ["REMEDIATION_TOKEN"]
COMPOSE_PROJECT = os.environ["COMPOSE_PROJECT"]
TARGET_CONTAINER = os.getenv("TARGET_CONTAINER", "")

class Alert(BaseModel):
    service: str = "backend"
    reason: str
    metrics: dict = {}


def backend_container(client):
    candidates = client.containers.list(all=True, filters={"label": [
        "com.docker.compose.service=backend", "com.docker.compose.project=" + COMPOSE_PROJECT]})
    if TARGET_CONTAINER:
        candidates = [c for c in candidates if c.name == TARGET_CONTAINER]
    if len(candidates) != 1:
        raise HTTPException(409, "Expected exactly one backend in the configured Compose project")
    return candidates[0]

@app.get("/health")
def health():
    return {"status": "ok", "service": "remediation"}

@app.post("/alerts", status_code=202)
def remediate(alert: Alert, authorization: str = Header(default="")):
    global last_restart
    if not secrets.compare_digest(authorization, "Bearer " + TOKEN):
        raise HTTPException(401, "Unauthorized")
    if alert.service != "backend":
        raise HTTPException(status_code=400, detail="unsupported service")
    with lock:
        if time.monotonic() - last_restart < 60:
            raise HTTPException(429, "Remediation cooldown active")
        last_restart = time.monotonic()
    try:
        client = docker.from_env()
        container = backend_container(client)
        container.restart(timeout=10)
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                response = requests.get(f"{BACKEND_URL}/health", timeout=3)
                if response.ok:
                    return {"status": "health_restored", "business_recovery_verified": False, "container": container.name, "reason": alert.reason}
            except requests.RequestException:
                pass
            time.sleep(2)
        raise HTTPException(status_code=504, detail="backend did not recover within 30 seconds")
    except docker.errors.DockerException as exc:
        raise HTTPException(status_code=503, detail=f"docker remediation failed: {exc.__class__.__name__}")
