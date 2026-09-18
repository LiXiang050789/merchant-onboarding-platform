#!/usr/bin/env python
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "env" / "check.json"


def run(cmd: list[str], timeout: int = 20) -> dict:
    try:
        completed = subprocess.run(
            cmd,
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        return {
            "cmd": " ".join(cmd),
            "ok": completed.returncode == 0,
            "returncode": completed.returncode,
            "stdout": completed.stdout.strip()[-1200:],
            "stderr": completed.stderr.strip()[-1200:],
        }
    except Exception as exc:  # pragma: no cover - diagnostics path
        return {"cmd": " ".join(cmd), "ok": False, "error": repr(exc)}


def command_exists(name: str) -> dict:
    path = shutil.which(name)
    return {"cmd": f"which {name}", "ok": path is not None, "path": path}


def python_import(name: str) -> dict:
    code = f"import {name}; print(getattr({name}, '__version__', 'ok'))"
    return run([sys.executable, "-c", code])


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)

    checks: dict[str, dict] = {
        "python_version": run([sys.executable, "-V"]),
        "numpy_import": python_import("numpy"),
        "docker_command": command_exists("docker"),
        "docker_info": run(["docker", "info"]),
        "docker_compose": run(["docker", "compose", "version"]),
        "mysql_image": run(["docker", "image", "inspect", "mysql:8.0"]),
        "mongo_image": run(["docker", "image", "inspect", "mongo:7"]),
        "node_version": run(["node", "-v"]),
        "npm_version": run(["npm", "-v"]),
        "redis_cli": command_exists("redis-cli"),
        "redis_ping": run(["redis-cli", "ping"]),
        "gitignore_env": {
            "cmd": "read .gitignore",
            "ok": ".env" in (ROOT / ".gitignore").read_text(encoding="utf-8"),
        },
        "env_file": {
            "cmd": "test -f .env",
            "ok": (ROOT / ".env").exists(),
            "note": ".env is local and ignored by git",
        },
    }

    required = [
        "python_version",
        "numpy_import",
        "docker_command",
        "docker_info",
        "docker_compose",
        "mysql_image",
        "mongo_image",
        "node_version",
        "npm_version",
        "redis_cli",
        "redis_ping",
        "gitignore_env",
        "env_file",
    ]
    ok = all(checks[name].get("ok") for name in required)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if ok else "fail",
        "required": required,
        "checks": checks,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "evidence": str(OUT)}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
