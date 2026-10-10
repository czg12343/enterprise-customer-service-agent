"""Validated decisions selecting only server-owned tools and workflows."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TOOLS = {
    "order": "query_order", "logistics": "query_logistics", "product": "search_products",
    "ticket": "ticket_workflow", "refund": "refund_workflow", "human": "handoff_workflow",
    "knowledge": "hybrid_retrieval", "general": "chat",
}


class RouteDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    intent: Literal["order", "logistics", "product", "ticket", "refund", "human", "knowledge", "general"]
    tool: Literal["query_order", "query_logistics", "search_products", "ticket_workflow", "refund_workflow", "handoff_workflow", "hybrid_retrieval", "chat"]
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    order_no: str | None = Field(default=None, max_length=40, pattern=r"^[A-Z]{2,5}\d{6,35}$")
    ticket_no: str | None = Field(default=None, max_length=40, pattern=r"^TK[A-Z0-9]{6,}$")
    product_keyword: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def matching_tool(self):
        if self.tool != TOOLS[self.intent]:
            raise ValueError("Tool does not match the declared intent")
        return self
