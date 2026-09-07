"""WU-M2/M3 package 계층과 금지 의존성을 정적 import 수준에서 고정한다."""

from __future__ import annotations

import ast
from pathlib import Path

from mafia_game.api.bootstrap_auth import BootstrapAuthMiddleware
from mafia_game.api.resources.handlers import register_resource_handlers
from mafia_game.api.streamable_session_pool import StreamableSessionPool
from mafia_game.core.config import RuntimeSettings
from mafia_game.domain.session import SessionRegistry
from mafia_game.schemas.bootstrap import BootstrapTokenVerifier
from mafia_game.schemas.context import validate_context
from mafia_game.services.bootstrap import BootstrapService
from mafia_game.services.resources import ResourceService

PACKAGE_ROOT = Path(__file__).parents[1] / "mafia_game"


def test_canonical_layers_are_importable_and_flat_modules_are_removed() -> None:
    """composition root 외 구현이 확정된 api·service·domain·schema·core에 위치한다."""

    assert BootstrapAuthMiddleware
    assert StreamableSessionPool
    assert RuntimeSettings
    assert SessionRegistry
    assert BootstrapTokenVerifier
    assert BootstrapService
    assert ResourceService
    assert validate_context
    assert register_resource_handlers
    assert not (PACKAGE_ROOT / "bootstrap.py").exists()
    assert not (PACKAGE_ROOT / "session.py").exists()
    assert not (PACKAGE_ROOT / "middleware.py").exists()


def test_domain_has_no_mcp_or_http_import_and_runtime_uses_no_sdk_private_attribute() -> None:
    """순수 domain과 SDK 공개 lifecycle 경계를 AST로 확인한다."""

    for domain_file in (PACKAGE_ROOT / "domain").glob("*.py"):
        domain_tree = ast.parse(domain_file.read_text())
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
        assert imported_roots.isdisjoint({"mcp", "httpx", "starlette"}), domain_file

    runtime_files = [
        path
        for path in PACKAGE_ROOT.rglob("*.py")
        if path.parts[-2] != "tests"
    ]
    for path in runtime_files:
        tree = ast.parse(path.read_text())
        private_sdk_imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    parts = alias.name.split(".")
                    if parts[0] == "mcp" and any(part.startswith("_") for part in parts[1:]):
                        private_sdk_imports.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                parts = node.module.split(".")
                if parts[0] == "mcp" and (
                    any(part.startswith("_") for part in parts[1:])
                    or any(alias.name.startswith("_") for alias in node.names)
                ):
                    private_sdk_imports.add(node.module)
        assert private_sdk_imports == set(), path

        private_attributes = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and node.attr in {"_server_instances", "_session_owners", "_task_group"}
        }
        assert private_attributes == set(), path


def test_session_pool_uses_only_public_manager_lifecycle_api() -> None:
    """세션별 pool이 SDK transport·private map 없이 constructor·run·request만 사용한다."""

    pool_path = PACKAGE_ROOT / "api" / "streamable_session_pool.py"
    source = pool_path.read_text()
    tree = ast.parse(source)
    assert "StreamableHTTPServerTransport" not in source
    assert "_server_instances" not in source
    assert "_session_owners" not in source

    manager_methods = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "manager"
    }
    assert manager_methods == {"run", "handle_request"}

    manager_constructors = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "StreamableHTTPSessionManager"
    ]
    assert len(manager_constructors) == 1
    keywords = {
        keyword.arg: ast.literal_eval(keyword.value)
        for keyword in manager_constructors[0].keywords
    }
    assert keywords == {
        "event_store": None,
        "json_response": True,
        "stateless": False,
        "session_idle_timeout": None,
    }


def test_resource_uses_only_public_sdk_handlers_and_no_direct_data_clients() -> None:
    """Resource 표면과 MCP runtime의 DB·Redis 비접근 경계를 AST로 고정한다."""

    handler_tree = ast.parse(
        (PACKAGE_ROOT / "api" / "resources" / "handlers.py").read_text()
    )
    sdk_attributes = {
        node.attr
        for node in ast.walk(handler_tree)
        if isinstance(node, ast.Attribute)
        and node.attr
        in {
            "list_resources",
            "read_resource",
            "request_context",
            "list_resource_templates",
            "subscribe_resource",
            "unsubscribe_resource",
        }
    }
    assert sdk_attributes == {"list_resources", "read_resource", "request_context"}

    forbidden_roots = {"asyncpg", "psycopg", "psycopg2", "redis", "sqlalchemy"}
    forbidden_imports: set[str] = set()
    for path in PACKAGE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                forbidden_imports.update(
                    alias.name.split(".", 1)[0]
                    for alias in node.names
                    if alias.name.split(".", 1)[0] in forbidden_roots
                )
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".", 1)[0]
                if root in forbidden_roots:
                    forbidden_imports.add(root)
    assert forbidden_imports == set()
