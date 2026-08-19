"""Model-in-the-loop synthetic prospect regression runner.

Runs the adversarial prospect script against M4 over Gemini generateContent, using
M4's current prospect system instructions. This exercises behavior without requiring
a human, browser, microphone, or realtime audio. The deterministic harness then
scores the generated transcript.

Set M4_SYNTHETIC_MODEL to override the text model used for regression. Realtime audio
transport remains covered separately by event/generation architecture tests.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

import m4_gemini_lab
import m4_prospect_behavior
import m4_synthetic_harness as harness

API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"
SYNTHETIC_MODEL = os.getenv("M4_SYNTHETIC_MODEL", "gemini-2.5-flash")
TIMEOUT = float(os.getenv("M4_SYNTHETIC_TIMEOUT", "45"))


def _extract_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates") or []
    if not candidates:
        return ""
    parts = (((candidates[0] or {}).get("content") or {}).get("parts") or [])
    return "".join(str(p.get("text") or "") for p in parts if isinstance(p, dict)).strip()


def _generate(history: list[dict[str, Any]], system_instruction: str, model: str = SYNTHETIC_MODEL) -> str:
    key = m4_gemini_lab.GEMINI_API_KEY
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    url = f"{API_ROOT}/{model}:generateContent"
    body = {
        "systemInstruction": {"parts": [{"text": system_instruction}]},
        "contents": history,
        "generationConfig": {
            "maxOutputTokens": 700,
        },
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "x-goog-api-key": key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Gemini synthetic regression failed: HTTP {exc.code} {detail[:1000]}") from exc
    text = _extract_text(payload)
    if not text:
        raise RuntimeError("Gemini synthetic regression returned no text")
    return text


def run_script(script: list[str] | None = None, model: str = SYNTHETIC_MODEL) -> dict[str, Any]:
    script = list(script or harness.ADVERSARIAL_PROSPECT_SCRIPT)
    instructions = m4_prospect_behavior.prospect_instructions()
    history: list[dict[str, Any]] = []
    transcript: list[dict[str, Any]] = []

    for prospect_text in script:
        transcript.append({"speaker": "prospect", "text": prospect_text})
        history.append({"role": "user", "parts": [{"text": prospect_text}]})
        m4_text = _generate(history, instructions, model=model)
        transcript.append({"speaker": "m4", "text": m4_text})
        history.append({"role": "model", "parts": [{"text": m4_text}]})

    evaluation = harness.evaluate(transcript)
    return {
        "model": model,
        "script": script,
        "transcript": transcript,
        "evaluation": evaluation.as_dict(),
    }


def main() -> int:
    result = run_script()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["evaluation"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
