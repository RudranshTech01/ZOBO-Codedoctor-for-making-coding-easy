import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from nemoguardrails import LLMRails, RailsConfig
from nemoguardrails.rails.llm.options import RailStatus
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")
GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
GUARDRAILS_CONFIG_DIR = BASE_DIR / "backend" / "guardrails"

app = FastAPI(title="CodeDoctor AI", version="2.0.0")


class AnalyzeRequest(BaseModel):
    language: str = Field(default="C++", max_length=40)
    code: str = Field(min_length=1, max_length=30000)
    error: str = Field(default="", max_length=10000)


SYSTEM_PROMPT = """You are CodeDoctor AI, an accurate, beginner-friendly coding assistant.
Analyze the entire submitted source code and any compiler/runtime error. Find all distinct clear compile-time, runtime, type, and logic bugs; do not stop after finding the first one. Check that variable names exist, statement syntax is complete, and values have appropriate types for the operations that use them. In dynamically typed languages, check for invalid coercions and results such as NaN (for example, multiplying a numeric string like \"ten\").

Return exactly one valid JSON object with these keys:
{"error_type":"string","error":"short explanation of the issues","why":"why each issue happens","fixed_code":"complete corrected source code","better_approach":"concise suggestion or No major improvement needed.","tips":["tip 1","tip 2"]}

Before answering, review the fixed_code against every issue you identified and make sure the fix removes them while preserving intended behavior. Do not invent errors. If no error is supplied, inspect the code for clear issues; if it appears correct, say so and avoid unnecessary changes. Keep explanations concise. fixed_code must be source code only, without Markdown fences. Return no text outside the JSON object."""

REQUIRED_KEYS = {
    "error_type",
    "error",
    "why",
    "fixed_code",
    "better_approach",
    "tips",
}


def extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)

    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("AI returned empty text or no JSON object")
        result = json.loads(text[start : end + 1])

    if not isinstance(result, dict) or not REQUIRED_KEYS.issubset(result):
        raise ValueError("AI response is missing one or more required fields")
    if not isinstance(result["tips"], list):
        raise ValueError("AI response field 'tips' must be a list")
    return result


@lru_cache(maxsize=1)
def get_guardrails_app() -> LLMRails:
    if not GROQ_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="GROQ_API_KEY is missing. Add it to the project-root .env file and restart the server.",
        )

    required_files = ["config.yml", "rails.co", "actions.py"]
    missing_files = [
        name for name in required_files
        if not (GUARDRAILS_CONFIG_DIR / name).is_file()
    ]
    if missing_files:
        missing = ", ".join(missing_files)
        raise HTTPException(
            status_code=500,
            detail=(
                f"NeMo Guardrails files missing in {GUARDRAILS_CONFIG_DIR}: {missing}. "
                "Place config.yml, rails.co, and actions.py together in backend/guardrails."
            ),
        )

    try:
        config = RailsConfig.from_path(str(GUARDRAILS_CONFIG_DIR))
        return LLMRails(config)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Could not load NVIDIA NeMo Guardrails config: {type(exc).__name__}: {exc}",
        ) from exc


@app.get("/")
async def home():
    return FileResponse(BASE_DIR / "frontend" / "index.html")


@app.get("/health")
async def health():
    required_files = ["config.yml", "rails.co", "actions.py"]
    missing_files = [
        name for name in required_files
        if not (GUARDRAILS_CONFIG_DIR / name).is_file()
    ]
    return {
        "status": "ok",
        "provider": "Groq",
        "provider_configured": bool(GROQ_API_KEY),
        "model": GROQ_MODEL,
        "nvidia_tool": "NeMo Guardrails",
        "guardrails_configured": not missing_files,
        "guardrails_missing_files": missing_files,
    }


@app.post("/api/analyze")
async def analyze(request: AnalyzeRequest):
    if not GROQ_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="GROQ_API_KEY is missing. Add it to the project-root .env file and restart the server.",
        )

    user_prompt = (
        f"Language: {request.language}\n\n"
        f"SOURCE CODE:\n{request.code}\n\n"
        f"COMPILER / RUNTIME ERROR (may be empty):\n{request.error or '(none supplied)'}"
    )

    try:
        # Run the custom NVIDIA NeMo input rail before sending code to Groq.
        guardrails = get_guardrails_app()
        guard_result = await guardrails.check_async(
            [{"role": "user", "content": user_prompt}]
        )
        if guard_result.status == RailStatus.BLOCKED:
            raise HTTPException(
                status_code=400,
                detail="Input was blocked by the NVIDIA NeMo Guardrails input check.",
            )

        payload = {
            "model": GROQ_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            # Allow enough room for the full fixed source and structured explanation.
            "max_completion_tokens": 8192,
            "reasoning_effort": "none",
            "reasoning_format": "hidden",
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "code_analysis",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "error_type": {"type": "string"},
                            "error": {"type": "string"},
                            "why": {"type": "string"},
                            "fixed_code": {"type": "string"},
                            "better_approach": {"type": "string"},
                            "tips": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": [
                            "error_type",
                            "error",
                            "why",
                            "fixed_code",
                            "better_approach",
                            "tips",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
        }
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        timeout = httpx.Timeout(60.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(GROQ_CHAT_URL, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        content = data["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Groq returned empty response content")
        return extract_json(content)

    except HTTPException:
        raise
    except httpx.HTTPStatusError as exc:
        provider_text = exc.response.text[:700].strip()
        raise HTTPException(
            status_code=502,
            detail=f"Groq returned HTTP {exc.response.status_code}: {provider_text or '(empty response)'}",
        ) from exc
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=504,
            detail=f"Groq request timed out ({type(exc).__name__}). Try again shortly.",
        ) from exc
    except httpx.RequestError as exc:
        print(f"Groq connection error: {type(exc).__name__}: {exc!r}")
        raise HTTPException(
            status_code=502,
            detail=f"Could not connect to Groq ({type(exc).__name__}). Check internet or proxy settings.",
        ) from exc
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"AI response was not in the expected JSON format: {exc}",
        ) from exc
    except Exception as exc:
        print(f"CodeDoctor request failed: {type(exc).__name__}: {exc}")
        raise HTTPException(
            status_code=502,
            detail=f"Code analysis failed ({type(exc).__name__}). Check the backend terminal for details.",
        ) from exc
