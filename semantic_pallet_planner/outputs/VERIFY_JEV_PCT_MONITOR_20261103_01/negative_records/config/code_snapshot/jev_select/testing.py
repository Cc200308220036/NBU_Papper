"""Explicit offline native-wire test double. Never used by a remote branch."""
from __future__ import annotations


from .contracts import canonical
from .transport import JevTransport, outcome, strict_json

SCENARIOS = ("normal", "pick_last", "invalid_choice", "wrong_model", "wrong_probabilities", "non_json", "timeout", "http_429", "http_529")


class OfflineTransport(JevTransport):
    origin = "test_double"

    def __init__(self, config, scenario="normal"):
        super().__init__(config)
        if scenario not in SCENARIOS:
            raise ValueError("unknown offline scenario")
        self.scenario = scenario
        self.calls = 0

    def complete(self, body):
        # Exercise identical native UTF-8 serialization; no pre-parsed shortcut.
        encoded = self.encode(body)
        wire = strict_json(encoded)
        self.calls += 1
        if self.scenario == "timeout":
            return outcome("UNKNOWN_IN_FLIGHT", error="SIMULATED_TIMEOUT")
        if self.scenario.startswith("http_"):
            status = int(self.scenario[5:])
            return outcome("PROVIDER_FAILURE", http_status=status, error=f"HTTP_{status}")
        if self.scenario == "non_json":
            return outcome("OK", b"not JSON", http_status=200)
        options = wire["questions"]["next_action"]["criteria"]
        if self.scenario == "pick_last":
            selected = sorted(options)[-1]
        else:
            selected = min(options, key=lambda l: (-options[l]["features"]["geometry_score"],
                           options[l]["pose"]["x_mm"], options[l]["pose"]["y_mm"],
                           options[l]["pose"]["z_base_mm"], options[l]["pose"]["yaw_deg"], options[l]["pick_object"]))
        answer = {"type": "choice", "choice": selected,
                  "probabilities": {label: float(label == selected) for label in options}, "confidence": 1.}
        payload = {"model": wire["model"], "answers": {"next_action": answer}}
        # Synthetic usage is intentionally absent: not measured, never reported as 0 real tokens.
        if self.scenario == "invalid_choice": answer["choice"] = "C99"
        if self.scenario == "wrong_model": payload["model"] = "jev-latest"
        if self.scenario == "wrong_probabilities": answer["probabilities"] = {"C99": 1.}
        return outcome("OK", canonical(payload).encode("utf-8"), http_status=200)
