import os
import secrets
import threading
import time
import json
from ansible_runner import run_playbook, PlaybookError
import requests
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel

app = FastAPI(title="RESILIENCE-ALPHA Remediation")
BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")
lock = threading.Lock()
last_restart = 0.0
TOKEN = os.environ["REMEDIATION_TOKEN"]

class Alert(BaseModel):
    service: str = "backend"
    reason: str
    metrics: dict = {}


@app.get("/health")
def health():
    return {"status": "ok", "service": "remediation", "executor": "ansible"}

@app.post("/alerts", status_code=202)
def remediate(alert: Alert, authorization: str = Header(default="")):
    global last_restart
    if not TOKEN or not secrets.compare_digest(authorization.encode(), ("Bearer " + TOKEN).encode()):
        raise HTTPException(401, "Unauthorized")
    if alert.service != "backend":
        raise HTTPException(status_code=400, detail="unsupported service")
    with lock:
        if time.monotonic() - last_restart < 60:
            raise HTTPException(429, "Remediation cooldown active")
        last_restart = time.monotonic()
    try:
        result = run_playbook()
        print(json.dumps({"event": "ansible_repair_completed", **result}), flush=True)
        deadline = time.monotonic() + 25
        healthy = False
        while time.monotonic() < deadline:
            try:
                response = requests.get(f"{BACKEND_URL}/health", timeout=3)
                if response.ok:
                    healthy = True
                    # The probe verifies catalogue/DB readiness, never a paid order.
                    probe = requests.get(f"{BACKEND_URL}/internal/business-probe", timeout=5,
                                         headers={"Authorization": "Bearer " + TOKEN})
                    data = probe.json() if probe.ok else {}
                    if (data.get("scope") == "catalogue_and_rollback_write"
                            and data.get("transactional_readiness_verified") is True
                            and data.get("writes_rolled_back") is True
                            and data.get("business_recovery_verified") is False):
                        return {"status": "technical_restored", "technical_recovery_verified": True,
                                "business_recovery_verified": False, "payment_verified": False,
                                "waiting_for": "new_paid_stripe_test_order",
                                "executor": "ansible"}
            except (requests.RequestException, ValueError, TypeError, AttributeError):
                pass
            time.sleep(2)
        if healthy:
            return {"status": "health_restored", "technical_recovery_verified": False, "business_recovery_verified": False,
                    "executor": "ansible"}
        raise HTTPException(status_code=504, detail="backend recovery not confirmed after the playbook")
    except PlaybookError:
        print(json.dumps({"event": "ansible_repair_failed", "playbook_success": False}), flush=True)
        raise HTTPException(status_code=503, detail="Scoped Ansible action failed or unconfirmed")
