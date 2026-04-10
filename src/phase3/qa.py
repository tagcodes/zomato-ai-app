from __future__ import annotations

"""
Phase 3 — LLM integration smoke tests (Groq).

This module provides a minimal Groq client wrapper and a small set of smoke tests
to confirm that:
- The API key is loaded from .env / environment variables.
- We can call the Groq chat completions endpoint and get a response.
- We can request structured JSON and parse it.

Run (from repo root):
    python src/phase3/qa.py

Notes:
- This file never prints the API key; it only prints whether it is present.
- Keep tests to 3 calls max by default to control cost.
"""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import time
from typing import Any, Dict, List, Optional

try:
    from dotenv import load_dotenv
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Missing dependency: python-dotenv. Install with: pip install python-dotenv") from exc

try:
    from groq import Groq
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Missing dependency: groq. Install with: pip install groq") from exc


DEFAULT_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")


@dataclass
class SmokeTestResult:
    name: str
    passed: bool
    details: str
    duration_ms: int


def _now_ms() -> int:
    return int(time.time() * 1000)


def load_env() -> None:
    """
    Load environment variables from .env if present.
    """
    project_root = Path(__file__).resolve().parents[2]
    dotenv_path = project_root / ".env"
    load_dotenv(dotenv_path=dotenv_path, override=False)


def get_groq_client() -> Groq:
    """
    Create a Groq client using GROQ_API_KEY from the environment.
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY is not set. Add it to .env in the repo root or export it in your shell."
        )
    return Groq(api_key=api_key)


def groq_chat(
    client: Groq,
    *,
    messages: List[Dict[str, str]],
    model: str = DEFAULT_MODEL,
    temperature: float = 0.2,
    max_tokens: int = 256,
) -> str:
    """
    Call Groq chat completions and return the assistant text.
    """
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return (resp.choices[0].message.content or "").strip()


def _test_env_key_present() -> SmokeTestResult:
    start = _now_ms()
    project_root = Path(__file__).resolve().parents[2]
    dotenv_path = project_root / ".env"
    dotenv_size = dotenv_path.stat().st_size if dotenv_path.exists() else -1

    ok = bool(os.getenv("GROQ_API_KEY"))
    end = _now_ms()
    return SmokeTestResult(
        name="env_has_groq_api_key",
        passed=ok,
        details=(
            "GROQ_API_KEY is set (value not printed)."
            if ok
            else f"GROQ_API_KEY is missing. .env exists={dotenv_path.exists()} size_bytes={dotenv_size} path={dotenv_path}"
        ),
        duration_ms=end - start,
    )


def _test_basic_completion(client: Groq, model: str) -> SmokeTestResult:
    start = _now_ms()
    try:
        text = groq_chat(
            client,
            model=model,
            messages=[
                {"role": "system", "content": "You are a concise assistant."},
                {"role": "user", "content": "Reply with exactly: OK"},
            ],
            temperature=0.0,
            max_tokens=16,
        )
        passed = text.strip() == "OK"
        details = f"Model returned: {text!r}"
    except Exception as e:  # noqa: BLE001 - smoke test should surface any failure
        passed = False
        details = f"Exception: {type(e).__name__}: {e}"
    end = _now_ms()
    return SmokeTestResult(name="basic_completion", passed=passed, details=details, duration_ms=end - start)


def _test_json_output(client: Groq, model: str) -> SmokeTestResult:
    start = _now_ms()
    try:
        text = groq_chat(
            client,
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "Return JSON only. No markdown, no extra text.",
                },
                {
                    "role": "user",
                    "content": 'Return {"ping": "pong"}',
                },
            ],
            temperature=0.0,
            max_tokens=32,
        )
        parsed: Dict[str, Any] = json.loads(text)
        passed = parsed.get("ping") == "pong"
        details = f"Parsed JSON OK: {parsed}"
    except Exception as e:  # noqa: BLE001
        passed = False
        details = f"Exception: {type(e).__name__}: {e}"
    end = _now_ms()
    return SmokeTestResult(name="json_output_parse", passed=passed, details=details, duration_ms=end - start)


def _test_small_reasoning(client: Groq, model: str) -> SmokeTestResult:
    start = _now_ms()
    try:
        text = groq_chat(
            client,
            model=model,
            messages=[
                {"role": "system", "content": "Answer in one short sentence."},
                {"role": "user", "content": "What is 2 + 2?"},
            ],
            temperature=0.0,
            max_tokens=16,
        )
        passed = "4" in text
        details = f"Model returned: {text!r}"
    except Exception as e:  # noqa: BLE001
        passed = False
        details = f"Exception: {type(e).__name__}: {e}"
    end = _now_ms()
    return SmokeTestResult(name="small_reasoning", passed=passed, details=details, duration_ms=end - start)


def run_smoke_tests(model: Optional[str] = None) -> List[SmokeTestResult]:
    """
    Run at most 4 smoke tests; only 3 of them call the LLM.
    """
    load_env()
    chosen_model = model or DEFAULT_MODEL

    results: List[SmokeTestResult] = []
    results.append(_test_env_key_present())

    client = None
    try:
        client = get_groq_client()
    except Exception as e:  # noqa: BLE001
        results.append(
            SmokeTestResult(
                name="create_client",
                passed=False,
                details=f"Exception: {type(e).__name__}: {e}",
                duration_ms=0,
            )
        )
        return results

    results.append(_test_basic_completion(client, chosen_model))
    results.append(_test_json_output(client, chosen_model))
    results.append(_test_small_reasoning(client, chosen_model))
    return results


def main() -> None:
    results = run_smoke_tests()
    passed = sum(1 for r in results if r.passed)
    print(f"Groq smoke tests: {passed}/{len(results)} passed. Model={DEFAULT_MODEL!r}")
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        print(f"- {status} {r.name} ({r.duration_ms}ms): {r.details}")


if __name__ == "__main__":
    main()

