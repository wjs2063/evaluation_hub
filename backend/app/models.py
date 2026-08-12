import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import EmailStr, field_validator, model_validator
from sqlalchemy import JSON, Column, DateTime
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
        sa_type=DateTime(timezone=True),  # type: ignore
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
        sa_type=DateTime(timezone=True),  # type: ignore
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


class EvaluationMetricDefinitionCreate(SQLModel):
    metric_type: EvaluationMetricType
    weight_percent: int = Field(ge=1, le=100)


class EvaluationMetricProfileBase(SQLModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=500)
    is_active: bool = True


class EvaluationMetricProfileCreate(EvaluationMetricProfileBase):
    metrics: list[EvaluationMetricDefinitionCreate] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def validate_metric_set(self) -> EvaluationMetricProfileCreate:
        keys = [metric.metric_type for metric in self.metrics]
        if len(keys) != len(set(keys)):
            raise ValueError("metric keys must be unique within a profile")
        if sum(metric.weight_percent for metric in self.metrics) != 100:
            raise ValueError("metric weights must add up to 100 percent")
        return self


class EvaluationMetricProfileUpdate(EvaluationMetricProfileCreate):
    pass


class EvaluationMetricProfile(EvaluationMetricProfileBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    version: int = Field(default=1, ge=1)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
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


class EvaluationMetricDefinitionPublic(EvaluationMetricDefinitionCreate):
    id: uuid.UUID
    position: int
    display_name: str
    description: str
    required_fields: list[str]
    score_direction: str
    uses_llm: bool
    docs_url: str


class EvaluationMetricCatalogItem(SQLModel):
    metric_type: EvaluationMetricType
    display_name: str
    description: str
    required_fields: list[str]
    score_direction: str
    uses_llm: bool
    docs_url: str


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
    body_template: str = Field(default="{{input}}")
    response_path: str | None = Field(default=None, max_length=500)
    threshold: float = Field(default=0.7, ge=0, le=1)
    evaluator: str = Field(default="deepeval", max_length=32)


class EvaluationDatasetRowCreate(SQLModel):
    input: str
    expected_output: str


class EvaluationDatasetCreate(EvaluationDatasetBase):
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
    threshold: float | None = Field(default=None, ge=0, le=1)
    evaluator: str | None = Field(default=None, max_length=32)


class EvaluationDataset(EvaluationDatasetBase, table=True):
    # The database column is retained for existing installations. Requests are
    # intentionally POST-only, so it is no longer part of the public API.
    method: str = Field(default="POST", max_length=10)
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )


class EvaluationDatasetRowUpdate(EvaluationDatasetRowCreate):
    pass


class EvaluationDatasetRow(EvaluationDatasetRowCreate, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    dataset_id: uuid.UUID = Field(
        foreign_key="evaluationdataset.id", nullable=False, ondelete="CASCADE"
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )


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
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )


class EvaluationEndpointPublic(EvaluationEndpointBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    headers_configured: bool = False


class EvaluationEndpointsPublic(SQLModel):
    data: list[EvaluationEndpointPublic]
    count: int


class EvaluationDatasetRowPublic(EvaluationDatasetRowCreate):
    id: uuid.UUID
    dataset_id: uuid.UUID
    created_at: datetime


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
    average_score: float = 0
    geval_available: bool = False
    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
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
    score: float = 0
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
    score: float = Field(ge=0, le=1)
    raw_score: float | None = Field(default=None, ge=0, le=1)
    score_direction: str = Field(default="higher_is_better", max_length=32)
    weight_percent: int = Field(ge=1, le=100)
    weighted_score: float = Field(ge=0, le=1)
    reason: str | None = Field(default=None, max_length=2000)
    error: str | None = Field(default=None, max_length=1000)


class EvaluationScenarioBase(SQLModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=500)
    endpoint_id: uuid.UUID = Field(
        foreign_key="evaluationendpoint.id", nullable=False, ondelete="RESTRICT"
    )
    threshold: float = Field(default=0.7, ge=0, le=1)
    evaluator: str = Field(default="deepeval", max_length=32)


class EvaluationScenarioTurnCreate(SQLModel):
    identifier: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=1, max_length=2048)
    headers: dict[str, str] = Field(default_factory=dict)
    body_template: str = Field(default="{}")
    response_path: str | None = Field(default=None, max_length=500)
    expected_output: str = ""


class EvaluationScenarioCreate(EvaluationScenarioBase):
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
    threshold: float | None = Field(default=None, ge=0, le=1)
    evaluator: str | None = Field(default=None, max_length=32)
    turns: list[EvaluationScenarioTurnCreate] | None = Field(
        default=None, max_length=100
    )


class EvaluationScenario(EvaluationScenarioBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE"
    )
    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
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


class EvaluationScenarioPublic(EvaluationScenarioBase):
    id: uuid.UUID
    owner_id: uuid.UUID
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
    total: int = 0
    passed: int = 0
    failed: int = 0
    turn_average_score: float = 0
    overall_score: float = 0
    overall_passed: bool = False
    overall_reason: str | None = None
    # Kept for clients created before the multi-turn result was split into
    # turn, conversation, and overall scores. It mirrors overall_score.
    average_score: float = 0
    evaluator: str = Field(default="deepeval", max_length=32)
    geval_score: float | None = None
    geval_reason: str | None = None
    error: str | None = Field(default=None, max_length=1000)
    created_at: datetime = Field(
        default_factory=get_datetime_utc, sa_type=DateTime(timezone=True)
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
    score: float = 0
    passed: bool = False
    reason: str | None = None
    error: str | None = Field(default=None, max_length=1000)


class EvaluationDatasetPublic(SQLModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    name: str
    description: str | None
    evaluation_type: str
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
