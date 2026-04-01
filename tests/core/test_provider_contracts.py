import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NUMBERS_MANAGER = ROOT / "services" / "numbers" / "manager.py"
PROXIES_MANAGER = ROOT / "services" / "proxies" / "manager.py"


def _read_ast(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _dict_keys(tree: ast.Module, var_name: str) -> set[str]:
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = [t for t in node.targets if isinstance(t, ast.Name)]
            if any(t.id == var_name for t in targets) and isinstance(node.value, ast.Dict):
                return {
                    key.value
                    for key in node.value.keys
                    if isinstance(key, ast.Constant) and isinstance(key.value, str)
                }
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == var_name and isinstance(node.value, ast.Dict):
            return {
                key.value
                for key in node.value.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }
    raise AssertionError(f"{var_name} not found")


def _tuple_values(tree: ast.Module, var_name: str) -> set[str]:
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = [t for t in node.targets if isinstance(t, ast.Name)]
            if any(t.id == var_name for t in targets) and isinstance(node.value, (ast.Tuple, ast.List)):
                return {
                    elt.value
                    for elt in node.value.elts
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                }
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == var_name and isinstance(node.value, (ast.Tuple, ast.List)):
            return {
                elt.value
                for elt in node.value.elts
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
            }
    raise AssertionError(f"{var_name} not found")


def test_numbers_provider_capabilities_cover_registry() -> None:
    tree = _read_ast(NUMBERS_MANAGER)
    providers = _dict_keys(tree, "PROVIDERS")
    capabilities = _dict_keys(tree, "PROVIDER_CAPABILITIES")
    assert providers.issubset(capabilities)


def test_numbers_rental_registry_uses_known_providers() -> None:
    tree = _read_ast(NUMBERS_MANAGER)
    providers = _dict_keys(tree, "PROVIDERS")
    rentals = _tuple_values(tree, "RENTAL_PROVIDER_CODES")
    assert rentals.issubset(providers)


def test_proxy_provider_registry_can_be_empty_when_disabled() -> None:
    tree = _read_ast(PROXIES_MANAGER)
    providers = _dict_keys(tree, "PROXY_PROVIDERS")
    assert isinstance(providers, set)
