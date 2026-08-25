# src/state.py
from typing import TypedDict, Annotated, Sequence, Optional, Literal
import operator
from langchain_core.messages import BaseMessage


class NOCState(TypedDict):
    """Estado global compartido del NOC-MAS (Fase 5 - Orquestador)."""

    messages: Annotated[Sequence[BaseMessage], operator.add]

    incident_id: Optional[str]
    severity: Optional[Literal["P1", "P2", "P3", "P4"]]
    source_alert: Optional[dict]

    next_agent: Optional[str]

    requires_human_approval: bool
    human_decision: Optional[Literal["approved", "rejected", "pending"]]

    context: dict