"""Value rules for parser and engine options that come from configuration.

A rule only inspects the value it is given. Nothing here reads files or the
environment, so the same options pass or fail in every process.

Typical usage example:

    rules = {"dpi": or_null(number_from(1)), "quiet": BOOLEAN}
    require_permitted_options("LiteParse", {"dpi": 150, "quiet": True}, rules)
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, replace
from math import isfinite
from typing import TypeGuard


@dataclass(frozen=True, slots=True)
class OptionRule:
    """The values one option accepts.

    Attributes:
        permitted: Wording of the accepted values, completing "must be".
        accepts: Tell whether a value is accepted.
        shown: Render a rejected value for the error message.
    """

    permitted: str
    accepts: Callable[[object], bool]
    shown: Callable[[object], str] = repr


def one_of(choices: Collection[str]) -> OptionRule:
    """Accept exactly one of the given names, compared as written."""
    return OptionRule(
        f"one of {', '.join(sorted(choices))}",
        lambda value: isinstance(value, str) and value in choices,
    )


def integer_from(minimum: int) -> OptionRule:
    """Accept a whole number of at least ``minimum``, which a boolean is not."""
    return OptionRule(
        f"an integer of at least {minimum}",
        lambda value: _is_integer(value) and value >= minimum,
    )


def number_from(minimum: float) -> OptionRule:
    """Accept a finite number of at least ``minimum``, which a boolean is not."""
    return OptionRule(
        f"a number of at least {minimum:g}",
        lambda value: _is_number(value) and value >= minimum,
    )


def or_null(rule: OptionRule) -> OptionRule:
    """Accept null as well as the values ``rule`` accepts."""
    return replace(
        rule,
        permitted=f"{rule.permitted} or null",
        accepts=lambda value: value is None or rule.accepts(value),
    )


def concealed(rule: OptionRule) -> OptionRule:
    """Show only the type of a rejected value, for an option that may hold a credential."""
    return replace(rule, shown=_type_name)


BOOLEAN = OptionRule("true or false", lambda value: isinstance(value, bool))
TEXT = OptionRule("text", lambda value: isinstance(value, str))


def require_permitted_options(
    owner: str,
    values: Mapping[str, object],
    rules: Mapping[str, OptionRule],
) -> None:
    """Reject the first option whose value its rule does not accept.

    Args:
        owner: What the options configure, such as ``LiteParse``. It opens
            the message.
        values: Option values by name, holding at least every name in ``rules``.
        rules: The rule of each checked option.

    Raises:
        ValueError: An option's value is not accepted. The message names the
            option, what it accepts and the value given, or only the value's
            type for a concealed option.
    """
    for name, rule in rules.items():
        value = values[name]
        if not rule.accepts(value):
            raise ValueError(f"{owner} {name} must be {rule.permitted}, got {rule.shown(value)}")


def _is_integer(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: object) -> TypeGuard[int | float]:
    return _is_integer(value) or (isinstance(value, float) and isfinite(value))


def _type_name(value: object) -> str:
    return type(value).__name__
