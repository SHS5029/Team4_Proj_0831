"""WU-M2 package 계층과 금지 의존성을 정적 import 수준에서 고정한다."""

from __future__ import annotations

import ast
from pathlib import Path

from mafia_game.api.bootstrap_auth import BootstrapAuthMiddleware
from mafia_game.core.config import RuntimeSettings
from mafia_game.domain.session import SessionRegistry
from mafia_game.schemas.bootstrap import BootstrapTokenVerifier
from mafia_game.services.bootstrap import BootstrapService

PACKAGE_ROOT = Path(__file__).parents[1] / "mafia_game"


def test_canonical_layers_are_importable_and_flat_modules_are_removed() -> None:
    """composition root 외 구현이 확정된 api·service·domain·schema·core에 위치한다."""

    assert BootstrapAuthMiddleware
    assert RuntimeSettings
    assert SessionRegistry
    assert BootstrapTokenVerifier
    assert BootstrapService
    assert not (PACKAGE_ROOT / "bootstrap.py").exists()
    assert not (PACKAGE_ROOT / "session.py").exists()
    assert not (PACKAGE_ROOT / "middleware.py").exists()


def test_domain_has_no_mcp_or_http_import_and_runtime_uses_no_sdk_private_attribute() -> None:
    """순수 domain과 SDK 공개 lifecycle 경계를 AST로 확인한다."""

    domain_tree = ast.parse((PACKAGE_ROOT / "domain" / "session.py").read_text())
    imported_roots = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(domain_tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_roots.update(
        node.module.split(".", 1)[0]
        for node in ast.walk(domain_tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )
    assert imported_roots.isdisjoint({"mcp", "httpx", "starlette"})

    runtime_files = [
        path
        for path in PACKAGE_ROOT.rglob("*.py")
        if path.parts[-2] != "tests"
    ]
    for path in runtime_files:
        tree = ast.parse(path.read_text())
        private_attributes = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and node.attr in {"_server_instances", "_session_owners", "_task_group"}
        }
        assert private_attributes == set(), path
