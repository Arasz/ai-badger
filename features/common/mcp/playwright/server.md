<!-- Playwright MCP tools -->
## MCP Tools: playwright

The Playwright MCP server provides browser automation capabilities through the Model
Context Protocol, enabling LLMs to interact with web pages using structured accessibility
snapshots without requiring vision models.

Start with `browser_navigate` to load the target URL. Use `browser_snapshot` to capture the
page's accessibility tree and element reference IDs (`ref=...`). Interact with elements using
`browser_click`, `browser_type`, `browser_fill_form`, or `browser_select_option` referencing
those IDs. Capture visual evidence with `browser_take_screenshot`. Monitor API calls with
`browser_network_requests` and debug issues with `browser_console_messages`. For multi-step
or complex interactions, execute custom Playwright scripts with `browser_run_code_unsafe`.
Each tool's own description covers the rest.
