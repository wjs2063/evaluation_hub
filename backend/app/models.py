import json
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import EmailStr, ValidationInfo, field_validator, model_validator
from pydantic_core import PydanticCustomError
from sqlalchemy import JSON, Column, DateTime, Numeric
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, Relationship, SQLModel


def get_datetime_utc() -> datetime:
    return datetime.now(UTC)


# Shared properties
class UserBase(SQLModel):
    email: EmailStr = Field(unique=True, index=True, max_length=255)
    is_active: bool = True
    is_superuser: bool = False
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on creation
class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserRegister(SQLModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on update, all are optional
class UserUpdate(SQLModel):
    email: EmailStr | None = Field(default=None, max_length=255)
    is_active: bool | None = None
    is_superuser: bool | None = None
    full_name: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, min_length=8, max_length=128)


class UserUpdateMe(SQLModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)


class UpdatePassword(SQLModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


# Database model, database table inferred from class name
class User(UserBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hashed_password: str
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_column=Column(DateTime(timezone=True)),
    )
    items: list[Item] = Relationship(back_populates="owner", cascade_delete=True)


# Properties to return via API, id is always required
class UserPublic(UserBase):
    id: uuid.UUID
    created_at: datetime | None = None


class UsersPublic(SQLModel):
    data: list[UserPublic]
    count: int


# Shared properties
class ItemBase(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=255)


# Properties to receive on item creation
class ItemCreate(ItemBase):
    pass


# Properties to receive on item update
class ItemUpdate(SQLModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=255)


# Database model, database table inferred from class name
class Item(ItemBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_column=Column(DateTime(timezone=True)),
    )
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    owner: User | None = Relationship(back_populates="items")


# Properties to return via API, id is always required
class ItemPublic(ItemBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime | None = None


class ItemsPublic(SQLModel):
    data: list[ItemPublic]
    count: int


class EvaluationMetricType(StrEnum):
    GEVAL_CORRECTNESS = "geval_correctness"
    GEVAL_CLARITY = "geval_clarity"
    GEVAL_PROFESSIONALISM = "geval_professionalism"
    ANSWER_RELEVANCY = "answer_relevancy"
    SUMMARIZATION = "summarization"
    BIAS = "bias"
    TOXICITY = "toxicity"
    PII_LEAKAGE = "pii_leakage"
    EXACT_MATCH = "exact_match"
    NON_ADVICE = "non_advice"
    MISUSE = "misuse"
    ROLE_VIOLATION = "role_violation"
    TURN_RELEVANCY = "turn_relevancy"
    ROLE_ADHERENCE = "role_adherence"
    KNOWLEDGE_RETENTION = "knowledge_retention"
    CONVERSATION_COMPLETENESS = "conversation_completeness"


class EvaluationMode(StrEnum):
    SINGLE_TURN = "single_turn"
    MULTI_TURN = "multi_turn"


class EvaluationScope(StrEnum):
    QUICK_UPLOAD = "quick_upload"
    SINGLE_TURN = "single_turn"
    MULTI_TURN = "multi_turn"


class EvaluationMetricDefinitionCreate(SQLModel):
    metric_type: EvaluationMetricType | None = None
    custom_metric_id: uuid.UUID | None = None
    weight_percent: int = Field(ge=1, le=100)
    config: dict[str, Any] = Field(default_factory=dict)
    custom_instruction: str | None = Field(default=None, max_length=2000)
    custom_metric_name: str | None = Field(default=None, max_length=255)
    custom_metric_version: int | None = Field(default=None, ge=1)
    custom_metric_prompt: str | None = Field(default=None, max_length=8000)
    required_keys: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def exactly_one_metric_identity(self) -> EvaluationMetricDefinitionCreate:
        if (self.metric_type is None) == (self.custom_metric_id is None):
            raise ValueError(
                "exactly one of metric_type or custom_metric_id must be provided"
            )
        return self


class EvaluationMetricProfileBase(SQLModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=500)
    is_active: bool = True
    evaluation_mode: EvaluationMode = EvaluationMode.SINGLE_TURN
    evaluation_scope: EvaluationScope = EvaluationScope.SINGLE_TURN


class EvaluationMetricProfileCreate(EvaluationMetricProfileBase):
    metrics: list[EvaluationMetricDefinitionCreate] = Field(min_length=1, max_length=16)

    @model_validator(mode="before")
    @classmethod
    def synchronize_scope_and_legacy_mode(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        scope = data.get("evaluation_scope")
        mode = data.get("evaluation_mode")
        if scope is None and mode is not None:
            data["evaluation_scope"] = mode
        elif scope is not None and mode is None:
            data["evaluation_mode"] = (
                "multi_turn" if scope == "multi_turn" else "single_turn"
            )
        return data

    @model_validator(mode="after")
    def validate_metric_set(self) -> EvaluationMetricProfileCreate:
        expected_mode = (
            EvaluationMode.MULTI_TURN
            if self.evaluation_scope == EvaluationScope.MULTI_TURN
            else EvaluationMode.SINGLE_TURN
        )
        if self.evaluation_mode != expected_mode:
            raise ValueError("evaluation_mode must match evaluation_scope")
        keys = [
            metric.metric_type or metric.custom_metric_id for metric in self.metrics
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("metric keys must be unique within a profile")
        if sum(metric.weight_percent for metric in self.metrics) != 100:
            raise ValueError("metric weights must add up to 100 percent")
        multi_turn = {
            EvaluationMetricType.TURN_RELEVANCY,
            EvaluationMetricType.ROLE_ADHERENCE,
            EvaluationMetricType.KNOWLEDGE_RETENTION,
            EvaluationMetricType.CONVERSATION_COMPLETENESS,
        }
        expected = (
            multi_turn
            if expected_mode == EvaluationMode.MULTI_TURN
            else set(EvaluationMetricType) - multi_turn
        )
        if any(
            metric.metric_type is not None and metric.metric_type not in expected
            for metric in self.metrics
        ):
            raise ValueError(
                "metric evaluation mode must match the profile evaluation mode"
            )
        required_config = {
            EvaluationMetricType.NON_ADVICE: ("advice_types",),
            EvaluationMetricType.MISUSE: ("domain",),
            EvaluationMetricType.ROLE_VIOLATION: ("role",),
            EvaluationMetricType.ROLE_ADHERENCE: ("chatbot_role",),
        }
        for metric in self.metrics:
            if metric.metric_type is None:
                continue
            for key in required_config.get(metric.metric_type, ()):
                value = metric.config.get(key)
                if value is None or value == "" or value == []:
                    raise ValueError(
                        f"{metric.metric_type.value} requires config.{key}"
                    )
        return self


class EvaluationMetricProfileUpdate(EvaluationMetricProfileCreate):
    expected_version: int | None = Field(default=None, ge=1)


class EvaluationMetricProfile(EvaluationMetricProfileBase, table=True):
    evaluation_mode: EvaluationMode = Field(
        default=EvaluationMode.SINGLE_TURN,
        sa_column=Column(
            SAEnum(
                EvaluationMode,
                values_callable=lambda enum_type: [item.value for item in enum_type],
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
    )
    evaluation_scope: EvaluationScope = Field(
        default=EvaluationScope.SINGLE_TURN,
        sa_column=Column(
            SAEnum(
                EvaluationScope,
                values_callable=lambda enum_type: [item.value for item in enum_type],
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    version: int = Field(default=1, ge=1)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_column=Column(DateTime(timezone=True)),
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_column=Column(DateTime(timezone=True)),
    )


class EvaluationMetricProfileItem(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    profile_id: uuid.UUID = Field(
        foreign_key="evaluationmetricprofile.id", nullable=False, ondelete="CASCADE"
    )
    position: int = Field(ge=0)
    key: str = Field(min_length=2, max_length=64)
    display_name: str = Field(min_length=1, max_length=100)
    criteria: str = Field(min_length=10, max_length=2000)
    weight_percent: int = Field(ge=1, le=100)
    evaluation_params: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    config: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    custom_instruction: str | None = Field(default=None, max_length=2000)
    custom_metric_id: uuid.UUID | None = Field(
        default=None, foreign_key="custommetric.id", ondelete="RESTRICT"
    )
    custom_metric_version: int | None = Field(default=None, ge=1)
    custom_metric_prompt: str | None = Field(default=None, max_length=8000)
    custom_metric_scope: str | None = Field(default=None, max_length=32)
    required_keys: list[str] = Field(default_factory=list, sa_column=Column(JSON))


class EvaluationMetricDefinitionPublic(EvaluationMetricDefinitionCreate):
    id: uuid.UUID
    position: int
    display_name: str
    description: str
    required_fields: list[str]
    score_direction: str
    uses_llm: bool
    docs_url: str
    evaluation_mode: EvaluationMode
    required_config: list[str]
    supports_custom_instruction: bool


class EvaluationMetricCatalogItem(SQLModel):
    metric_type: EvaluationMetricType
    display_name: str
    description: str
    required_fields: list[str]
    score_direction: str
    uses_llm: bool
    docs_url: str
    evaluation_mode: EvaluationMode
    required_config: list[str]
    supports_custom_instruction: bool


class EvaluationMetricCatalogPublic(SQLModel):
    data: list[EvaluationMetricCatalogItem]
    count: int


class EvaluationMetricProfilePublic(EvaluationMetricProfileBase):
    id: uuid.UUID
    version: int
    created_at: datetime
    updated_at: datetime
    metrics: list[EvaluationMetricDefinitionPublic] = Field(default_factory=list)


class EvaluationMetricProfilesPublic(SQLModel):
    data: list[EvaluationMetricProfilePublic]
    count: int


class CustomMetricBase(SQLModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=500)
    evaluation_scope: EvaluationScope
    prompt: str = Field(min_length=10, max_length=8000)
    is_active: bool = True

    @field_validator("prompt")
    @classmethod
    def validate_prompt_placeholders(cls, prompt: str, info: ValidationInfo) -> str:
        from app.custom_metrics import (
            CustomMetricPlaceholderError,
            parse_custom_metric_prompt,
        )

        evaluation_scope = info.data.get("evaluation_scope")
        if not isinstance(evaluation_scope, EvaluationScope):
            return prompt
        try:
            parse_custom_metric_prompt(prompt, evaluation_scope.value)
        except CustomMetricPlaceholderError as exc:
            if exc.error_type == "custom_metric_placeholder_required":
                raise PydanticCustomError(
                    "custom_metric_placeholder_required",
                    "프롬프트에 허용된 placeholder를 하나 이상 포함해야 합니다.",
                    exc.context,
                )
            if exc.error_type == "custom_metric_placeholder_malformed":
                raise PydanticCustomError(
                    "custom_metric_placeholder_malformed",
                    "placeholder 문법이 올바르지 않습니다: {invalid_tokens}",
                    exc.context,
                )
            if exc.error_type == "custom_metric_placeholder_not_allowed":
                raise PydanticCustomError(
                    "custom_metric_placeholder_not_allowed",
                    "{evaluation_scope} 범위에서 지원하지 않는 placeholder입니다: {invalid_tokens}",
                    exc.context,
                )
            raise RuntimeError("Unknown custom metric placeholder error") from exc
        return prompt


class CustomMetricCreate(CustomMetricBase):
    pass


class CustomMetricUpdate(CustomMetricBase):
    expected_version: int | None = Field(default=None, ge=1)


class CustomMetric(CustomMetricBase, table=True):
    evaluation_scope: EvaluationScope = Field(
        sa_column=Column(
            SAEnum(
                EvaluationScope,
                values_callable=lambda enum_type: [item.value for item in enum_type],
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        )
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    version: int = Field(default=1, ge=1)
    created_by_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL"
    )
    updated_by_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", ondelete="SET NULL"
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_column=Column(DateTime(timezone=True))
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc, sa_column=Column(DateTime(timezone=True))
    )


class CustomMetricPublic(CustomMetricBase):
    id: uuid.UUID
    version: int
    required_keys: list[str]
    created_by_id: uuid.UUID | None
    updated_by_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class CustomMetricsPublic(SQLModel):
    data: list[CustomMetricPublic]
    count: int


class CustomMetricPlaceholderContract(SQLModel):
    evaluation_scope: EvaluationScope
    syntax: Literal["double_curly_lower_snake_case"] = "double_curly_lower_snake_case"
    requires_at_least_one: bool = True
    allowed_keys: list[str]


class CustomMetricPlaceholderContractsPublic(SQLModel):
    data: list[CustomMetricPlaceholderContract]
    count: int


class BulkDeleteRequest(SQLModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=100)

    @field_validator("ids")
    @classmethod
    def unique_ids(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(value) != len(set(value)):
            raise ValueError("bulk ids must be unique")
        return value


def validate_actual_output_path(value: str | None) -> str | None:
    """Validate an RFC 6901 pointer while retaining legacy dotted paths."""
    if value is None or not value.strip():
        return None
    value = value.strip()
    if value.startswith("/"):
        for token in value.split("/")[1:]:
            index = 0
            while index < len(token):
                if token[index] == "~":
                    if index + 1 >= len(token) or token[index + 1] not in {"0", "1"}:
                        raise ValueError(
                            "JSON Pointer '~' escapes must be written as ~0 or ~1"
                        )
                    index += 2
                else:
                    index += 1
    elif any(not segment for segment in value.split(".")):
        raise ValueError("Legacy response paths cannot contain empty segments")
    return value


class EvaluationDatasetBase(SQLModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=500)
    evaluation_type: str = Field(default="single_turn", max_length=32)
    endpoint_url: str | None = Field(default=None, max_length=2048)
    endpoint_id: uuid.UUID | None = Field(
        default=None, foreign_key="evaluationendpoint.id", ondelete="SET NULL"
    )
    metric_profile_id: uuid.UUID | None = Field(
        default=None, foreign_key="evaluationmetricprofile.id", ondelete="SET NULL"
    )
    headers: dict[str, str] = Field(default_factory=dict, sa_column=Column(JSON))
    body_template: str = Field(default='{"input":"{{input}}"}')
    response_path: str | None = Field(default=None, max_length=500)
    threshold: float = Field(default=70, ge=0, le=100, sa_type=Numeric)
    evaluator: str = Field(default="deepeval", max_length=32)

    @field_validator("evaluation_type")
    @classmethod
    def require_single_turn_type(cls, value: str) -> str:
        if value != "single_turn":
            raise ValueError("Evaluation datasets only support the single_turn type")
        return value

    @field_validator("response_path")
    @classmethod
    def validate_response_path(cls, value: str | None) -> str | None:
        return validate_actual_output_path(value)

    @field_validator("body_template")
    @classmethod
    def validate_body_template(cls, value: str) -> str:
        try:
            body = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("Request body_template must be valid JSON") from exc
        if not isinstance(body, dict):
            raise ValueError("Request body_template must be a JSON object")
        return value


class EvaluationDatasetRowCreate(SQLModel):
    input: str
    expected_output: str
    request_headers: dict[str, str] | None = None
    request_body: str | None = None
    response_path: str | None = Field(default=None, max_length=500)

    @field_validator("response_path")
    @classmethod
    def validate_response_path(cls, value: str | None) -> str | None:
        return validate_actual_output_path(value)

    @field_validator("request_body")
    @classmethod
    def validate_request_body(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            body = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("Case request_body must be valid JSON") from exc
        if not isinstance(body, dict):
            raise ValueError("Case request_body must be a JSON object")
        return value


class EvaluationDatasetCreate(EvaluationDatasetBase):
    evaluation_type: Literal["single_turn"] = "single_turn"
    rows: list[EvaluationDatasetRowCreate] = Field(default_factory=list)


class EvaluationDatasetUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=500)
    endpoint_url: str | None = Field(default=None, max_length=2048)
    endpoint_id: uuid.UUID | None = None
    metric_profile_id: uuid.UUID | None = None
    headers: dict[str, str] | None = None
    body_template: str | None = None
    response_path: str | None = Field(default=None, max_length=500)
    threshold: float | None = Field(default=None, ge=0, le=100)
    evaluator: str | None = Field(default=None, max_length=32)


class EvaluationDataset(EvaluationDatasetBase, table=True):
    # The database column is retained for existing installations. Requests are
    # intentionally POST-only, so it is no longer part of the public API.
    method: str = Field(default="POST", max_length=10)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    created_by_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", nullable=True, ondelete="SET NULL"
    )
    updated_by_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", nullable=True, ondelete="SET NULL"
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_column=Column(DateTime(timezone=True))
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc, sa_column=Column(DateTime(timezone=True))
    )


class EvaluationDatasetRowUpdate(SQLModel):
    input: str | None = None
    expected_output: str | None = None
    request_headers: dict[str, str] | None = None
    request_body: str | None = None
    response_path: str | None = Field(default=None, max_length=500)

    @field_validator("response_path")
    @classmethod
    def validate_response_path(cls, value: str | None) -> str | None:
        return validate_actual_output_path(value)

    @field_validator("request_body")
    @classmethod
    def validate_request_body(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            body = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("Case request_body must be valid JSON") from exc
        if not isinstance(body, dict):
            raise ValueError("Case request_body must be a JSON object")
        return value


class EvaluationDatasetRow(EvaluationDatasetRowCreate, table=True):
    request_headers: dict[str, str] | None = Field(default=None, sa_column=Column(JSON))
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    dataset_id: uuid.UUID = Field(
        foreign_key="evaluationdataset.id", nullable=False, ondelete="CASCADE"
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_column=Column(DateTime(timezone=True))
    )


class EvaluationRequestDocument(SQLModel):
    headers: dict[str, str]
    body: dict[str, Any]
    actual_output_json_pointer: str | None

    @field_validator("actual_output_json_pointer")
    @classmethod
    def validate_json_pointer(cls, value: str | None) -> str | None:
        return validate_actual_output_path(value)


class SingleTurnDatasetCaseDocument(SQLModel):
    input: str
    request: EvaluationRequestDocument
    expected_output: str


class SingleTurnDatasetDocument(SQLModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=500)
    test_type: Literal["single_turn"]
    endpoint_id: uuid.UUID
    metric_profile_id: uuid.UUID | None = None
    threshold: float = Field(default=70, ge=0, le=100)
    evaluator: Literal["deepeval", "local"] = "deepeval"
    cases: list[SingleTurnDatasetCaseDocument] = Field(max_length=1000)

    @model_validator(mode="after")
    def validate_metric_profile(self) -> SingleTurnDatasetDocument:
        if self.evaluator == "deepeval" and self.metric_profile_id is None:
            raise ValueError("DeepEval datasets require metric_profile_id")
        return self


class EvaluationScheduleType(StrEnum):
    INTERVAL = "interval"
    CRON = "cron"


class EvaluationScheduleTargetType(StrEnum):
    SINGLE_TURN = "single_turn"
    MULTI_TURN = "multi_turn"


class EvaluationScheduleBase(SQLModel):
    name: str = Field(min_length=1, max_length=255)
    schedule_type: EvaluationScheduleType = EvaluationScheduleType.INTERVAL
    interval_seconds: int | None = Field(default=None, ge=60, le=31_536_000)
    cron_expression: str | None = Field(default=None, min_length=5, max_length=100)
    timezone: str = Field(default="Asia/Seoul", min_length=1, max_length=100)
    is_active: bool = True

    @model_validator(mode="after")
    def validate_schedule_configuration(self) -> EvaluationScheduleBase:
        from app.cron_schedule import parse_cron_expression, validate_timezone

        validate_timezone(self.timezone)
        if self.schedule_type == EvaluationScheduleType.INTERVAL:
            if self.interval_seconds is None:
                raise ValueError("Interval schedules require interval_seconds")
            if self.cron_expression is not None:
                raise ValueError("Interval schedules cannot define cron_expression")
        else:
            if not self.cron_expression:
                raise ValueError("Cron schedules require cron_expression")
            parse_cron_expression(self.cron_expression)
            if self.interval_seconds is not None:
                raise ValueError("Cron schedules cannot define interval_seconds")
        return self


class EvaluationDatasetScheduleCreate(EvaluationScheduleBase):
    next_run_at: datetime | None = None
    baseline_run_id: uuid.UUID | None = None


class EvaluationScheduleCreate(EvaluationScheduleBase):
    target_type: EvaluationScheduleTargetType
    target_id: uuid.UUID
    next_run_at: datetime | None = None
    baseline_run_id: uuid.UUID | None = None


class EvaluationScheduleUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    schedule_type: EvaluationScheduleType | None = None
    interval_seconds: int | None = Field(default=None, ge=60, le=31_536_000)
    cron_expression: str | None = Field(default=None, min_length=5, max_length=100)
    timezone: str | None = Field(default=None, min_length=1, max_length=100)
    is_active: bool | None = None
    next_run_at: datetime | None = None
    baseline_run_id: uuid.UUID | None = None


class EvaluationSchedule(SQLModel, table=True):
    name: str = Field(min_length=1, max_length=255)
    schedule_type: str = Field(default="interval", max_length=16)
    interval_seconds: int | None = Field(default=None, ge=60, le=31_536_000)
    cron_expression: str | None = Field(default=None, max_length=100)
    timezone: str = Field(default="Asia/Seoul", max_length=100)
    is_active: bool = True
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    dataset_id: uuid.UUID | None = Field(
        default=None, foreign_key="evaluationdataset.id", ondelete="CASCADE"
    )
    scenario_id: uuid.UUID | None = Field(
        default=None, foreign_key="evaluationscenario.id", ondelete="CASCADE"
    )
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    baseline_run_id: uuid.UUID | None = Field(
        default=None, foreign_key="evaluationrun.id", ondelete="SET NULL"
    )
    next_run_at: datetime = Field(
        default_factory=get_datetime_utc, sa_column=Column(DateTime(timezone=True))
    )
    last_enqueued_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_column=Column(DateTime(timezone=True))
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc, sa_column=Column(DateTime(timezone=True))
    )


class EvaluationSchedulePublic(EvaluationScheduleBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    owner_name: str | None = None
    target_type: EvaluationScheduleTargetType
    target_id: uuid.UUID
    target_name: str
    target_description: str | None = None
    dataset_id: uuid.UUID | None
    scenario_id: uuid.UUID | None
    baseline_run_id: uuid.UUID | None
    next_run_at: datetime
    last_enqueued_at: datetime | None
    created_at: datetime
    updated_at: datetime


class EvaluationSchedulesPublic(SQLModel):
    data: list[EvaluationSchedulePublic]
    count: int


class EvaluationJob(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    dataset_id: uuid.UUID | None = Field(
        default=None, foreign_key="evaluationdataset.id", ondelete="CASCADE"
    )
    scenario_id: uuid.UUID | None = Field(
        default=None, foreign_key="evaluationscenario.id", ondelete="CASCADE"
    )
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    baseline_run_id: uuid.UUID | None = Field(
        default=None, foreign_key="evaluationrun.id", ondelete="SET NULL"
    )
    schedule_id: uuid.UUID | None = Field(
        default=None, foreign_key="evaluationschedule.id", ondelete="SET NULL"
    )
    metric_profile_id: uuid.UUID | None = Field(
        default=None, foreign_key="evaluationmetricprofile.id", ondelete="SET NULL"
    )
    status: str = Field(default="queued", min_length=3, max_length=32)
    scheduled_for: datetime = Field(
        default_factory=get_datetime_utc, sa_column=Column(DateTime(timezone=True))
    )
    available_at: datetime = Field(
        default_factory=get_datetime_utc, sa_column=Column(DateTime(timezone=True))
    )
    attempt: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=3, ge=1, le=10)
    claimed_by: str | None = Field(default=None, max_length=255)
    lease_expires_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
    heartbeat_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
    error: str | None = Field(default=None, max_length=2000)
    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_column=Column(DateTime(timezone=True))
    )
    started_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
    finished_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )


class EvaluationJobPublic(SQLModel):
    id: uuid.UUID
    dataset_id: uuid.UUID | None
    scenario_id: uuid.UUID | None
    baseline_run_id: uuid.UUID | None
    schedule_id: uuid.UUID | None
    metric_profile_id: uuid.UUID | None
    status: str
    scheduled_for: datetime
    attempt: int
    max_attempts: int
    error: str | None
    run_id: uuid.UUID | None = None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class EvaluationEndpointBase(SQLModel):
    name: str = Field(min_length=1, max_length=255)
    base_url: str = Field(min_length=1, max_length=2048)
    is_active: bool = True


class EvaluationEndpointCreate(EvaluationEndpointBase):
    headers: dict[str, str] = Field(default_factory=dict)


class EvaluationEndpointUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    base_url: str | None = Field(default=None, min_length=1, max_length=2048)
    is_active: bool | None = None
    headers: dict[str, str] | None = None


class EvaluationEndpoint(EvaluationEndpointBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # Never return this column to callers.  It contains encrypted JSON rather
    # than a plaintext Authorization/API key.
    encrypted_headers: str = Field(default="")
    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_column=Column(DateTime(timezone=True))
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc, sa_column=Column(DateTime(timezone=True))
    )


class EvaluationEndpointPublic(EvaluationEndpointBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    headers_configured: bool = False


class EvaluationEndpointsPublic(SQLModel):
    data: list[EvaluationEndpointPublic]
    count: int


class EvaluationComparisonMode(StrEnum):
    ABSOLUTE = "absolute"
    RELATIVE = "relative"
    HYBRID = "hybrid"


class EvaluationComparisonCreate(SQLModel):
    endpoint_a_id: uuid.UUID
    endpoint_b_id: uuid.UUID
    metric_profile_id: uuid.UUID
    comparison_mode: EvaluationComparisonMode = EvaluationComparisonMode.HYBRID

    @model_validator(mode="after")
    def endpoints_must_differ(self) -> EvaluationComparisonCreate:
        if self.endpoint_a_id == self.endpoint_b_id:
            raise ValueError("comparison endpoints must be different")
        return self


class EvaluationComparison(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    evaluation_mode: str = Field(max_length=32)
    dataset_id: uuid.UUID | None = Field(
        default=None, foreign_key="evaluationdataset.id", ondelete="CASCADE"
    )
    scenario_id: uuid.UUID | None = Field(
        default=None, foreign_key="evaluationscenario.id", ondelete="CASCADE"
    )
    endpoint_a_id: uuid.UUID = Field(
        foreign_key="evaluationendpoint.id", nullable=False, ondelete="RESTRICT"
    )
    endpoint_b_id: uuid.UUID = Field(
        foreign_key="evaluationendpoint.id", nullable=False, ondelete="RESTRICT"
    )
    metric_profile_id: uuid.UUID | None = Field(
        default=None, foreign_key="evaluationmetricprofile.id", ondelete="SET NULL"
    )
    metric_profile_version: int | None = None
    metric_profile_snapshot: dict[str, object] | None = Field(
        default=None, sa_column=Column(JSON)
    )
    comparison_mode: str = Field(max_length=16)
    status: str = Field(default="running", max_length=16)
    run_a_id: uuid.UUID | None = Field(
        default=None, foreign_key="evaluationrun.id", ondelete="SET NULL"
    )
    run_b_id: uuid.UUID | None = Field(
        default=None, foreign_key="evaluationrun.id", ondelete="SET NULL"
    )
    scenario_run_a_id: uuid.UUID | None = Field(
        default=None, foreign_key="evaluationscenariorun.id", ondelete="SET NULL"
    )
    scenario_run_b_id: uuid.UUID | None = Field(
        default=None, foreign_key="evaluationscenariorun.id", ondelete="SET NULL"
    )
    comparable_count: int = 0
    winner_a_count: int = 0
    winner_b_count: int = 0
    tie_count: int = 0
    results: list[dict[str, object]] = Field(
        default_factory=list, sa_column=Column(JSON)
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_column=Column(DateTime(timezone=True))
    )


class EvaluationComparisonPublic(SQLModel):
    id: uuid.UUID
    evaluation_mode: EvaluationMode
    dataset_id: uuid.UUID | None
    scenario_id: uuid.UUID | None
    endpoint_a_id: uuid.UUID
    endpoint_b_id: uuid.UUID
    metric_profile_id: uuid.UUID | None
    metric_profile_version: int | None
    comparison_mode: EvaluationComparisonMode
    status: str
    run_a_id: uuid.UUID | None
    run_b_id: uuid.UUID | None
    scenario_run_a_id: uuid.UUID | None
    scenario_run_b_id: uuid.UUID | None
    comparable_count: int
    winner_a_count: int
    winner_b_count: int
    tie_count: int
    results: list[dict[str, object]]
    created_at: datetime


class EvaluationComparisonsPublic(SQLModel):
    data: list[EvaluationComparisonPublic]
    count: int


class EvaluationDatasetRowPublic(EvaluationDatasetRowCreate):
    id: uuid.UUID
    dataset_id: uuid.UUID
    created_at: datetime


class EvaluationDatasetRowsPublic(SQLModel):
    data: list[EvaluationDatasetRowPublic]
    count: int


class EvaluationRun(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    dataset_id: uuid.UUID = Field(
        foreign_key="evaluationdataset.id", nullable=False, ondelete="CASCADE"
    )
    baseline_run_id: uuid.UUID | None = Field(
        default=None, foreign_key="evaluationrun.id", ondelete="SET NULL"
    )
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    evaluator: str = Field(default="deterministic-baseline-v1", max_length=100)
    job_id: uuid.UUID | None = Field(
        default=None, foreign_key="evaluationjob.id", ondelete="SET NULL"
    )
    comparison_group_id: uuid.UUID | None = Field(default=None, index=True)
    metric_profile_id: uuid.UUID | None = Field(
        default=None, foreign_key="evaluationmetricprofile.id", ondelete="SET NULL"
    )
    metric_profile_version: int | None = None
    metric_profile_snapshot: dict[str, object] | None = Field(
        default=None, sa_column=Column(JSON)
    )
    total: int = 0
    passed: int = 0
    failed: int = 0
    pass_rate: float = 0
    average_score: float = Field(default=0, sa_type=Numeric)
    geval_available: bool = False
    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_column=Column(DateTime(timezone=True))
    )


class EvaluationRunRow(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    run_id: uuid.UUID = Field(
        foreign_key="evaluationrun.id", nullable=False, ondelete="CASCADE"
    )
    dataset_row_id: uuid.UUID | None = Field(
        default=None, foreign_key="evaluationdatasetrow.id", ondelete="SET NULL"
    )
    input: str
    expected_output: str
    actual_output: str = ""
    response_status: int | None = None
    response_body: str | None = None
    score: float | None = Field(default=None, sa_type=Numeric)
    passed: bool = False
    metrics: list[dict[str, object]] = Field(
        default_factory=list, sa_column=Column(JSON)
    )
    error: str | None = Field(default=None, max_length=1000)


class EvaluationRunMetricResult(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    run_row_id: uuid.UUID = Field(
        foreign_key="evaluationrunrow.id", nullable=False, ondelete="CASCADE"
    )
    metric_key: str = Field(min_length=2, max_length=64)
    display_name: str = Field(min_length=1, max_length=100)
    score: float = Field(ge=0, le=100, sa_type=Numeric)
    raw_score_ratio: float | None = Field(default=None, ge=0, le=1)
    score_direction: str = Field(default="higher_is_better", max_length=32)
    weight_percent: int = Field(ge=1, le=100)
    weighted_score: float = Field(ge=0, le=100, sa_type=Numeric)
    reason: str | None = Field(default=None, max_length=2000)
    error: str | None = Field(default=None, max_length=1000)


class EvaluationScenarioBase(SQLModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=500)
    endpoint_id: uuid.UUID = Field(
        foreign_key="evaluationendpoint.id", nullable=False, ondelete="RESTRICT"
    )
    threshold: float = Field(default=70, ge=0, le=100, sa_type=Numeric)
    metric_profile_id: uuid.UUID | None = Field(
        default=None, foreign_key="evaluationmetricprofile.id", ondelete="SET NULL"
    )
    evaluator: str = Field(default="deepeval", max_length=32)


class EvaluationScenarioTurnCreate(SQLModel):
    identifier: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=1, max_length=2048)
    headers: dict[str, str] = Field(default_factory=dict)
    body_template: str = Field(default="{}")
    response_path: str | None = Field(default=None, max_length=500)
    expected_output: str = ""

    @field_validator("response_path")
    @classmethod
    def validate_response_path(cls, value: str | None) -> str | None:
        return validate_actual_output_path(value)


class MultiTurnRequestDocument(SQLModel):
    url: str = Field(min_length=1, max_length=2048)
    headers: dict[str, str]
    body: dict[str, Any]
    actual_output_json_pointer: str | None

    @field_validator("actual_output_json_pointer")
    @classmethod
    def validate_json_pointer(cls, value: str | None) -> str | None:
        return validate_actual_output_path(value)


class MultiTurnDatasetCaseDocument(SQLModel):
    identifier: str = Field(min_length=1, max_length=100)
    request: MultiTurnRequestDocument
    expected_output: str


class MultiTurnDatasetDocument(SQLModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=500)
    test_type: Literal["multi_turn"]
    endpoint_id: uuid.UUID
    threshold: float = Field(default=70, ge=0, le=100)
    metric_profile_id: uuid.UUID | None = None
    evaluator: Literal["deepeval", "local"] = "deepeval"
    cases: list[MultiTurnDatasetCaseDocument] = Field(min_length=1, max_length=100)


class EvaluationScenarioCreate(SQLModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=500)
    threshold: float = Field(default=70, ge=0, le=100)
    metric_profile_id: uuid.UUID | None = None
    evaluator: str = Field(default="deepeval", max_length=32)
    test_type: Literal["multi_turn"] = "multi_turn"
    # Accept an omitted or blank editor value so the route can return the same
    # actionable error used for every missing managed endpoint.
    endpoint_id: uuid.UUID | None = None
    turns: list[EvaluationScenarioTurnCreate] = Field(min_length=1, max_length=100)

    @field_validator("endpoint_id", mode="before")
    @classmethod
    def empty_endpoint_id_is_missing(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value


class EvaluationScenarioUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=500)
    endpoint_id: uuid.UUID | None = None
    threshold: float | None = Field(default=None, ge=0, le=100)
    metric_profile_id: uuid.UUID | None = None
    evaluator: str | None = Field(default=None, max_length=32)
    turns: list[EvaluationScenarioTurnCreate] | None = Field(
        default=None, max_length=100
    )


class EvaluationScenario(EvaluationScenarioBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    created_by_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", nullable=True, ondelete="SET NULL"
    )
    updated_by_id: uuid.UUID | None = Field(
        default=None, foreign_key="user.id", nullable=True, ondelete="SET NULL"
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_column=Column(DateTime(timezone=True))
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc, sa_column=Column(DateTime(timezone=True))
    )


class EvaluationScenarioTurn(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    scenario_id: uuid.UUID = Field(
        foreign_key="evaluationscenario.id", nullable=False, ondelete="CASCADE"
    )
    position: int
    identifier: str = Field(max_length=100)
    url: str = Field(max_length=2048)
    # Kept only to satisfy the existing database schema; all calls use POST.
    method: str = Field(default="POST", max_length=10)
    encrypted_headers: str = Field(default="")
    body_template: str
    response_path: str | None = Field(default=None, max_length=500)
    expected_output: str = ""


class EvaluationScenarioTurnPublic(SQLModel):
    id: uuid.UUID
    position: int
    identifier: str
    url: str
    headers_configured: bool = False
    body_template: str
    response_path: str | None
    expected_output: str


class EvaluationScenarioTurnsPublic(SQLModel):
    data: list[EvaluationScenarioTurnPublic]
    count: int


class EvaluationScenarioPublic(EvaluationScenarioBase):
    test_type: Literal["multi_turn"]
    evaluation_type: Literal["multi_turn"]
    id: uuid.UUID
    owner_id: uuid.UUID
    created_by_id: uuid.UUID | None
    updated_by_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    turn_count: int = 0
    turns: list[EvaluationScenarioTurnPublic] = Field(default_factory=list)


class EvaluationScenariosPublic(SQLModel):
    data: list[EvaluationScenarioPublic]
    count: int


class EvaluationScenarioRun(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    scenario_id: uuid.UUID = Field(
        foreign_key="evaluationscenario.id", nullable=False, ondelete="CASCADE"
    )
    baseline_run_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="evaluationscenariorun.id",
        ondelete="SET NULL",
    )
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    job_id: uuid.UUID | None = Field(
        default=None, foreign_key="evaluationjob.id", ondelete="SET NULL"
    )
    comparison_group_id: uuid.UUID | None = Field(default=None, index=True)
    metric_profile_id: uuid.UUID | None = Field(
        default=None, foreign_key="evaluationmetricprofile.id", ondelete="SET NULL"
    )
    metric_profile_version: int | None = None
    metric_profile_snapshot: dict[str, object] | None = Field(
        default=None, sa_column=Column(JSON)
    )
    metrics: list[dict[str, object]] = Field(
        default_factory=list, sa_column=Column(JSON)
    )
    total: int = 0
    passed: int = 0
    failed: int = 0
    turn_average_score: float = Field(default=0, sa_type=Numeric)
    overall_score: float = Field(default=0, sa_type=Numeric)
    overall_passed: bool = False
    overall_reason: str | None = None
    # Kept for clients created before the multi-turn result was split into
    # turn, conversation, and overall scores. It mirrors overall_score.
    average_score: float = Field(default=0, sa_type=Numeric)
    evaluator: str = Field(default="deepeval", max_length=32)
    geval_score: float | None = Field(default=None, sa_type=Numeric)
    geval_reason: str | None = None
    error: str | None = Field(default=None, max_length=1000)
    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_column=Column(DateTime(timezone=True))
    )


class EvaluationScenarioRunTurn(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    run_id: uuid.UUID = Field(
        foreign_key="evaluationscenariorun.id", nullable=False, ondelete="CASCADE"
    )
    scenario_turn_id: uuid.UUID | None = Field(
        default=None, foreign_key="evaluationscenarioturn.id", ondelete="SET NULL"
    )
    position: int
    identifier: str = Field(max_length=100)
    request_body: str = ""
    actual_output: str = ""
    expected_output: str = ""
    response_status: int | None = None
    response_body: str | None = None
    score: float = Field(default=0, sa_type=Numeric)
    passed: bool = False
    reason: str | None = None
    error: str | None = Field(default=None, max_length=1000)


class EvaluationDatasetPublic(SQLModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_by_id: uuid.UUID | None
    updated_by_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    name: str
    description: str | None
    evaluation_type: Literal["single_turn"]
    test_type: Literal["single_turn"]
    endpoint_id: uuid.UUID | None
    metric_profile_id: uuid.UUID | None
    body_template: str
    response_path: str | None
    threshold: float
    evaluator: str
    row_count: int = 0
    rows: list[EvaluationDatasetRowPublic] = Field(default_factory=list)


class EvaluationDatasetsPublic(SQLModel):
    data: list[EvaluationDatasetPublic]
    count: int


class EvaluationDatasetImportResult(SQLModel):
    imported: int
    row_count: int


# Generic message
class Message(SQLModel):
    message: str


# JSON payload containing access token
class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"


# Contents of JWT token
class TokenPayload(SQLModel):
    sub: str | None = None


class NewPassword(SQLModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)
