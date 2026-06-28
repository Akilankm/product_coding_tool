"""Install/register a stable Jupyter kernel for this project."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

KERNEL_NAME = "product-coding-tool"
DISPLAY_NAME = "Product Coding Tool (PDM)"


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def write_ipython_config(root: Path) -> Path:
    profile_dir = root / ".ipython" / "profile_default"
    profile_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = profile_dir / "ipython_config.py"
    cfg_path.write_text(
        "# Generated for Product Coding Tool notebooks.\n"
        "# Jedi is intentionally disabled because kernel-side Jedi completion can become slow/hanging on large environments.\n"
        "c = get_config()\n"
        "c.Completer.use_jedi = False\n",
        encoding="utf-8",
    )
    return cfg_path


def install_kernel(root: Path) -> Path:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "ipykernel",
            "install",
            "--user",
            "--name",
            KERNEL_NAME,
            "--display-name",
            DISPLAY_NAME,
        ],
        check=True,
    )
    try:
        from jupyter_client.kernelspec import KernelSpecManager
    except Exception as exc:  # pragma: no cover - dependency guard
        raise RuntimeError("jupyter-client is required to register the notebook kernel.") from exc

    spec = KernelSpecManager().get_kernel_spec(KERNEL_NAME)
    kernel_json_path = Path(spec.resource_dir) / "kernel.json"
    payload = json.loads(kernel_json_path.read_text(encoding="utf-8"))
    env = dict(payload.get("env") or {})
    env["PYTHONPATH"] = str(root / "src") + os.pathsep + env.get("PYTHONPATH", "")
    env["IPYTHONDIR"] = str(root / ".ipython")
    env["PCT_IPYTHON_DISABLE_JEDI"] = "true"
    payload["env"] = env
    kernel_json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return kernel_json_path


def main() -> None:
    root = project_root()
    cfg_path = write_ipython_config(root)
    kernel_json_path = install_kernel(root)
    print(f"Wrote IPython config: {cfg_path}")
    print(f"Installed Jupyter kernel: {kernel_json_path}")
    print(f"Kernel display name: {DISPLAY_NAME}")


if __name__ == "__main__":
    main()
