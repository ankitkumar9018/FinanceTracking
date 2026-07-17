"""FIRE / retirement projection service.

Pure math — no database or external calls. Projects an investment corpus
year-by-year with monthly compounding and an optional annual step-up on the
monthly contribution, and works out when (if ever) the corpus reaches the
"FIRE number" (the corpus that sustains the target annual expenses at a given
safe withdrawal rate).
"""

from __future__ import annotations


def compute_fire(
    current_net_worth: float,
    monthly_contribution: float,
    annual_return_pct: float,
    annual_expenses: float,
    withdrawal_rate_pct: float = 4.0,
    step_up_pct: float = 0.0,
    max_years: int = 60,
) -> dict:
    """Project a path to financial independence (FIRE).

    Args:
        current_net_worth: Starting corpus.
        monthly_contribution: Amount invested every month (year 1).
        annual_return_pct: Expected annual return, e.g. ``12`` for 12%.
            Compounded monthly at ``annual_return_pct / 12``.
        annual_expenses: Target yearly spending in retirement.
        withdrawal_rate_pct: Safe withdrawal rate, e.g. ``4`` for the 4% rule.
        step_up_pct: Percentage increase applied to the monthly contribution
            at the start of every subsequent year (SIP step-up).
        max_years: Maximum number of years to project.

    Returns:
        dict with ``fire_number``, ``years_to_fire`` (int | None), ``achieved``
        (bool), ``final_corpus`` and a ``projection`` list of
        ``{year, corpus, invested}`` snapshots (year 0 = today).
    """
    current_net_worth = float(current_net_worth)
    monthly_contribution = float(monthly_contribution)
    annual_expenses = float(annual_expenses)
    max_years = max(int(max_years), 0)

    monthly_rate = annual_return_pct / 100.0 / 12.0
    step_up = step_up_pct / 100.0

    withdrawal_fraction = withdrawal_rate_pct / 100.0
    fire_number = (
        annual_expenses / withdrawal_fraction if withdrawal_fraction > 0 else None
    )

    corpus = current_net_worth
    invested = current_net_worth
    monthly = monthly_contribution

    projection: list[dict] = [
        {"year": 0, "corpus": round(corpus, 2), "invested": round(invested, 2)}
    ]

    years_to_fire: int | None = None
    achieved = False

    # Already there before contributing anything?
    if fire_number is not None and corpus >= fire_number:
        years_to_fire = 0
        achieved = True
        return {
            "fire_number": round(fire_number, 2) if fire_number is not None else None,
            "years_to_fire": years_to_fire,
            "achieved": achieved,
            "final_corpus": round(corpus, 2),
            "projection": projection,
        }

    for year in range(1, max_years + 1):
        for _ in range(12):
            corpus = corpus * (1 + monthly_rate) + monthly
            invested += monthly

        projection.append(
            {"year": year, "corpus": round(corpus, 2), "invested": round(invested, 2)}
        )

        if fire_number is not None and corpus >= fire_number:
            years_to_fire = year
            achieved = True
            break

        # Step up next year's monthly contribution.
        monthly *= 1 + step_up

    return {
        "fire_number": round(fire_number, 2) if fire_number is not None else None,
        "years_to_fire": years_to_fire,
        "achieved": achieved,
        "final_corpus": round(corpus, 2),
        "projection": projection,
    }
