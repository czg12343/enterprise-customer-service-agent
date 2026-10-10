from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from urllib.parse import urlparse

from pydantic import AwareDatetime, BaseModel, ConfigDict, EmailStr, Field, field_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


TicketCategory = Literal["product", "order", "logistics", "refund", "repair", "complaint", "other"]
TicketPriority = Literal["low", "normal", "high", "urgent"]
TicketStatus = Literal["pending", "processing", "waiting_customer", "resolved", "closed"]


class InputModel(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)


class UserCreate(InputModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_.-]+$")
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(InputModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(InputModel):
    refresh_token: str = Field(min_length=20, max_length=4096)


class UserOut(ORMModel):
    id: str
    username: str
    email: str
    role: str
    is_active: bool
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserOut


class ProductOut(ORMModel):
    id: str
    sku: str
    name: str
    category: str
    description: str
    price: Decimal
    stock: int
    locked_stock: int
    is_active: bool
    created_at: datetime


class ProductCreate(InputModel):
    sku: str = Field(min_length=2, max_length=40, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]+$")
    name: str = Field(min_length=2, max_length=120)
    category: str = Field(min_length=1, max_length=50)
    description: str = Field(default="", max_length=5000)
    price: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    stock: int = Field(default=0, ge=0, le=10_000_000, strict=True)
    is_active: bool = True

    @field_validator("sku")
    @classmethod
    def normalize_sku(cls, value: str) -> str:
        return value.upper()


class ProductUpdate(InputModel):
    sku: str | None = Field(default=None, min_length=2, max_length=40, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]+$")
    name: str | None = Field(default=None, min_length=2, max_length=120)
    category: str | None = Field(default=None, min_length=1, max_length=50)
    description: str | None = Field(default=None, max_length=5000)
    price: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    stock: int | None = Field(default=None, ge=0, le=10_000_000, strict=True)
    is_active: bool | None = None

    @field_validator("sku")
    @classmethod
    def normalize_sku(cls, value: str | None) -> str | None:
        return value.upper() if value else value


class OrderItemCreate(InputModel):
    product_id: str = Field(min_length=1, max_length=32)
    quantity: int = Field(ge=1, le=999, strict=True)


class OrderCreate(InputModel):
    customer_username: str = Field(min_length=1, max_length=50)
    order_no: str | None = Field(default=None, max_length=40, pattern=r"^[A-Z]{2,5}\d{6,35}$")
    payment_status: Literal["pending", "paid"] = "paid"
    items: list[OrderItemCreate] = Field(min_length=1, max_length=100)


class LogisticsUpdate(InputModel):
    carrier: str = Field(min_length=1, max_length=80)
    tracking_no: str = Field(min_length=1, max_length=80)
    status: Literal["shipped", "in_transit", "out_for_delivery", "delivered"]
    latest_event: str = Field(min_length=1, max_length=255)
    estimated_delivery: date | None = None
    delivered_at: AwareDatetime | None = None


class OrderItemOut(ORMModel):
    product_name: str
    quantity: int
    unit_price: Decimal


class LogisticsOut(ORMModel):
    carrier: str
    tracking_no: str
    status: str
    latest_event: str
    estimated_delivery: date | None
    delivered_at: datetime | None


class OrderOut(ORMModel):
    id: str
    order_no: str
    customer_username: str
    status: str
    payment_status: str
    shipping_status: str
    total_amount: Decimal
    created_at: datetime
    items: list[OrderItemOut]
    logistics: LogisticsOut | None = None


class TicketCreate(InputModel):
    order_no: str | None = Field(default=None, max_length=40)
    category: TicketCategory = "other"
    title: str = Field(min_length=2, max_length=160)
    description: str = Field(min_length=2, max_length=5000)
    priority: TicketPriority = "normal"


class TicketUpdate(InputModel):
    status: TicketStatus | None = None
    assignee_id: str | None = Field(default=None, max_length=32)
    result: str | None = Field(default=None, max_length=5000)


class RefundDecision(InputModel):
    action: Literal["complete", "reject"]
    result: str | None = Field(default=None, max_length=5000)


class TicketOut(ORMModel):
    id: str
    ticket_no: str
    user_id: str
    order_no: str | None
    category: str
    title: str
    description: str
    priority: str
    status: str
    assignee_id: str | None
    result: str | None
    created_at: datetime
    updated_at: datetime


class KnowledgeBaseCreate(InputModel):
    name: str = Field(min_length=2, max_length=100)
    description: str = ""
    visibility: Literal["public", "internal"] = "internal"


class KnowledgeAccessUpdate(InputModel):
    visibility: Literal["public", "internal"]


class KnowledgeBaseOut(ORMModel):
    id: str
    name: str
    description: str
    is_active: bool
    created_at: datetime
    document_count: int = 0
    chunk_count: int = 0
    visibility: str = "internal"


class DocumentOut(ORMModel):
    id: str
    knowledge_base_id: str
    filename: str
    file_type: str
    status: str
    chunk_count: int
    created_at: datetime


class DocumentChunkOut(ORMModel):
    id: str
    chunk_index: int
    content: str
    page_number: int | None
    section: str | None
    start_char: int
    end_char: int


class DocumentContentOut(DocumentOut):
    knowledge_base_name: str
    chunks: list[DocumentChunkOut] = Field(default_factory=list)


class ConversationCreate(InputModel):
    title: str = Field(default="新会话", min_length=1, max_length=120)


class ConversationOut(ORMModel):
    id: str
    title: str
    status: str
    created_at: datetime
    updated_at: datetime
    refund_state: dict = Field(default_factory=dict)


class ChatRequest(InputModel):
    content: str = Field(min_length=1, max_length=10000)


class SourceOut(BaseModel):
    document: str
    page: int | None = None
    section: str | None = None
    snippet: str
    score: float
    citation_id: int | None = None
    document_id: str | None = None
    chunk_id: str | None = None


class ToolCallOut(BaseModel):
    name: str
    arguments: dict = Field(default_factory=dict)
    status: str = "success"


class MessageOut(ORMModel):
    id: str
    conversation_id: str
    role: str
    content: str
    intent: str | None
    sources: list[SourceOut] = Field(default_factory=list)
    tool_calls: list[ToolCallOut] = Field(default_factory=list)
    feedback: int | None
    created_at: datetime


class FeedbackRequest(BaseModel):
    value: int = Field(ge=-1, le=1)


class HandoffConversationOut(BaseModel):
    id: str
    title: str
    status: str
    customer_name: str
    assignee_id: str | None = None
    latest_message: str
    updated_at: datetime


class DashboardStats(BaseModel):
    users: int
    orders: int
    open_tickets: int
    conversations: int
    knowledge_documents: int
    today_agent_runs: int


class LLMConfigUpdate(InputModel):
    base_url: str = Field(min_length=8, max_length=500)
    api_key: str | None = Field(default=None, max_length=4096)
    model: str = Field(min_length=1, max_length=200)
    enabled: bool = True
    clear_api_key: bool = False

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Base URL 必须是有效的 HTTP 或 HTTPS 地址")
        if parsed.username or parsed.password:
            raise ValueError("Base URL 不能包含用户名或密码")
        return value.rstrip("/")


class LLMConfigOut(BaseModel):
    base_url: str
    model: str
    enabled: bool
    ready: bool
    has_api_key: bool
    source: str


class LLMConnectionTestOut(BaseModel):
    success: bool
    message: str


class EvaluationToolOut(BaseModel):
    name: str
    status: str


class EvaluationCaseResultOut(BaseModel):
    key: str
    name: str
    query: str
    passed: bool
    actual_intent: str
    expected_intent: str
    intent_correct: bool
    answer_score: float
    citation_score: float | None
    tool_score: float
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int
    estimated_cost_usd: float
    answer: str
    sources: list[str] = Field(default_factory=list)
    tools: list[EvaluationToolOut] = Field(default_factory=list)
    error: str | None = None


class EvaluationRunOut(ORMModel):
    id: str
    status: str
    total_cases: int
    passed_cases: int
    answer_accuracy: float
    citation_accuracy: float
    tool_success_rate: float
    average_latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    estimated_cost_usd: float
    user_satisfaction: float | None
    results: list[EvaluationCaseResultOut] = Field(default_factory=list)
    created_at: datetime


class EvaluationOverviewOut(BaseModel):
    latest: EvaluationRunOut | None
    history: list[EvaluationRunOut] = Field(default_factory=list)
    user_satisfaction: float | None
    positive_feedback: int
    negative_feedback: int
