"""JSON-lines worker executed only inside a restricted plugin subprocess."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
from contextlib import redirect_stdout
from dataclasses import asdict


def main() -> None:
    request = json.loads(sys.stdin.read())
    path = os.environ["LIFETREE_PLUGIN_PATH"]
    spec = importlib.util.spec_from_file_location("lifetree_isolated_plugin", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("plugin loader unavailable")
    module = importlib.util.module_from_spec(spec)
    captured = io.StringIO()
    with redirect_stdout(captured):
        spec.loader.exec_module(module)
        plugin = getattr(module, "Plugin", None)
        if plugin is None:
            raise RuntimeError("Plugin class missing")
        manifest = plugin.manifest()
        response = {"manifest": asdict(manifest), "warning": None}
        if request.get("action") == "run":
            raw = plugin.fetch(request.get("params") or {})
            raw_text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
            if hasattr(plugin, "transform"):
                try:
                    transformed = plugin.transform(raw_text, None)
                    if isinstance(transformed, str) and transformed.strip():
                        raw_text = transformed
                except Exception as exc:  # noqa: BLE001
                    response["warning"] = f"transform failed in isolated process: {exc}"
            response["text"] = raw_text
    sys.stdout.write(json.dumps(response, ensure_ascii=False))


if __name__ == "__main__":
    main()
