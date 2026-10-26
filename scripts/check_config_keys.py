#!/usr/bin/env python3
"""PM1-A1: verifica que los manifiestos aporten las variables que main.py
exige al arrancar. Trabaja solo con NOMBRES de claves, nunca con valores."""
import ast
import re
import sys
from pathlib import Path

MAIN = Path("webhook_service/main.py")
CONFIGMAP = Path("deploy/apps/webhook/webhook-config.yaml")
SECRET_EXAMPLE = Path("deploy/apps/webhook/webhook-secret.yaml.example")


def required_from_main() -> set[str]:
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_require_env"):
            return {a.value for a in node.args if isinstance(a, ast.Constant)}
    sys.exit("ERROR: no encontre la llamada a _require_env en main.py")


def keys_in(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    return set(re.findall(r"^  ([A-Z][A-Z0-9_]*):", text, re.M))


required = required_from_main()
provided = keys_in(CONFIGMAP) | keys_in(SECRET_EXAMPLE)
missing = sorted(required - provided)

print(f"main.py exige {len(required)} variables; los manifiestos aportan {len(required & provided)}.")
if missing:
    print("FALTAN en ConfigMap/Secret.example: " + ", ".join(missing))
    sys.exit(1)
print("OK: todas las variables obligatorias estan declaradas.")
