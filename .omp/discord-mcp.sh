#!/bin/sh
# Discord MCP (SaseQ/discord-mcp) over stdio, scoped to this directory tree.
# Registered as `discord` in ~/.omp/agent/mcp.json. omp spawns stdio servers in
# its working directory, so this refuses to start outside the tree.
#
# Token:    security add-generic-password -U -s discord-mcp -a "$USER" -w
# Guild ID: optional default server; set GUILD_ID below or export DISCORD_GUILD_ID.
set -eu

GUILD_ID="${DISCORD_GUILD_ID:-1564671275316543508}" # SideQuest
IMAGE="saseq/discord-mcp:latest"

ROOT=$(cd "$(dirname "$0")/.." && pwd -P)
case "$(pwd -P)/" in
	"$ROOT"/*) ;;
	*)
		echo "discord-mcp: only enabled under $ROOT" >&2
		exit 1
		;;
esac

if ! DISCORD_TOKEN=$(security find-generic-password -s discord-mcp -w 2>/dev/null); then
	echo "discord-mcp: no bot token in Keychain; run: security add-generic-password -U -s discord-mcp -a \"\$USER\" -w" >&2
	exit 1
fi
export DISCORD_TOKEN

if [ -n "$GUILD_ID" ]; then
	export DISCORD_GUILD_ID="$GUILD_ID"
	exec docker run --rm -i -e DISCORD_TOKEN -e DISCORD_GUILD_ID "$IMAGE"
fi
exec docker run --rm -i -e DISCORD_TOKEN "$IMAGE"
