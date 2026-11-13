#!/usr/bin/env bash
# Publish the released MCP bundle once, using GitHub Actions OIDC.
set -euo pipefail
metadata=${1:?Supply the released server.json file}
registry=${MCP_REGISTRY_URL:-https://registry.modelcontextprotocol.io}
publisher=${MCP_PUBLISHER:-mcp-publisher}

# Only a missing exact version permits publication. Lookup failures and conflicting
# immutable package metadata stop before authentication.
if python3 - "$metadata" "$registry" <<'PYTHON'
import json
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import urlopen

try:
    local = json.loads(Path(sys.argv[1]).read_text())
    name, version = local["name"], local["version"]
    url = f"{sys.argv[2].rstrip('/')}/v0.1/servers/{quote(name, safe='')}/versions/{quote(version, safe='')}"
    try:
        with urlopen(url, timeout=30) as response:
            remote = json.load(response)["server"]
    except HTTPError as exc:
        if exc.code == 404:
            sys.exit(3)
        raise
    if any(remote[key] != local[key] for key in ("name", "version", "packages")):
        raise ValueError("Published Registry version has different package metadata; increment project.version")
    print(f"{name} {version} is already published with matching package metadata.")
except (OSError, ValueError, KeyError, TypeError) as exc:
    sys.exit(str(exc))
PYTHON
then
    exit 0
else
    status=$?
    if [[ "$status" != 3 ]]; then exit "$status"; fi
fi

"$publisher" validate "$metadata"
"$publisher" login github-oidc --registry="$registry"
"$publisher" publish "$metadata"
