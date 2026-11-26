"""Summary statistics computed in SQL (GROUP BY), never by loading rows into Python.

Amounts in different currencies are never added together: every total is per currency.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Transaction, User
from app.modules.transactions.service import TransactionFilters, apply_filters


def summary(db: Session, user: User, filters: TransactionFilters) -> dict:
    count = func.count()
    total = func.sum(Transaction.amount)

    totals_stmt = apply_filters(
        select(
            Transaction.currency,
            count,
            total,
            func.round(func.avg(Transaction.amount), 2),
            func.min(Transaction.amount),
            func.max(Transaction.amount),
        ),
        user,
        filters,
    ).group_by(Transaction.currency)

    category_stmt = apply_filters(
        select(Transaction.category, Transaction.currency, count, total), user, filters
    ).group_by(Transaction.category, Transaction.currency)

    # Months are cut in UTC, matching how timestamps are stored.
    month = func.to_char(func.timezone("UTC", Transaction.occurred_at), "YYYY-MM")
    month_stmt = apply_filters(
        select(month.label("month"), Transaction.currency, count, total), user, filters
    ).group_by(month, Transaction.currency)

    return {
        "totals": [
            {"currency": c, "count": n, "total": t, "average": a, "min": lo, "max": hi}
            for c, n, t, a, lo, hi in db.execute(totals_stmt.order_by(Transaction.currency))
        ],
        "by_category": [
            {"category": cat, "currency": c, "count": n, "total": t}
            for cat, c, n, t in db.execute(category_stmt.order_by(total.desc()))
        ],
        "by_month": [
            {"month": m, "currency": c, "count": n, "total": t}
            for m, c, n, t in db.execute(month_stmt.order_by(month, Transaction.currency))
        ],
    }
