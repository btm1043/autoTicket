import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autoticket_app.models import FieldBinding


ALLOW_INSECURE_TLS_FOR_HOSTS = {"127.0.0.1", "localhost"}
APP_NAME = "AutoTicket"
PROFILE_NAME = "sn-profile"
SERVICENOW_CONFIG_FILENAME = "servicenow_config.json"


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ServiceNowSettings:
    start_url: str
    host_regex: str
    ready_dom_selector: str
    field_bindings: tuple[FieldBinding, ...]
    source_path: Path


@dataclass(frozen=True)
class ServiceNowConfigLoadResult:
    settings: ServiceNowSettings
    warnings: tuple[str, ...] = ()


def get_runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def get_bundle_root() -> Path:
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root)
    return get_runtime_root()


def get_servicenow_config_candidates(local_data_dir: Path | None = None) -> tuple[Path, ...]:
    candidates = []

    if local_data_dir is not None:
        candidates.append(local_data_dir / SERVICENOW_CONFIG_FILENAME)

    candidates.append(get_runtime_root() / SERVICENOW_CONFIG_FILENAME)

    bundle_candidate = get_bundle_root() / SERVICENOW_CONFIG_FILENAME
    if bundle_candidate not in candidates:
        candidates.append(bundle_candidate)

    return tuple(candidates)


def _load_json_file(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except OSError as exc:
        raise ConfigError(f"could not read file: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}") from exc


def _require_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"'{key}' must be a non-empty string")
    return value


def _parse_field_binding(index: int, data: Any) -> FieldBinding:
    if not isinstance(data, dict):
        raise ConfigError(f"'field_bindings[{index}]' must be an object")

    value_key = _require_string(data, "value_key")
    form_field = _require_string(data, "form_field")

    selectors = data.get("selectors")
    if not isinstance(selectors, list):
        raise ConfigError(f"'field_bindings[{index}].selectors' must be an array")

    normalized_selectors = []
    for selector_index, selector in enumerate(selectors):
        if not isinstance(selector, str):
            raise ConfigError(
                f"'field_bindings[{index}].selectors[{selector_index}]' must be a string"
            )
        normalized_selectors.append(selector)

    return FieldBinding(
        value_key=value_key,
        form_field=form_field,
        selectors=tuple(normalized_selectors),
    )


def _parse_servicenow_settings(data: Any, source_path: Path) -> ServiceNowSettings:
    if not isinstance(data, dict):
        raise ConfigError("root JSON value must be an object")

    field_bindings_data = data.get("field_bindings")
    if not isinstance(field_bindings_data, list) or not field_bindings_data:
        raise ConfigError("'field_bindings' must be a non-empty array")

    field_bindings = tuple(
        _parse_field_binding(index, binding_data)
        for index, binding_data in enumerate(field_bindings_data)
    )

    return ServiceNowSettings(
        start_url=_require_string(data, "start_url"),
        host_regex=_require_string(data, "host_regex"),
        ready_dom_selector=_require_string(data, "ready_dom_selector"),
        field_bindings=field_bindings,
        source_path=source_path,
    )


def load_servicenow_settings(local_data_dir: Path | None = None) -> ServiceNowConfigLoadResult:
    warnings = []
    existing_candidates = []

    for candidate in get_servicenow_config_candidates(local_data_dir):
        if not candidate.exists():
            continue

        existing_candidates.append(candidate)

        try:
            data = _load_json_file(candidate)
            settings = _parse_servicenow_settings(data, candidate)
            return ServiceNowConfigLoadResult(
                settings=settings,
                warnings=tuple(warnings),
            )
        except ConfigError as exc:
            warnings.append(f"[config][warn] ignoring ServiceNow config at {candidate}: {exc}")

    if existing_candidates:
        details = "\n".join(warnings)
        raise ConfigError(f"No valid ServiceNow config could be loaded.\n{details}")

    searched = "\n".join(str(path) for path in get_servicenow_config_candidates(local_data_dir))
    raise ConfigError(
        "No ServiceNow config file was found. Looked in:\n"
        f"{searched}"
    )
