"""Minimal NVIDIA (integrate.api.nvidia.com) chat client for EVAL / GENERATION ONLY. Reads NVIDIA_API_KEY from env and never prints it. Retries 429 / 5xx / transport errors (counted); never falls back to anything else."""
import json, os, time, httpx
BASE = "https://integrate.api.nvidia.com/v1"
import os as _os
_client = httpx.Client(timeout=httpx.Timeout(float(_os.environ.get("NV_TIMEOUT", "900")), connect=20))
STATS = {"calls": 0, "retries": 0, "prompt_tokens": 0, "completion_tokens": 0}

def chat(model, messages, retries=8, **kw):
    body = {"model": model, "messages": messages, **kw}
    last = None
    for a in range(retries + 1):
        try:
            t = time.time()
            r = _client.post(f"{BASE}/chat/completions", json=body,
                             headers={"Authorization": f"Bearer {os.environ['NVIDIA_API_KEY']}"})
            if r.status_code == 429 or r.status_code >= 500:
                last = f"HTTP {r.status_code}: {r.text[:200]}"
                STATS["retries"] += 1
                time.sleep(min(60, 5 * (a + 1) * (3 if r.status_code == 429 else 1)))
                continue
            if r.status_code != 200:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:400]}")
            d = r.json()
            STATS["calls"] += 1
            u = d.get("usage") or {}
            STATS["prompt_tokens"] += u.get("prompt_tokens", 0) or 0
            STATS["completion_tokens"] += u.get("completion_tokens", 0) or 0
            d["_latency"] = round(time.time() - t, 2)
            return d
        except (httpx.TransportError,) as e:
            last = repr(e)
            STATS["retries"] += 1
            time.sleep(5 * (a + 1))
    raise RuntimeError(f"failed after retries: {last}")

def content(d):
    return d["choices"][0]["message"].get("content") or ""
