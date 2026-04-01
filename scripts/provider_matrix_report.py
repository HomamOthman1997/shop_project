#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NUMBERS_MANAGER = ROOT / "services" / "numbers" / "manager.py"
PROXIES_MANAGER = ROOT / "services" / "proxies" / "manager.py"
OUTPUT_PATH = ROOT / "docs" / "providers" / "runtime_provider_matrix.md"


def _load_module_ast(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _literal_dict_keys(tree: ast.Module, name: str) -> list[str]:
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name and isinstance(node.value, ast.Dict):
                    keys: list[str] = []
                    for key_node in node.value.keys:
                        if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
                            keys.append(key_node.value)
                    return keys
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name and isinstance(node.value, ast.Dict):
            keys: list[str] = []
            for key_node in node.value.keys:
                if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
                    keys.append(key_node.value)
            return keys
    raise ValueError(f"Could not parse dict keys for {name}")


def _literal_tuple_values(tree: ast.Module, name: str) -> list[str]:
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name and isinstance(node.value, (ast.Tuple, ast.List)):
                    values: list[str] = []
                    for elt in node.value.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            values.append(elt.value)
                    return values
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name and isinstance(node.value, (ast.Tuple, ast.List)):
            values: list[str] = []
            for elt in node.value.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    values.append(elt.value)
            return values
    raise ValueError(f"Could not parse tuple/list values for {name}")


def _provider_capabilities(tree: ast.Module) -> dict[str, dict[str, bool]]:
    out: dict[str, dict[str, bool]] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "PROVIDER_CAPABILITIES" and isinstance(node.value, ast.Dict):
                    for key_node, value_node in zip(node.value.keys, node.value.values):
                        if not (isinstance(key_node, ast.Constant) and isinstance(key_node.value, str)):
                            continue
                        provider = key_node.value
                        caps: dict[str, bool] = {}
                        if isinstance(value_node, ast.Dict):
                            for cap_key_node, cap_val_node in zip(value_node.keys, value_node.values):
                                if isinstance(cap_key_node, ast.Constant) and isinstance(cap_key_node.value, str):
                                    caps[cap_key_node.value] = bool(
                                        isinstance(cap_val_node, ast.Constant) and bool(cap_val_node.value)
                                    )
                        out[provider] = caps
                    return out
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "PROVIDER_CAPABILITIES" and isinstance(node.value, ast.Dict):
            for key_node, value_node in zip(node.value.keys, node.value.values):
                if not (isinstance(key_node, ast.Constant) and isinstance(key_node.value, str)):
                    continue
                provider = key_node.value
                caps: dict[str, bool] = {}
                if isinstance(value_node, ast.Dict):
                    for cap_key_node, cap_val_node in zip(value_node.keys, value_node.values):
                        if isinstance(cap_key_node, ast.Constant) and isinstance(cap_key_node.value, str):
                            caps[cap_key_node.value] = bool(isinstance(cap_val_node, ast.Constant) and bool(cap_val_node.value))
                out[provider] = caps
            return out
    raise ValueError("Could not parse PROVIDER_CAPABILITIES")


def render_markdown() -> str:
    numbers_tree = _load_module_ast(NUMBERS_MANAGER)
    proxies_tree = _load_module_ast(PROXIES_MANAGER)

    numbers_providers = sorted(_literal_dict_keys(numbers_tree, "PROVIDERS"))
    rental_providers = set(_literal_tuple_values(numbers_tree, "RENTAL_PROVIDER_CODES"))
    capabilities = _provider_capabilities(numbers_tree)
    proxy_providers = sorted(_literal_dict_keys(proxies_tree, "PROXY_PROVIDERS"))

    lines: list[str] = [
        "# Runtime Provider Matrix",
        "",
        "This file is generated from source code and is intended to prevent docs/runtime drift.",
        "",
        "## Numbers providers",
        "",
        "| Provider | Temp | Rental | Unlimited rental | State temp | State rental | In RENTAL_PROVIDER_CODES |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]

    for code in numbers_providers:
        caps = capabilities.get(code, {})
        lines.append(
            "| "
            + code
            + " | "
            + ("✅" if caps.get("supports_temp") else "❌")
            + " | "
            + ("✅" if caps.get("supports_rental") else "❌")
            + " | "
            + ("✅" if caps.get("supports_unlimited_rental") else "❌")
            + " | "
            + ("✅" if caps.get("supports_state_temp") else "❌")
            + " | "
            + ("✅" if caps.get("supports_state_rental") else "❌")
            + " | "
            + ("✅" if code in rental_providers else "❌")
            + " |"
        )

    lines.extend([
        "",
        "## Proxy providers",
        "",
        "| Provider | Active in runtime registry |",
        "|---|---:|",
    ])
    for code in proxy_providers:
        lines.append(f"| {code} | ✅ |")

    lines.extend([
        "",
        "## Source files",
        "",
        "- `services/numbers/manager.py`",
        "- `services/proxies/manager.py`",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate/check provider matrix report from runtime source files.")
    parser.add_argument("--check", action="store_true", help="Fail if output file is not up to date.")
    parser.add_argument("--output", default=str(OUTPUT_PATH), help="Output path for generated markdown.")
    args = parser.parse_args()

    output = Path(args.output)
    content = render_markdown()

    if args.check:
        existing = output.read_text(encoding="utf-8") if output.exists() else ""
        if existing != content:
            print(f"Provider matrix is out of date: {output}")
            return 1
        print(f"Provider matrix is up to date: {output}")
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")
    print(f"Wrote provider matrix: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
