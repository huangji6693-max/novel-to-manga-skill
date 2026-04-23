"""Shared helpers across pipeline stages."""
from __future__ import annotations
import json
import os
import hashlib
import time
import uuid
import urllib.request
import urllib.parse
from pathlib import Path

ROOT = Path(os.environ.get("MANGA_ROOT", "/root/manga"))
COMFY = os.environ.get("COMFY_URL", "http://127.0.0.1:8188")
CLIENT_ID = str(uuid.uuid4())


def panel_seed(panel_id: str) -> int:
    """Deterministic seed from panel_id so retries stay consistent."""
    h = hashlib.sha256(panel_id.encode()).hexdigest()
    return int(h[:8], 16) % (2**31 - 1)


def http_post(path: str, data: dict) -> dict:
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        f"{COMFY}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def http_get(path: str) -> dict:
    with urllib.request.urlopen(f"{COMFY}{path}") as r:
        return json.loads(r.read())


def queue_workflow(workflow: dict, timeout: int = 600) -> list[str]:
    """Submit workflow to ComfyUI, block until complete, return saved filenames."""
    payload = {"prompt": workflow, "client_id": CLIENT_ID}
    resp = http_post("/prompt", payload)
    prompt_id = resp["prompt_id"]

    start = time.time()
    while time.time() - start < timeout:
        hist = http_get(f"/history/{prompt_id}")
        if prompt_id in hist:
            outputs = hist[prompt_id].get("outputs", {})
            files = []
            for node_id, out in outputs.items():
                for img in out.get("images", []):
                    files.append(img["filename"])
            return files
        time.sleep(1.5)
    raise TimeoutError(f"Workflow {prompt_id} timed out after {timeout}s")


def load_workflow(name: str) -> dict:
    """Load a workflow JSON template from workflows/."""
    path = ROOT / "workflows" / name
    if not path.exists():
        path = Path(__file__).parent.parent / "workflows" / name
    with open(path) as f:
        return json.load(f)


def ensure_dirs() -> None:
    for sub in ("script_json", "refs", "output/panels_raw",
                "output/panels_passed", "output/pages"):
        (ROOT / sub).mkdir(parents=True, exist_ok=True)
