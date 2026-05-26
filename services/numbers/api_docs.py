from __future__ import annotations

import html
import json
from typing import Any

from services.numbers.api_schema import numbers_openapi_schema


def _esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def _method_badge(method: str) -> str:
    label = str(method or "GET").upper()
    return f'<span class="method method-{_esc(label.lower())}">{_esc(label)}</span>'


def _scope_label(operation: dict[str, Any]) -> str:
    scope = str(operation.get("x-required-scope") or "public").strip() or "public"
    return scope


def _parameters_label(operation: dict[str, Any]) -> str:
    params = operation.get("parameters")
    if not isinstance(params, list) or not params:
        return "None"
    labels: list[str] = []
    for param in params:
        if not isinstance(param, dict):
            continue
        name = str(param.get("name") or "").strip()
        location = str(param.get("in") or "").strip()
        required = "required" if param.get("required") else "optional"
        if name:
            labels.append(f"{name} ({location}, {required})")
    return ", ".join(labels) or "None"


def _action_rows(actions: dict[str, Any]) -> str:
    rows: list[str] = []
    for key, action in sorted((actions or {}).items()):
        if not isinstance(action, dict):
            continue
        enabled = bool(action.get("enabled", True))
        rows.append(
            "<tr>"
            f"<td><code>{_esc(key)}</code></td>"
            f"<td>{_method_badge(str(action.get('method') or 'GET'))}</td>"
            f"<td><code>{_esc(action.get('endpoint'))}</code></td>"
            f"<td><code>{_esc(action.get('scope') or 'public')}</code></td>"
            f"<td>{'yes' if action.get('requires_idempotency_key') else 'no'}</td>"
            f"<td class=\"{'ok' if enabled else 'muted'}\">{_esc('enabled' if enabled else action.get('reason') or 'disabled')}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def _endpoint_rows(paths: dict[str, Any]) -> str:
    rows: list[str] = []
    for path, methods in sorted((paths or {}).items()):
        if not isinstance(methods, dict):
            continue
        for method, operation in sorted(methods.items()):
            if not isinstance(operation, dict):
                continue
            rows.append(
                "<tr>"
                f"<td>{_method_badge(method)}</td>"
                f"<td><code>{_esc(path)}</code></td>"
                f"<td>{_esc(operation.get('summary'))}</td>"
                f"<td><code>{_esc(_scope_label(operation))}</code></td>"
                f"<td>{_esc(_parameters_label(operation))}</td>"
                "</tr>"
            )
    return "\n".join(rows)


def _capability_items(capabilities: dict[str, Any]) -> str:
    items: list[str] = []
    for key, value in sorted((capabilities or {}).items()):
        if isinstance(value, (dict, list, tuple)):
            rendered = json.dumps(value, ensure_ascii=True)
        else:
            rendered = str(value).lower() if isinstance(value, bool) else str(value)
        items.append(f"<li><span>{_esc(key)}</span><strong>{_esc(rendered)}</strong></li>")
    return "\n".join(items)


def render_numbers_api_docs(schema: dict[str, Any] | None = None) -> str:
    schema = schema or numbers_openapi_schema()
    discovery = schema.get("x-phantom-api-discovery") if isinstance(schema.get("x-phantom-api-discovery"), dict) else {}
    actions = discovery.get("actions") if isinstance(discovery.get("actions"), dict) else {}
    capabilities = discovery.get("capabilities") if isinstance(discovery.get("capabilities"), dict) else {}
    base_path = str(discovery.get("base_path") or schema.get("servers", [{}])[0].get("url") or "/api/v1/numbers")

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex, nofollow">
  <title>{_esc(schema.get('info', {}).get('title') or 'Phantom Numbers API')}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f8fb;
      --panel: #ffffff;
      --ink: #14213d;
      --muted: #667085;
      --line: #d9e2ec;
      --brand: #0b8a7b;
      --brand-2: #0a6f63;
      --warn: #8a4b00;
      --ok: #067647;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: var(--bg);
      line-height: 1.5;
    }}
    header {{
      background: var(--panel);
      border-bottom: 1px solid var(--line);
    }}
    .wrap {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 28px 18px;
    }}
    h1, h2 {{
      margin: 0;
      letter-spacing: 0;
    }}
    h1 {{ font-size: clamp(28px, 4vw, 44px); line-height: 1.08; }}
    h2 {{ font-size: 20px; margin-bottom: 12px; }}
    p {{ color: var(--muted); margin: 10px 0 0; }}
    a {{ color: var(--brand-2); font-weight: 700; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .top-grid {{
      display: grid;
      grid-template-columns: minmax(0, 1.5fr) minmax(280px, .8fr);
      gap: 18px;
      align-items: start;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
      margin-top: 18px;
      overflow: hidden;
    }}
    .chips {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 18px; }}
    .chip {{
      display: inline-flex;
      align-items: center;
      border: 1px solid #b7d9d2;
      background: #eefaf8;
      color: var(--brand-2);
      border-radius: 999px;
      padding: 5px 10px;
      font-size: 13px;
      font-weight: 700;
    }}
    code {{
      background: #eef2f6;
      border: 1px solid #d9e2ec;
      border-radius: 6px;
      padding: 2px 5px;
      font-size: 12px;
      overflow-wrap: anywhere;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }}
    th, td {{
      text-align: left;
      vertical-align: top;
      border-bottom: 1px solid var(--line);
      padding: 10px 8px;
    }}
    th {{
      color: #344054;
      background: #f8fafc;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: .04em;
    }}
    tr:last-child td {{ border-bottom: 0; }}
    .method {{
      display: inline-block;
      min-width: 52px;
      text-align: center;
      border-radius: 6px;
      padding: 3px 7px;
      font-size: 12px;
      font-weight: 800;
      color: #fff;
      background: #475467;
    }}
    .method-get {{ background: #0b8a7b; }}
    .method-post {{ background: #175cd3; }}
    .ok {{ color: var(--ok); font-weight: 700; }}
    .muted {{ color: var(--warn); font-weight: 700; }}
    .cap-list {{
      list-style: none;
      margin: 0;
      padding: 0;
      display: grid;
      gap: 8px;
    }}
    .cap-list li {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      border-bottom: 1px solid var(--line);
      padding-bottom: 8px;
    }}
    .cap-list li:last-child {{ border-bottom: 0; padding-bottom: 0; }}
    .cap-list span {{ color: var(--muted); }}
    .cap-list strong {{ text-align: right; overflow-wrap: anywhere; }}
    .table-wrap {{ overflow-x: auto; }}
    footer {{ color: var(--muted); font-size: 12px; padding-bottom: 30px; }}
    @media (max-width: 820px) {{
      .top-grid {{ grid-template-columns: 1fr; }}
      .wrap {{ padding: 22px 12px; }}
      th, td {{ padding: 9px 6px; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="wrap top-grid">
      <section>
        <h1>{_esc(schema.get('info', {}).get('title') or 'Phantom Numbers API')}</h1>
        <p>{_esc(schema.get('info', {}).get('description') or '')}</p>
        <div class="chips">
          <span class="chip">Base path: {_esc(base_path)}</span>
          <span class="chip">Version: {_esc(schema.get('info', {}).get('version') or 'v1')}</span>
          <span class="chip">Server-managed refunds</span>
          <span class="chip">Webhook-first delivery</span>
        </div>
      </section>
      <aside class="panel">
        <h2>References</h2>
        <p><a href="{_esc(base_path)}/openapi.json">OpenAPI JSON</a></p>
        <p><a href="{_esc(base_path)}/catalog/bootstrap">Bootstrap discovery</a></p>
        <p><a href="{_esc(base_path)}/health">Health check</a></p>
      </aside>
    </div>
  </header>
  <main class="wrap">
    <section class="panel">
      <h2>Capabilities</h2>
      <ul class="cap-list">
        {_capability_items(capabilities)}
      </ul>
    </section>
    <section class="panel">
      <h2>Endpoint Reference</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>Method</th><th>Path</th><th>Summary</th><th>Scope</th><th>Parameters</th></tr>
          </thead>
          <tbody>
            {_endpoint_rows(schema.get('paths') if isinstance(schema.get('paths'), dict) else {})}
          </tbody>
        </table>
      </div>
    </section>
    <section class="panel">
      <h2>Action Catalog</h2>
      <p>Use this catalog to wire external bots and partner clients without depending on Mini App internals.</p>
      <div class="table-wrap">
        <table>
          <thead>
            <tr><th>Key</th><th>Method</th><th>Endpoint</th><th>Scope</th><th>Idempotency</th><th>Status</th></tr>
          </thead>
          <tbody>
            {_action_rows(actions)}
          </tbody>
        </table>
      </div>
    </section>
  </main>
  <footer class="wrap">Generated from the runtime OpenAPI schema and API discovery payload.</footer>
</body>
</html>"""
