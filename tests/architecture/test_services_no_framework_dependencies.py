"""
Enforces the rule that services never import Django models directly and
stay plain Python classes with no Django inheritance, without needing a
configured Django/DB environment: it parses each service file's source
with `ast` instead of importing it.

`django.conf` (settings access) is explicitly allowed — see project
decision: services reading operational constants via `django.conf.settings`
is not considered a framework dependency, only Django ORM / DRF usage is.
"""

import ast
import importlib
import os

import pytest

SERVICE_PACKAGES = [
    "apps.transformation.services",
    "apps.supplier_auth.services",
]

ALLOWED_DJANGO_IMPORTS = {"django.conf"}

FORBIDDEN_IMPORT_PREFIXES = (
    "django",
    "rest_framework",
)


def _service_files():
    files = []
    for package_name in SERVICE_PACKAGES:
        package = importlib.import_module(package_name)
        package_dir = os.path.dirname(package.__file__)
        for filename in sorted(os.listdir(package_dir)):
            if filename.endswith(".py") and filename != "__init__.py":
                files.append(
                    (package_name, filename, os.path.join(package_dir, filename))
                )
    return files


def _is_allowed_django_import(module_name: str) -> bool:
    return any(
        module_name == allowed or module_name.startswith(allowed + ".")
        for allowed in ALLOWED_DJANGO_IMPORTS
    )


def _is_forbidden_import(module_name: str) -> bool:
    if module_name is None:
        return False
    if not module_name.startswith(FORBIDDEN_IMPORT_PREFIXES):
        return False
    return not _is_allowed_django_import(module_name)


def _is_project_model_import(module_name: str) -> bool:
    """Flags `from apps.<app>.models import ...` — a Django ORM models module."""
    if module_name is None:
        return False
    parts = module_name.split(".")
    return len(parts) >= 3 and parts[0] == "apps" and "models" in parts


def _violations_in_source(source: str) -> list[str]:
    tree = ast.parse(source)
    violations = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_forbidden_import(alias.name):
                    violations.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module_name = node.module
            if _is_forbidden_import(module_name):
                violations.append(f"from {module_name} import ...")
            elif _is_project_model_import(module_name):
                violations.append(f"from {module_name} import ... (Django ORM model)")

    return violations


@pytest.mark.parametrize(
    "package_name,filename,path",
    _service_files(),
    ids=[f"{p}.{f}" for p, f, _ in _service_files()],
)
def test_service_file_has_no_framework_dependencies(package_name, filename, path):
    with open(path, encoding="utf-8") as fh:
        source = fh.read()

    violations = _violations_in_source(source)

    assert not violations, (
        f"{package_name}.{filename} depends on a framework/ORM import, "
        f"violating the 'services never import Django models directly' rule: {violations}"
    )
