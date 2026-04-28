import json
import re
from collections.abc import Iterable

from autoticket_app.models import FieldBinding, Ticket


def is_servicenow_url(url: str, host_regex: str) -> bool:
    return bool(re.search(host_regex, url or "", re.IGNORECASE))


def build_form_values(ticket: Ticket) -> dict[str, str]:
    values = {}
    for key, value in ticket.to_dict().items():
        if value is None:
            values[key] = ""
        elif isinstance(value, str):
            values[key] = value
        else:
            values[key] = str(value)

    values["caller_id"] = ticket.caller_name or ticket.caller_email
    return values


def _build_binding_payload(field_bindings: Iterable[FieldBinding]) -> list[dict[str, object]]:
    payload = []
    for binding in field_bindings:
        payload.append(
            {
                "value_key": binding.value_key,
                "form_field": binding.form_field,
                "selectors": list(binding.selectors),
            }
        )
    return payload


def build_servicenow_fill_js(
    ticket: Ticket,
    field_bindings: Iterable[FieldBinding],
) -> str:
    payload = {
        "bindings": _build_binding_payload(field_bindings),
        "values": build_form_values(ticket),
    }
    payload_json = json.dumps(payload)

    return f"""
(() => {{
  const payload = {payload_json};
  const out = {{}};

  function setBySelector(sel, value) {{
    const el = document.querySelector(sel);
    if (!el) return false;
    el.focus();
    el.value = value;
    el.dispatchEvent(new Event("input", {{ bubbles: true }}));
    el.dispatchEvent(new Event("change", {{ bubbles: true }}));
    return true;
  }}

  function setField(binding) {{
    const value = Object.prototype.hasOwnProperty.call(payload.values, binding.value_key)
      ? String(payload.values[binding.value_key] ?? "")
      : "";
    let ok = false;

    if (window.g_form && typeof window.g_form.setValue === "function") {{
      try {{
        window.g_form.setValue(binding.form_field, value);
        ok = true;
      }} catch (e) {{
        out[binding.form_field + "_g_form_error"] = String(e);
      }}
    }}

    if (!ok && binding.selectors && binding.selectors.length) {{
      for (const sel of binding.selectors) {{
        if (setBySelector(sel, value)) {{
          ok = true;
          break;
        }}
      }}
    }}

    out[binding.form_field] = ok;
  }}

  for (const binding of payload.bindings) {{
    setField(binding);
  }}

  out.url = window.location.href;
  out.title = document.title;
  return out;
}})();
"""


def build_ready_check_js(required_dom_selector: str) -> str:
    selector_json = json.dumps(required_dom_selector)
    return f"""
(() => {{
  return {{
    ready: Boolean(document.querySelector({selector_json})),
    url: window.location.href,
    title: document.title
  }};
}})();
"""
