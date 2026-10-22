import json
import math
import os
import time
import uuid
from pathlib import Path
from datetime import datetime, timezone

import requests
from sklearn.ensemble import IsolationForest

BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")
REMEDIATION_URL = os.getenv("REMEDIATION_URL", "http://remediation:9000")
INTERVAL = max(1.0, float(os.getenv("POLL_INTERVAL_SECONDS", "10")))
BASELINE_SAMPLES = 20
COOLDOWN_SECONDS = 120


def log(event, **fields):
    print(json.dumps({"event": event, **fields}, ensure_ascii=True), flush=True)


class Detector:
    def __init__(self, state_path=None):
        self.model = IsolationForest(contamination="auto", random_state=42)
        self.baseline = []
        self.ready = False
        self.health_failures = 0
        self.last_attempt = -math.inf
        # Offline reports are persisted without credentials or raw remote replies.
        self.state_path = Path(state_path) if state_path else None
        self.pending = {}
        self.verified_refs = set()
        if self.state_path and self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text())
                if not isinstance(data, dict) or len(data) > 1000: raise ValueError()
                self.pending = data
            except (ValueError, OSError):
                raise RuntimeError("Pending recovery state invalid; preserve the volume for review") from None

    def save(self):
        if self.state_path:
            temporary = self.state_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self.pending), encoding="utf-8")
            temporary.replace(self.state_path)

    def reconcile(self, session, token):
        try:
            response = session.post(f"{BACKEND_URL}/internal/recovery/reconcile", timeout=4,
                                    headers={"Authorization": "Bearer " + token})
            response.raise_for_status()
            for incident in response.json().get("incidents", []):
                ref = incident.get("ref")
                if (incident.get("state") == "business_verified"
                        and incident.get("business_recovery_verified") is True
                        and ref not in self.verified_refs):
                    self.verified_refs.add(ref)
                    log("recovery_business_verified", ref=ref, business_recovery_verified=True)
        except (requests.RequestException, ValueError, TypeError, AttributeError):
            log("recovery_verification_unavailable", action="observe_only")

    def observe(self, healthy, latency_ms, error_rate=None):
        """latency_ms is THIS health probe's duration, never an old API request."""
        if not math.isfinite(latency_ms) or latency_ms < 0:
            raise ValueError("Invalid probe duration")
        if error_rate is not None and (not math.isfinite(error_rate) or not 0 <= error_rate <= 1):
            raise ValueError("Invalid error rate")
        self.health_failures = 0 if healthy else self.health_failures + 1
        # Missing metrics are not fabricated as actual measurements.
        sample = [latency_ms]
        anomaly = bool(self.model.predict([sample])[0] == -1) if self.ready else None
        # Fit only once. Production calibration and evaluation remain separate work.
        if healthy and error_rate == 0 and not self.ready:
            self.baseline.append(sample)
            if len(self.baseline) >= BASELINE_SAMPLES:
                self.model.fit(self.baseline)
                self.ready = True
                log("model_calibrated", samples=len(self.baseline))
        reason = None
        if not healthy and self.health_failures >= 3 and anomaly is True:
            reason = "ml_anomaly_with_confirmed_health_failure"
        elif not healthy and self.health_failures >= 6:
            reason = "availability_fallback_six_failed_health_probes"
        return {"healthy": healthy, "probe_latency_ms": round(latency_ms, 2),
                "error_rate": error_rate, "ml_ready": self.ready, "ml_anomaly": anomaly,
                "health_failures": self.health_failures, "baseline_samples": len(self.baseline),
                "recovery_reason": reason}

    def report(self, session, token, incident):
        if incident["ref"] not in self.pending and len(self.pending) >= 1000:
            raise RuntimeError("Pending recovery report capacity reached")
        self.pending[incident["ref"]] = dict(incident)
        self.save()
        self.flush(session, token)

    def flush(self, session, token):
        for ref, state in list(self.pending.items()):
            try:
                response = session.post(f"{BACKEND_URL}/internal/incidents", json=state, timeout=3,
                                        headers={"Authorization": "Bearer " + token})
            except requests.RequestException:
                return
            if response.ok and self.pending.get(ref) == state:
                del self.pending[ref]
                self.save()
            elif response.status_code in (400, 401, 409, 422):
                # Keep rejected reports for review/credential repair; never silently discard evidence.
                log("incident_report_rejected", ref=ref, http_status=response.status_code)
                return

    def dispatch(self, observation, session, token, now=None):
        now = time.monotonic() if now is None else now
        if not observation["recovery_reason"]:
            return False
        if now - self.last_attempt < COOLDOWN_SECONDS:
            log("recovery_cooldown", health_failures=self.health_failures)
            return False
        # Record BEFORE sending, including on 429/timeout. Never recursively alert.
        self.last_attempt = now
        incident = {"ref": "INC-" + uuid.uuid4().hex[:12], "status": "remediation",
                    "reason": observation["recovery_reason"], "action": "redemarrage_api_boutique",
                    "detail": observation, "opened_at": datetime.now(timezone.utc).isoformat()}
        self.report(session, token, incident)
        try:
            response = session.post(
                f"{REMEDIATION_URL}/alerts",
                headers={"Authorization": "Bearer " + token},
                json={"service": "backend", "reason": observation["recovery_reason"],
                      "metrics": observation}, timeout=60)
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict): raise ValueError("Invalid remediation response")
            technical = result.get("technical_recovery_verified") is True
            # A dry-run/health response cannot assert a successful payment.
            safe_result = {"technical_recovery_verified": technical, "business_recovery_verified": False}
            incident.update(status="attente_metier" if technical else "echec", result=safe_result,
                            business_verified=False)
            self.report(session, token, incident)
            log("recovery_reported", ref=incident["ref"], technical_recovery_verified=technical,
                business_recovery_verified=False, reason=observation["recovery_reason"])
            return technical
        except (requests.RequestException, ValueError) as exc:
            incident.update(status="echec", result={"error": exc.__class__.__name__}, business_verified=False,
                            closed_at=datetime.now(timezone.utc).isoformat())
            self.report(session, token, incident)
            log("recovery_request_failed", retry_after_seconds=COOLDOWN_SECONDS)
            return False


def poll(detector, session, token):
    started = time.perf_counter()
    try:
        response = session.get(f"{BACKEND_URL}/health", timeout=5)
        # Only server failure supports restarting the API. 4xx means a probe/config issue.
        if response.status_code != 200 and response.status_code < 500:
            detector.health_failures = 0
            log("probe_configuration_error", http_status=response.status_code)
            return
        healthy = response.status_code == 200
    except (requests.ConnectionError, requests.Timeout):
        healthy = False
    except requests.RequestException:
        detector.health_failures = 0
        log("health_collection_error")
        return

    duration = (time.perf_counter() - started) * 1000
    error_rate = None

    if healthy:
        try:
            response = session.get(
                f"{BACKEND_URL}/internal/metrics", timeout=5
            )
            response.raise_for_status()
            error_rate = float(response.json()["error_rate"])
        except (requests.RequestException, ValueError, KeyError, TypeError):
            log("metrics_collection_error", action="observe_only")

    detector.flush(session, token)
    if healthy:
        detector.reconcile(session, token)
    observation = detector.observe(healthy, duration, error_rate)
    log("observation", **observation)
    detector.dispatch(observation, session, token)


def main():
    token = os.environ["REMEDIATION_TOKEN"]
    if not token:
        raise RuntimeError("Missing remediation token")

    detector = Detector(os.getenv("STATE_PATH"))
    log(
        "detector_started",
        baseline_samples=BASELINE_SAMPLES,
        poll_interval_seconds=INTERVAL,
        cooldown_seconds=COOLDOWN_SECONDS,
    )

    with requests.Session() as session:
        while True:
            try:
                poll(detector, session, token)
            except (ValueError, KeyError, TypeError):
                detector.health_failures = 0
                log("invalid_observation", action="observe_only")
            time.sleep(INTERVAL)


if __name__ == "__main__":
    main()