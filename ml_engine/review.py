from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def review_benchmark(result: dict) -> dict:
    """Ask an optional OpenAI-compatible LLM to critique, never alter, a result."""
    base_url = os.getenv("LLM_BASE_URL", "").strip().rstrip("/")
    api_key = os.getenv("LLM_API_KEY", "").strip()
    model = os.getenv("LLM_MODEL", "").strip()
    if not (base_url and api_key and model):
        return {"available": False, "message": "LLM review is not configured. The forecast results remain available without it."}

    summary = {
        "target_name": result.get("target_name"),
        "horizon_months": result.get("horizon_months"),
        "observations": result.get("observations"),
        "external_features_used": result.get("external_features_used"),
        "models": result.get("models"),
        "regimes": result.get("regimes"),
        "data": result.get("data"),
        "caveats": result.get("caveats"),
    }
    body = {
        "model": model,
        "temperature": 0.1,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an advisory methods reviewer for a college research demonstration. "
                    "Do not make or change forecasts. Do not claim causation. Identify at most three "
                    "specific concerns about evaluation fairness, missing evidence, source verification, or overclaiming. "
                    "If evidence is insufficient, say so. Keep the response concise."
                ),
            },
            {"role": "user", "content": json.dumps(summary, ensure_ascii=False)},
        ],
    }
    request = Request(
        f"{base_url}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8"))
        content = payload["choices"][0]["message"]["content"]
        return {"available": True, "advisory_only": True, "review": str(content)[:6000]}
    except (HTTPError, URLError, TimeoutError, KeyError, IndexError, ValueError) as exc:
        return {"available": False, "message": f"Advisory review unavailable ({type(exc).__name__}); model results were not changed."}
