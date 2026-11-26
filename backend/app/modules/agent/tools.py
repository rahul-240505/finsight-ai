"""The agent's tools (ADR-012): five read-only lookups plus `submit_report`.

Rules every tool follows:
* Arguments are validated by a Pydantic model with `extra="forbid"`; the model's raw output
  never reaches a query.
* Tools act as the investigating user, through the same services as the API, and only on
  the investigation's dataset. The dataset is fixed by the server, not chosen by the model,
  so the model can't widen its own scope.
* Results are plain JSON, capped in size, and remembered so the final report can be checked:
  a finding may only cite a transaction that a tool actually returned.
"""

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Dataset, RiskAssessment, Transaction, User
from app.modules.ml import registry
from app.modules.ml import service as risk
from app.modules.rag import service as rag
from app.modules.transactions import analytics
from app.modules.transactions.service import TransactionFilters
from app.services.llm import LLMProvider
from app.services.vector_store import QdrantStore


class ToolError(Exception):
    """A tool refused the call; the message is safe to show the model."""


@dataclass
class ToolContext:
    db: Session
    user: User
    dataset: Dataset
    llm: LLMProvider
    store: QdrantStore
    seen_transactions: dict[str, dict] = field(default_factory=dict)  # id -> evidence
    seen_policies: dict[str, dict] = field(default_factory=dict)  # "P1" -> passage


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoArgs(_Args):
    pass


class FlaggedArgs(_Args):
    limit: int = Field(default=10, ge=1, le=20, description="How many, highest risk first")


class TransactionArgs(_Args):
    transaction_id: uuid.UUID


class AccountArgs(_Args):
    account_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,64}$")
    limit: int = Field(default=20, ge=1, le=30)


class PolicyArgs(_Args):
    query: str = Field(min_length=3, max_length=300)


class Finding(_Args):
    transaction_id: uuid.UUID
    observation: str = Field(min_length=3, max_length=400)


class ReportArgs(_Args):
    summary: str = Field(min_length=10, max_length=1500)
    findings: list[Finding] = Field(default_factory=list, max_length=10)
    recommendation: str = Field(min_length=3, max_length=800)
    policy_refs: list[str] = Field(default_factory=list, max_length=5)


def _money(value: Decimal) -> str:
    return f"{value:.2f}"


def _evidence(tx: Transaction, assessment: RiskAssessment | None) -> dict:
    return {
        "transaction_id": str(tx.id),
        "account_id": tx.account_id,
        "occurred_at": tx.occurred_at.isoformat(),
        "amount": _money(tx.amount),
        "currency": tx.currency,
        "merchant": tx.merchant,
        "category": tx.category,
        "risk_score": round(assessment.risk_score, 4) if assessment else None,
        "flagged": assessment.is_flagged if assessment else None,
        "reasons": assessment.reasons if assessment else [],
    }


def _remember(ctx: ToolContext, items: list[dict]) -> list[dict]:
    for item in items:
        ctx.seen_transactions[item["transaction_id"]] = item
    return items


def _active_model_id(ctx: ToolContext) -> uuid.UUID | None:
    try:
        return registry.active_version(ctx.db, risk.MODEL_NAME).id
    except registry.NoActiveModel:
        return None


def _assessments(ctx: ToolContext, tx_ids: list[uuid.UUID]) -> dict:
    """The active model's assessment of each transaction (older model versions ignored)."""
    model_id = _active_model_id(ctx)
    if not tx_ids or model_id is None:
        return {}
    stmt = select(RiskAssessment).where(
        RiskAssessment.owner_id == ctx.user.id,
        RiskAssessment.model_version_id == model_id,
        RiskAssessment.transaction_id.in_(tx_ids),
    )
    return {a.transaction_id: a for a in ctx.db.scalars(stmt)}


def get_dataset_summary(ctx: ToolContext, _: NoArgs) -> dict:
    s = analytics.summary(ctx.db, ctx.user, TransactionFilters(dataset_id=ctx.dataset.id))
    model_id = _active_model_id(ctx)
    flagged = (
        ctx.db.scalar(
            select(func.count()).where(
                RiskAssessment.owner_id == ctx.user.id,
                RiskAssessment.dataset_id == ctx.dataset.id,
                RiskAssessment.model_version_id == model_id,
                RiskAssessment.is_flagged,
            )
        )
        if model_id
        else None
    )
    return {
        "dataset": ctx.dataset.name,
        "rows": ctx.dataset.row_count,
        "flagged_assessments": flagged,
        "totals": s["totals"],
        "top_categories": s["by_category"][:5],
    }


def list_flagged_transactions(ctx: ToolContext, args: FlaggedArgs) -> dict:
    rows = risk.list_assessments(ctx.db, ctx.user, ctx.dataset.id, True, args.limit, 0)
    if not rows:
        return {"items": [], "note": "No flagged transactions. The dataset may not be scored."}
    return {"items": _remember(ctx, [_evidence(t, a) for a, t in rows])}


def get_transaction(ctx: ToolContext, args: TransactionArgs) -> dict:
    tx = ctx.db.scalar(
        select(Transaction).where(
            Transaction.id == args.transaction_id,
            Transaction.owner_id == ctx.user.id,
            Transaction.dataset_id == ctx.dataset.id,
        )
    )
    if tx is None:  # missing, someone else's, or outside this investigation's dataset
        raise ToolError("Transaction not found in this dataset.")
    assessment = _assessments(ctx, [tx.id]).get(tx.id)
    return _remember(ctx, [_evidence(tx, assessment)])[0]


def get_account_history(ctx: ToolContext, args: AccountArgs) -> dict:
    base = [
        Transaction.owner_id == ctx.user.id,
        Transaction.dataset_id == ctx.dataset.id,
        Transaction.account_id == args.account_id,
    ]
    stats = ctx.db.execute(
        select(func.count(), func.avg(Transaction.amount), func.max(Transaction.amount)).where(
            *base
        )
    ).one()
    if stats[0] == 0:
        raise ToolError("No transactions for this account in this dataset.")
    recent = list(
        ctx.db.scalars(
            select(Transaction)
            .where(*base)
            .order_by(Transaction.occurred_at.desc(), Transaction.id.desc())
            .limit(args.limit)
        )
    )
    assessments = _assessments(ctx, [t.id for t in recent])
    return {
        "account_id": args.account_id,
        "transactions_in_dataset": stats[0],
        "average_amount": _money(stats[1]),
        "max_amount": _money(stats[2]),
        "recent": _remember(ctx, [_evidence(t, assessments.get(t.id)) for t in recent]),
    }


def search_policies(ctx: ToolContext, args: PolicyArgs) -> dict:
    passages = rag.retrieve(ctx.db, ctx.user, ctx.llm, ctx.store, args.query, top_k=3)
    items = []
    for p in passages:
        ref = f"P{len(ctx.seen_policies) + 1}"
        ctx.seen_policies[ref] = {
            "id": ref,
            "document_id": str(p.document_id),
            "filename": p.filename,
            "page": p.page,
            "excerpt": p.text[:300],
        }
        items.append({"id": ref, "file": p.filename, "page": p.page, "text": p.text[:600]})
    return {"passages": items} if items else {"passages": [], "note": "No policy documents."}


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: type[_Args]
    run: Callable[[ToolContext, Any], dict] | None  # None: handled by the loop (submit_report)

    def schema(self) -> dict:
        params = self.args.model_json_schema()
        params.pop("title", None)
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": params},
        }


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in (
        Tool(
            "get_dataset_summary",
            "Totals per currency, top categories and the number of flagged transactions "
            "for the dataset under investigation.",
            NoArgs,
            get_dataset_summary,
        ),
        Tool(
            "list_flagged_transactions",
            "Transactions the risk model flagged as unusual, highest risk first, with reasons.",
            FlaggedArgs,
            list_flagged_transactions,
        ),
        Tool(
            "get_transaction",
            "One transaction of this dataset by id, with its risk score and reasons.",
            TransactionArgs,
            get_transaction,
        ),
        Tool(
            "get_account_history",
            "Count, average and maximum amount, and the most recent transactions of one "
            "account in this dataset.",
            AccountArgs,
            get_account_history,
        ),
        Tool(
            "search_policies",
            "Search the user's policy documents. Returns passages with ids (P1, P2, ...) "
            "to cite in the report.",
            PolicyArgs,
            search_policies,
        ),
        Tool(
            "submit_report",
            "Finish: submit the draft report. Each finding must use a transaction_id returned "
            "by a tool; policy_refs must be passage ids from search_policies.",
            ReportArgs,
            None,
        ),
    )
}
SCHEMAS = [t.schema() for t in TOOLS.values()]


def dump(result: dict, limit: int) -> str:
    """Compact JSON, cut to `limit` characters. '<' is escaped (still valid JSON), so text
    from the data can't open or close the <tool_result> fence around it."""
    text = json.dumps(result, default=_json_default, separators=(",", ":"))
    text = text.replace("<", "\\u003c")
    return text if len(text) <= limit else text[: limit - 20] + '..."[truncated]"'


def _json_default(value: object) -> str:
    if isinstance(value, Decimal | uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(type(value).__name__)
