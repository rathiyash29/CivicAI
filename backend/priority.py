# MOCK PRIORITY ENGINE - Factor values are currently mock data.
# In production, these will come from real datasets/database/analytics.

from typing import Literal


def calculate_priority(
    citizen_demand: float,
    infrastructure_gap: float,
    population_impact: float,
    urgency: float,
    investment_gap: float,
) -> dict:
    """
    Calculate priority score based on weighted factors.

    Weights:
    - Citizen demand: 30%
    - Infrastructure gap: 25%
    - Population impact: 20%
    - Urgency: 15%
    - Investment gap: 10%
    """
    # Validate inputs are within 0-100 range
    for name, value in [
        ("citizen_demand", citizen_demand),
        ("infrastructure_gap", infrastructure_gap),
        ("population_impact", population_impact),
        ("urgency", urgency),
        ("investment_gap", investment_gap),
    ]:
        if not 0 <= value <= 100:
            raise ValueError(f"{name} must be between 0 and 100")

    priority_score = round(
        citizen_demand * 0.30
        + infrastructure_gap * 0.25
        + population_impact * 0.20
        + urgency * 0.15
        + investment_gap * 0.10,
        2,
    )

    if priority_score <= 39:
        priority_level: Literal["Low", "Medium", "High"] = "Low"
    elif priority_score <= 69:
        priority_level = "Medium"
    else:
        priority_level = "High"

    return {
        "priority_score": priority_score,
        "priority_level": priority_level,
        "factors": {
            "citizen_demand": citizen_demand,
            "infrastructure_gap": infrastructure_gap,
            "population_impact": population_impact,
            "urgency": urgency,
            "investment_gap": investment_gap,
        },
    }


def determine_factors_from_analysis(analysis: dict) -> dict:
    """
    Determine mock factor values based on AI analysis.
    This is a placeholder - in production, these would come from real data sources.
    """
    severity = analysis.get("severity", "Medium")
    urgency_level = analysis.get("urgency", "Medium")
    category = analysis.get("category", "Other")

    # Map severity/urgency to 0-100 scores
    severity_map = {"Low": 30, "Medium": 60, "High": 90}
    urgency_map = {"Low": 30, "Medium": 60, "High": 90}

    # Category-based infrastructure gap estimation
    category_infra_gap = {
        "Road Infrastructure": 75,
        "Water Supply": 85,
        "Electricity": 70,
        "Sanitation": 80,
        "Public Transport": 65,
        "Healthcare": 60,
        "Education": 55,
        "Other": 50,
    }

    # Category-based population impact estimation
    category_population_impact = {
        "Road Infrastructure": 70,
        "Water Supply": 90,
        "Electricity": 75,
        "Sanitation": 80,
        "Public Transport": 65,
        "Healthcare": 85,
        "Education": 60,
        "Other": 50,
    }

    # Category-based investment gap estimation
    category_investment_gap = {
        "Road Infrastructure": 60,
        "Water Supply": 70,
        "Electricity": 55,
        "Sanitation": 50,
        "Public Transport": 65,
        "Healthcare": 60,
        "Education": 50,
        "Other": 55,
    }

    # Citizen demand based on severity + urgency
    base_demand = (severity_map.get(severity, 50) + urgency_map.get(urgency_level, 50)) / 2

    return {
        "citizen_demand": round(base_demand),
        "infrastructure_gap": category_infra_gap.get(category, 50),
        "population_impact": category_population_impact.get(category, 50),
        "urgency": urgency_map.get(urgency_level, 50),
        "investment_gap": category_investment_gap.get(category, 50),
    }