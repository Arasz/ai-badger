<!-- Hermes MCP tools -->
## MCP Tools: hermes

Hermes Agent exposes a stdio MCP bridge for connected messaging platforms. Use it when another
agent needs to list conversations, read history, poll live events, send text messages, browse
channels, or manage approval requests through Hermes.

The server is started by the client with `hermes mcp serve`. Read operations use Hermes's session
store without a running gateway; sending messages requires the gateway and its platform adapters.

The common declaration is conditional: ai-badger emits it only when `hermes` resolves on PATH.
