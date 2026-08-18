# Agent instructions

This repository is zeit, a Python 3.14 library for a bi-temporal knowledge graph.
Read `SPEC.md` before changing behavior.

## Markdown

Follow V14 in `SPEC.md`.
Write Markdown prose with one sentence per line.
Do not split a sentence across two or more lines.
Headings, tables, and fenced code blocks are exempt.

## Logfire after e2e

The e2e harness configures Logfire at process start with service name `zeit-e2e`.
`pytest -m e2e` asserts the graph only.
Do not query Logfire over HTTP from pytest.

After `pytest -m e2e`, use the Logfire MCP server:

1. Call `query_schema_reference` to load the current SQL schema.
2. Call `query_run` for PydanticAI spans in the e2e window, filtered by service name `zeit-e2e`.

Example `query_run` SQL:

```sql
SELECT start_timestamp, span_name, message, otel_scope_name
FROM records
WHERE service_name = 'zeit-e2e'
  AND (
    otel_scope_name LIKE 'pydantic%'
    OR span_name LIKE '%agent%'
    OR span_name LIKE '%embed%'
  )
ORDER BY start_timestamp DESC
LIMIT 100
```

Set `LOGFIRE_TOKEN` in the process environment before pytest.
The harness does not pass a token into `Graph`.
