# ServiceNow Config

`AutoTicket` now loads ServiceNow form settings from `servicenow_config.json`.

## Where the app looks

The app loads the first valid file it finds in this order:

1. `%LOCALAPPDATA%\\AutoTicket\\servicenow_config.json`
2. `servicenow_config.json` next to the app
3. The bundled fallback copy shipped with the app

If a higher-priority file exists but is invalid, the app logs a warning and tries the next one.

## What you can change

- `start_url`: the page the embedded browser opens first
- `host_regex`: what URLs count as your ServiceNow host
- `ready_dom_selector`: what selector means the target form is ready
- `field_bindings`: how ticket keys map to ServiceNow fields and DOM selectors

## Add or update a field

Each binding looks like this:

```json
{
  "value_key": "short_description",
  "form_field": "short_description",
  "selectors": [
    "#incident\\.short_description",
    "input[name='incident.short_description']",
    "input[name='short_description']"
  ]
}
```

- `value_key` is the ticket JSON key the app reads
- `form_field` is the `g_form.setValue(...)` field name
- `selectors` are DOM fallbacks if `g_form` is unavailable

If you add a brand-new ticket field, you still need phase 3 Python work to add that field to the canonical `Ticket` model. If you are only remapping an existing field to a different ServiceNow control, JSON-only changes are enough.
