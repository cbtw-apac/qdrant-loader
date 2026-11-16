"""The per-source-type strategy: schemas, validation and the dataclass mapping.

Handles:
- validating a connection's credentials, config and tuning, collecting every field issue
- publishing the spec's ``SourceType`` object (JSON Schemas, ``ui`` hints, capabilities)
- mapping stored values to and from the connector config dataclass keywords

Does NOT resolve secret references or build connectors; see ``builder.py``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import ValidationError
from pydantic.fields import FieldInfo

from harborrag_core.contracts.errors import HarborValidationError

from .fields import WIDGET_MARKER, StrictModel, is_secret

AuthMethodId = Literal["api_token", "oauth", "pat", "app", "none"]
Category = Literal["issue_tracker", "wiki", "files", "code"]

METHOD_KEY = "method"
OPERATOR_FIELD_HELP = "can be set only in connectors.yaml or with the harborrag CLI"
_COMBINATORS = ("anyOf", "allOf", "oneOf", "not")
_WIDGET_BY_TYPE = {"array": "list", "boolean": "toggle", "integer": "number", "number": "number"}
_ICON_BASE = "https://cdn.harborrag.dev/icons"
_DOCS_BASE = "https://docs.harborrag.dev/connectors"


@dataclass(frozen=True, slots=True)
class FieldIssue:
    """One failing field, addressed as ``credentials.<name>`` or ``config.<name>``."""

    field: str
    issue: str

    def as_dict(self) -> dict[str, str]:
        """Return the ``{field, issue}`` shape the API error details use."""
        return {"field": self.field, "issue": self.issue}


class ConnectionValidationError(HarborValidationError):
    """Credentials, config or tuning fail the source type's schema."""

    error_code = "validation_error"

    def __init__(self, issues: Sequence[FieldIssue]) -> None:
        super().__init__(
            "connection does not match its source type schema",
            details={"errors": [issue.as_dict() for issue in issues]},
        )
        self.issues = tuple(issues)


@dataclass(frozen=True, slots=True)
class AuthMethodSpec:
    """One way to authenticate, with the dataclass keywords it implies.

    ``derived`` keywords pick the method and are not stored; ``implied_by`` picks it
    from keywords that are, such as a Cloud ``deployment_type``.
    """

    id: AuthMethodId
    title: str
    model: type[StrictModel]
    derived: Mapping[str, Any] = field(default_factory=dict)
    implied_by: Callable[[Mapping[str, Any]], bool] | None = None


@dataclass(frozen=True, slots=True)
class Setup:
    """One way to set up a connection: where the source runs or how it is reached.

    Each setup fixes the auth method and the values it implies. Connection
    templates are built per setup, such as Jira Cloud, Jira Data Center or a
    public GitHub repository.
    """

    id: str
    title: str
    method: AuthMethodId
    note: str
    credentials: Mapping[str, Any] = field(default_factory=dict)
    config: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Capabilities:
    """What a source type supports, as published to the connection form."""

    incremental: bool
    attachments: bool
    acl_sync: bool = False


@dataclass(frozen=True, slots=True)
class ValidatedConnection:
    """Normalized, schema-checked credentials, config and tuning."""

    credentials: dict[str, Any]
    config: dict[str, Any]
    tuning: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SourceTypeSpec:
    """Everything HarborRAG knows about one source type.

    ``credential_renames`` maps a public credential name to the dataclass
    keyword it feeds; ``query_fields`` are config fields that travel in the
    run's query filters instead of the dataclass; ``query_narrowers`` gives a
    query field the function that combines the connection's value with a run's
    so the run selects no more than the connection does, raising ``ValueError``
    when it cannot, and a query field without one cannot be set by a run once
    the connection configures it; ``endpoints`` are the
    credential fields naming the host secrets are sent to;
    ``operator_fields`` are credential fields only the CLI and
    ``connectors.yaml`` may set, such as a worker file path;
    ``tenant_keyword`` is the dataclass keyword that receives the connection's
    tenant, which no caller can set; ``build_check``
    is False when building the config reads the worker's file system, so
    the API cannot check it; ``policy`` holds install rules every write
    obeys and ``api_policy`` rules only API writes obey; ``setups`` are the
    setups a connection template is offered for.
    """

    source_type: str
    name: str
    category: Category
    provider: str
    auth_methods: tuple[AuthMethodSpec, ...]
    config_model: type[StrictModel]
    tuning_model: type[StrictModel]
    capabilities: Capabilities
    credential_renames: Mapping[str, str] = field(default_factory=dict)
    endpoints: frozenset[str] = frozenset()
    operator_fields: frozenset[str] = frozenset()
    tenant_keyword: str | None = None
    build_check: bool = True
    query_fields: frozenset[str] = frozenset()
    query_narrowers: Mapping[str, Callable[[str, str], str]] = field(default_factory=dict)
    aliases: tuple[str, ...] = ()
    version: str = "2.0.0"
    policy: Callable[[Mapping[str, Any]], list[FieldIssue]] | None = None
    api_policy: Callable[[Mapping[str, Any]], list[FieldIssue]] | None = None
    setups: tuple[Setup, ...] = ()

    @property
    def credential_fields(self) -> frozenset[str]:
        """Every credential field across all auth methods."""
        return frozenset(name for method in self.auth_methods for name in method.model.model_fields)

    @property
    def secret_fields(self) -> frozenset[str]:
        """Credential fields that are write-only secrets."""
        return frozenset(
            name
            for method in self.auth_methods
            for name, info in method.model.model_fields.items()
            if is_secret(info)
        )

    def method_secret_fields(self, method_id: str | None) -> frozenset[str]:
        """Secret fields of the auth method ``method_id`` names, or of the default one.

        Raises:
            KeyError: ``method_id`` names no auth method of this type.
        """
        model = self.auth_method(method_id).model
        return frozenset(name for name, info in model.model_fields.items() if is_secret(info))

    @property
    def config_fields(self) -> frozenset[str]:
        """Every field of the config model."""
        return frozenset(self.config_model.model_fields)

    @property
    def tuning_fields(self) -> frozenset[str]:
        """Every field of the tuning model."""
        return frozenset(self.tuning_model.model_fields)

    @property
    def has_method_choice(self) -> bool:
        """True when credentials must name their auth method."""
        return len(self.auth_methods) > 1

    def auth_method(self, method_id: str | None) -> AuthMethodSpec:
        """Return the auth method ``method_id`` names, or the default one.

        Raises:
            KeyError: ``method_id`` names no auth method of this type.
        """
        if method_id is None:
            return self.auth_methods[0]
        for method in self.auth_methods:
            if method.id == method_id:
                return method
        raise KeyError(method_id)

    def validate(
        self,
        credentials: Mapping[str, Any],
        config: Mapping[str, Any],
        tuning: Mapping[str, Any] | None = None,
    ) -> ValidatedConnection:
        """Check credentials, config and tuning against this type's models.

        Args:
            credentials: Effective credentials; secrets as values or references.
            config: What to sync.
            tuning: Per-connection overrides of connector defaults; ``None`` means the default.

        Returns:
            The normalized values, holding only fields the caller set; tuning drops ``None``.

        Raises:
            ConnectionValidationError: Any field fails; every failing field is listed.
        """
        issues: list[FieldIssue] = []
        method_id = credentials.get(METHOD_KEY)
        try:
            method = self.auth_method(method_id)
        except KeyError:
            allowed = ", ".join(m.id for m in self.auth_methods)
            issues.append(FieldIssue(f"credentials.{METHOD_KEY}", f"must be one of: {allowed}"))
            method = self.auth_methods[0]
        values = {key: value for key, value in credentials.items() if key != METHOD_KEY}
        checked_credentials = _check(method.model, values, "credentials", issues)
        checked_config = _check(self.config_model, config, "config", issues)
        checked_tuning = {
            key: value
            for key, value in _check(self.tuning_model, tuning or {}, "advanced", issues).items()
            if value is not None
        }
        if checked_config:
            issues.extend(self.policy_issues(checked_config))
        if issues:
            raise ConnectionValidationError(issues)
        if self.has_method_choice:
            checked_credentials = {METHOD_KEY: method.id, **checked_credentials}
        return ValidatedConnection(checked_credentials, checked_config, checked_tuning)

    def api_policy_issues(self, config: Mapping[str, Any]) -> list[FieldIssue]:
        """Install rules only API writes obey, such as requiring a local source root."""
        return self.api_policy(config) if self.api_policy is not None else []

    def operator_field_issues(
        self,
        incoming: Mapping[str, Any],
        stored: Mapping[str, Any] | None,
        *,
        part: str = "credentials",
        merge: bool = False,
    ) -> list[FieldIssue]:
        """List the operator-only fields an API write would change.

        Args:
            incoming: The fields the caller sent.
            stored: The connection's stored fields, or ``None`` for a new connection.
            part: Prefix of the reported field path.
            merge: True when a field left out keeps its stored value; otherwise
                leaving it out clears it, which is a change too.

        Returns:
            One issue per operator-only field whose value would change.
        """
        before = stored or {}
        return [
            FieldIssue(f"{part}.{name}", OPERATOR_FIELD_HELP)
            for name in sorted(self.operator_fields)
            if not (merge and name not in incoming) and incoming.get(name) != before.get(name)
        ]

    def policy_issues(self, config: Mapping[str, Any]) -> list[FieldIssue]:
        """Install-level rules a schema cannot express, such as allowed local roots."""
        return self.policy(config) if self.policy is not None else []

    def describe(self, defaults: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Return the API's ``SourceType`` object for this type.

        Args:
            defaults: Connector defaults by dataclass keyword, published as the
                ``default`` of config and advanced fields that leave a value out.

        Returns:
            The ``SourceType`` object; each auth method carries its own ``ui`` hints.
        """
        known = dict(defaults or {})
        config_schema = _with_defaults(publish_schema(self.config_model), known)
        advanced_schema = _with_defaults(publish_schema(self.tuning_model), known)
        return {
            "source_type": self.source_type,
            "name": self.name,
            "category": self.category,
            "icon": f"{_ICON_BASE}/{self.source_type}.svg",
            "version": self.version,
            "docs_url": f"{_DOCS_BASE}/{self.source_type}",
            "auth_methods": [
                {
                    "auth_method_id": method.id,
                    "title": method.title,
                    "schema": self._method_schema(method),
                    "ui": _hints(_model_hints(method.model, "Connection")),
                }
                for method in self.auth_methods
            ],
            "config_schema": config_schema,
            "advanced_schema": advanced_schema,
            "ui": self._ui_hints(config_schema, advanced_schema),
            "capabilities": {
                "incremental": self.capabilities.incremental,
                "acl_sync": self.capabilities.acl_sync,
                "attachments": self.capabilities.attachments,
            },
        }

    def flatten(
        self,
        credentials: Mapping[str, Any],
        config: Mapping[str, Any],
        tuning: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Name every stored value by its dataclass keyword; secrets stay as references.

        Args:
            credentials: Stored credentials.
            config: Stored config, query fields included.
            tuning: Stored tuning overrides.

        Returns:
            The inverse of ``split_flat``, with method-implied keywords added.
        """
        method = self.auth_method(credentials.get(METHOD_KEY))
        values: dict[str, Any] = dict(method.derived)
        for key, value in credentials.items():
            if key != METHOD_KEY:
                values[self.credential_renames.get(key, key)] = value
        values.update(config)
        values.update(tuning)
        return values

    def to_connector_values(
        self,
        credentials: Mapping[str, Any],
        config: Mapping[str, Any],
        tuning: Mapping[str, Any],
        secret_values: Mapping[str, str],
    ) -> dict[str, Any]:
        """Flatten stored values into the connector config dataclass keywords.

        Args:
            credentials: Validated credentials; secrets as references or values.
            config: Validated config.
            tuning: Validated tuning overrides.
            secret_values: Resolved plaintext for each secret field held as a reference.

        Returns:
            Keyword arguments for the provider's config dataclass.

        Raises:
            ConnectionValidationError: A secret reference has no resolved value.
        """
        unresolved = [
            FieldIssue(f"credentials.{key}", "secret is not resolved")
            for key, value in credentials.items()
            if isinstance(value, Mapping) and key not in secret_values
        ]
        if unresolved:
            raise ConnectionValidationError(unresolved)
        resolved = {
            key: secret_values[key] if isinstance(value, Mapping) else value
            for key, value in credentials.items()
        }
        syncable = {key: value for key, value in config.items() if key not in self.query_fields}
        return self.flatten(resolved, syncable, tuning)

    def query_filters(self, config: Mapping[str, Any]) -> dict[str, Any]:
        """Return the config values that travel in the run's query filters."""
        return {key: config[key] for key in sorted(self.query_fields) if config.get(key)}

    def split_flat(
        self, flat: Mapping[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        """Split dataclass keywords (e.g. a legacy YAML entry) into the three stored parts.

        Args:
            flat: Keyword arguments as the provider dataclass names them.

        Returns:
            ``(credentials, config, tuning)``; credentials name their auth method
            when the type has several.
        """
        public = {target: name for name, target in self.credential_renames.items()}
        derived_keys = {key for method in self.auth_methods for key in method.derived}
        credentials: dict[str, Any] = {}
        config: dict[str, Any] = {}
        tuning: dict[str, Any] = {}
        for key, value in flat.items():
            name = public.get(key, key)
            if key in derived_keys:
                continue
            if name in self.credential_fields:
                credentials[name] = value
            elif key in self.tuning_fields:
                tuning[key] = value
            else:
                config[key] = value
        if self.has_method_choice:
            credentials = {METHOD_KEY: self._infer_method(flat, credentials), **credentials}
        return credentials, config, tuning

    def _infer_method(self, flat: Mapping[str, Any], credentials: Mapping[str, Any]) -> str:
        """Pick the auth method a flat entry implies: derived keys, implied_by, required fields."""
        for method in self.auth_methods:
            if method.derived and all(
                str(flat.get(key, "")).strip().lower() == value
                for key, value in method.derived.items()
            ):
                return method.id
        for method in self.auth_methods:
            if method.implied_by is not None and method.implied_by(flat):
                return method.id
        for method in self.auth_methods:
            required = {n for n, info in method.model.model_fields.items() if info.is_required()}
            if required <= set(credentials):
                return method.id
        return self.auth_methods[0].id

    def _method_schema(self, method: AuthMethodSpec) -> dict[str, Any]:
        """Publish an auth method's schema, naming it in ``method`` when the type has several."""
        schema = publish_schema(method.model)
        if not self.has_method_choice:
            return schema
        is_default = method is self.auth_methods[0]
        selector: dict[str, Any] = {
            "const": method.id,
            "description": "Auth method; may be left out for the first method only",
        }
        if is_default:
            selector["default"] = method.id
        schema["properties"] = {METHOD_KEY: selector, **schema["properties"]}
        if not is_default:
            schema["required"] = [METHOD_KEY, *schema.get("required", [])]
        return schema

    def _ui_hints(
        self, config_schema: Mapping[str, Any], advanced_schema: Mapping[str, Any]
    ) -> dict[str, dict[str, Any]]:
        """Form hints of config and advanced fields, plus credential fields every method shares."""
        per_method = [_model_hints(method.model, "Connection") for method in self.auth_methods]
        shared = {
            name: hint
            for name, hint in per_method[0].items()
            if all(hints.get(name) == hint for hints in per_method[1:])
        }
        return _hints(
            {
                **shared,
                **_model_hints(self.config_model, "Sync", config_schema),
                **_model_hints(self.tuning_model, "Advanced", advanced_schema),
            }
        )


def _model_hints(
    model: type[StrictModel], group: str, published: Mapping[str, Any] | None = None
) -> dict[str, dict[str, Any]]:
    """Build the form hint of each field of ``model``, without its ``order``."""
    properties = (published or publish_schema(model))["properties"]
    hints: dict[str, dict[str, Any]] = {}
    for name, info in model.model_fields.items():
        examples = info.examples or []
        hints[name] = {
            "group": group,
            "widget": _widget_for(info, properties.get(name, {})),
            "help": info.description or "",
            "placeholder": str(examples[0]) if examples else "",
        }
    return hints


def _hints(hints: Mapping[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Number the hints in form order."""
    return {name: {**hint, "order": order} for order, (name, hint) in enumerate(hints.items(), 1)}


def _with_defaults(schema: dict[str, Any], defaults: Mapping[str, Any]) -> dict[str, Any]:
    """Publish the connector's default, which a left-out field gets, on each property."""
    for name, prop in schema["properties"].items():
        if defaults.get(name) is not None:
            prop["default"] = defaults[name]
    return schema


def publish_schema(model: type[StrictModel]) -> dict[str, Any]:
    """Return a compact JSON Schema of ``model`` as the API publishes it."""
    raw = model.model_json_schema(mode="validation")
    properties = {name: _clean(prop) for name, prop in raw.get("properties", {}).items()}
    schema: dict[str, Any] = {"type": "object"}
    if raw.get("required"):
        schema["required"] = list(raw["required"])
    schema["properties"] = properties
    schema.update({key: raw[key] for key in _COMBINATORS if key in raw})
    return schema


def _clean(prop: dict[str, Any]) -> dict[str, Any]:
    """Drop titles and markers and collapse ``X | None`` into ``X``."""
    cleaned = {key: value for key, value in prop.items() if key not in {"title", WIDGET_MARKER}}
    options = cleaned.pop("anyOf", None)
    if options is not None:
        concrete = [option for option in options if option.get("type") != "null"]
        if len(concrete) == 1:
            cleaned = {**concrete[0], **cleaned}
        else:
            cleaned["anyOf"] = concrete
    if cleaned.get("default", "") is None:
        cleaned.pop("default")
    if isinstance(cleaned.get("items"), dict):
        cleaned["items"] = _clean(cleaned["items"])
    return cleaned


def _widget_for(info: FieldInfo, published: Mapping[str, Any]) -> str:
    """Choose the form widget of a field from its marker, secrecy or published type."""
    if is_secret(info):
        return "secret"
    extra = info.json_schema_extra if isinstance(info.json_schema_extra, dict) else {}
    if WIDGET_MARKER in extra:
        return str(extra[WIDGET_MARKER])
    if "enum" in published or "const" in published:
        return "select"
    return _WIDGET_BY_TYPE.get(str(published.get("type")), "text")


def _check(
    model: type[StrictModel],
    values: Mapping[str, Any],
    prefix: str,
    issues: list[FieldIssue],
) -> dict[str, Any]:
    """Validate ``values`` against ``model``, appending each failure to ``issues``."""
    try:
        return model.model_validate(dict(values)).model_dump(mode="json", exclude_unset=True)
    except ValidationError as error:
        seen: set[str] = set()
        for detail in error.errors(include_url=False, include_input=False):
            location = detail["loc"]
            path = f"{prefix}.{location[0]}" if location else prefix
            if path not in seen:
                seen.add(path)
                issues.append(FieldIssue(path, _issue(detail)))
        return {}


def _issue(detail: Mapping[str, Any]) -> str:
    """Turn a pydantic error into a short, stable issue text."""
    kind = detail.get("type")
    if kind == "missing":
        return "required"
    if kind == "extra_forbidden":
        return "unknown field"
    return str(detail.get("msg", "invalid value")).removeprefix("Value error, ")
