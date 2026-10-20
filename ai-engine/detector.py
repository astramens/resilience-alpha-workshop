import json
import math
import os
import time

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
    def __init__(self):
        self.model = IsolationForest(contamination="auto", random_state=42)
        self.baseline = []
        self.ready = False
        self.health_failures = 0
        self.last_attempt = -math.inf

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

    def dispatch(self, observation, session, token, now=None):
        now = time.monotonic() if now is None else now
        if not observation["recovery_reason"]:
            return False
        if now - self.last_attempt < COOLDOWN_SECONDS:
            log("recovery_cooldown", health_failures=self.health_failures)
            return False
        # Record BEFORE sending, including on 429/timeout. Never recursively alert.
        self.last_attempt = now
        try:
            response = session.post(
                f"{REMEDIATION_URL}/alerts",
                headers={"Authorization": "Bearer " + token},
                json={"service": "backend", "reason": observation["recovery_reason"],
                      "metrics": observation}, timeout=60)
            response.raise_for_status()
            result = response.json()
            if result.get("status") not in ("health_restored", "remediated"):
                log("recovery_unconfirmed", http_status=response.status_code)
                return False
            log("health_recovery_reported", business_recovery_verified=False,
                reason=observation["recovery_reason"])
            return True
        except (requests.RequestException, ValueError):
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

    observation = detector.observe(healthy, duration, error_rate)
    log("observation", **observation)
    detector.dispatch(observation, session, token)


def main():
    token = os.environ["REMEDIATION_TOKEN"]
    if not token:
        raise RuntimeError("Missing remediation token")

    detector = Detector()
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