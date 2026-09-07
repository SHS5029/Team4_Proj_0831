"""MCP Resource URI와 subject allowlist의 순수 canonical registry다."""

RESOURCE_URIS = {
    "public": "mafia://session/public",
    "me": "mafia://session/me",
    "turn": "mafia://session/turn",
    "persona": "mafia://session/persona",
    "gm-guide": "mafia://session/gm-guide",
}
URI_TO_SCOPE = {uri: scope for scope, uri in RESOURCE_URIS.items()}
