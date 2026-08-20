import re
from collections.abc import Sequence

PLACEHOLDER_SYNTAX = "double_curly_lower_snake_case"

SCOPE_ALLOWED_KEYS: dict[str, tuple[str, ...]] = {
    "quick_upload": ("input", "actual_output", "expected_output"),
    "single_turn": ("input", "actual_output", "expected_output"),
    "multi_turn": ("role", "content", "expected_outcome"),
}

_PLACEHOLDER_KEY = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*")


class CustomMetricPlaceholderError(ValueError):
    def __init__(
        self,
        error_type: str,
        message: str,
        *,
        evaluation_scope: str,
        invalid_tokens: Sequence[str] = (),
        allowed_keys: Sequence[str],
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message
        self.evaluation_scope = evaluation_scope
        self.invalid_tokens = tuple(invalid_tokens)
        self.allowed_keys = tuple(allowed_keys)

    @property
    def context(self) -> dict[str, object]:
        return {
            "evaluation_scope": self.evaluation_scope,
            "invalid_tokens": list(self.invalid_tokens),
            "allowed_keys": list(self.allowed_keys),
        }


def allowed_keys_for_scope(evaluation_scope: str) -> tuple[str, ...]:
    allowed = SCOPE_ALLOWED_KEYS.get(evaluation_scope)
    if allowed is None:
        raise ValueError("Unknown custom metric evaluation scope")
    return allowed


def _placeholder_candidates(prompt: str) -> tuple[list[str], list[str]]:
    keys: list[str] = []
    malformed: list[str] = []
    cursor = 0
    while cursor < len(prompt):
        opening = prompt.find("{{", cursor)
        closing = prompt.find("}}", cursor)
        if closing != -1 and (opening == -1 or closing < opening):
            malformed.append("}}")
            cursor = closing + 2
            continue
        if opening == -1:
            break
        closing = prompt.find("}}", opening + 2)
        if closing == -1:
            malformed.append(prompt[opening:])
            break
        token = prompt[opening : closing + 2]
        key = prompt[opening + 2 : closing]
        if "{{" in key or _PLACEHOLDER_KEY.fullmatch(key) is None:
            malformed.append(token)
        else:
            keys.append(key)
        cursor = closing + 2
    return keys, malformed


def parse_custom_metric_prompt(prompt: str, evaluation_scope: str) -> tuple[str, ...]:
    """Validate reserved ``{{key}}`` placeholders and return unique keys in order."""
    allowed = allowed_keys_for_scope(evaluation_scope)
    keys, malformed = _placeholder_candidates(prompt)
    if malformed:
        invalid_tokens = tuple(dict.fromkeys(malformed))
        raise CustomMetricPlaceholderError(
            "custom_metric_placeholder_malformed",
            "placeholder 문법이 올바르지 않습니다: " + ", ".join(invalid_tokens),
            evaluation_scope=evaluation_scope,
            invalid_tokens=invalid_tokens,
            allowed_keys=allowed,
        )

    unique_keys = tuple(dict.fromkeys(keys))
    if not unique_keys:
        raise CustomMetricPlaceholderError(
            "custom_metric_placeholder_required",
            "프롬프트에 허용된 placeholder를 하나 이상 포함해야 합니다.",
            evaluation_scope=evaluation_scope,
            allowed_keys=allowed,
        )

    unknown = tuple(key for key in unique_keys if key not in allowed)
    if unknown:
        raise CustomMetricPlaceholderError(
            "custom_metric_placeholder_not_allowed",
            f"{evaluation_scope} 범위에서 지원하지 않는 placeholder입니다: "
            + ", ".join(unknown),
            evaluation_scope=evaluation_scope,
            invalid_tokens=unknown,
            allowed_keys=allowed,
        )
    return unique_keys


def ensure_required_values(
    required_keys: list[str] | tuple[str, ...], values: dict[str, object]
) -> None:
    missing: list[str] = []
    for key in required_keys:
        value = values.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(key)
    if missing:
        raise ValueError(
            "Custom metric requires non-empty execution data: " + ", ".join(missing)
        )
