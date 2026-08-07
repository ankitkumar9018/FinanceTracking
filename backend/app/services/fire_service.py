"""FIRE / retirement projection service.

Pure math — no database or external calls. Projects an investment corpus
year-by-year with monthly compounding and an optional annual step-up on the
monthly contribution, and works out when (if ever) the corpus reaches the
"FIRE number" (the corpus that sustains the target annual expenses at a given
safe withdrawal rate).

:func:`project_monthly` is the single compounding engine shared with
``goal_service.sip_projection`` — both used to carry their own copies of the
identical month-by-month loop.
"""

from __future__ import annotations


def project_monthly(
    principal: float,
    monthly_contribution: float,
    annual_return_pct: float,
    years: int,
    *,
    step_up_pct: float = 0.0,
    stop_at: float | None = None,
) -> dict:
    """Month-by-month compounding projection with an annual SIP step-up.

    Conventions (shared by the FIRE and SIP-projection callers):

    - every month the corpus first compounds at ``annual_return_pct / 12``,
      then the monthly contribution is added (end-of-month contribution);
    - after each completed year the monthly contribution steps up by
      ``step_up_pct`` percent;
    - ``principal`` counts toward ``invested``.

    When ``stop_at`` is given the projection stops early at the end of the
    first year whose corpus reaches it (checked before that year's step-up);
    a ``principal`` already at/above ``stop_at`` stops at year 0.

    Returns ``{final_corpus, invested, stop_year, yearly}`` where ``yearly``
    is a list of unrounded ``{year, corpus, invested}`` snapshots (year 0 =
    the starting state) and ``stop_year`` is ``None`` when ``stop_at`` was
    never reached (or not given).
    """
    corpus = float(principal)
    monthly = float(monthly_contribution)
    years = max(int(years), 0)

    monthly_rate = annual_return_pct / 100.0 / 12.0
    step_up = step_up_pct / 100.0

    invested = corpus
    yearly: list[dict] = [{"year": 0, "corpus": corpus, "invested": invested}]
    stop_year: int | None = None

    if stop_at is not None and corpus >= stop_at:
        stop_year = 0
    else:
        for year in range(1, years + 1):
            for _ in range(12):
                corpus = corpus * (1 + monthly_rate) + monthly
                invested += monthly

            yearly.append({"year": year, "corpus": corpus, "invested": invested})

            if stop_at is not None and corpus >= stop_at:
                stop_year = year
                break

            # Step up next year's monthly contribution.
            monthly *= 1 + step_up

    return {
        "final_corpus": corpus,
        "invested": invested,
        "stop_year": stop_year,
        "yearly": yearly,
    }


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
    withdrawal_fraction = withdrawal_rate_pct / 100.0
    fire_number = (
        float(annual_expenses) / withdrawal_fraction
        if withdrawal_fraction > 0
        else None
    )

    result = project_monthly(
        current_net_worth,
        monthly_contribution,
        annual_return_pct,
        max_years,
        step_up_pct=step_up_pct,
        stop_at=fire_number,
    )

    years_to_fire = result["stop_year"]

    return {
        "fire_number": round(fire_number, 2) if fire_number is not None else None,
        "years_to_fire": years_to_fire,
        "achieved": years_to_fire is not None,
        "final_corpus": round(result["final_corpus"], 2),
        "projection": [
            {
                "year": snap["year"],
                "corpus": round(snap["corpus"], 2),
                "invested": round(snap["invested"], 2),
            }
            for snap in result["yearly"]
        ],
    }
