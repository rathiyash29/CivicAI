# MOCK HOTSPOT DATA - Replace with database complaint aggregation later.

from typing import Literal


# In-memory mock complaints dataset from Pune areas
MOCK_COMPLAINTS = [
    # Kothrud
    {"id": 1, "location": "Kothrud", "category": "Road Infrastructure", "severity": "High"},
    {"id": 2, "location": "Kothrud", "category": "Road Infrastructure", "severity": "High"},
    {"id": 3, "location": "Kothrud", "category": "Road Infrastructure", "severity": "Medium"},
    {"id": 4, "location": "Kothrud", "category": "Road Infrastructure", "severity": "High"},
    {"id": 5, "location": "Kothrud", "category": "Road Infrastructure", "severity": "Low"},
    {"id": 6, "location": "Kothrud", "category": "Road Infrastructure", "severity": "High"},
    {"id": 7, "location": "Kothrud", "category": "Water Supply", "severity": "Medium"},
    {"id": 8, "location": "Kothrud", "category": "Water Supply", "severity": "High"},
    {"id": 9, "location": "Kothrud", "category": "Water Supply", "severity": "Medium"},
    {"id": 10, "location": "Kothrud", "category": "Electricity", "severity": "Low"},
    {"id": 11, "location": "Kothrud", "category": "Electricity", "severity": "Medium"},
    {"id": 12, "location": "Kothrud", "category": "Sanitation", "severity": "High"},
    {"id": 13, "location": "Kothrud", "category": "Sanitation", "severity": "Medium"},

    # Hadapsar
    {"id": 14, "location": "Hadapsar", "category": "Road Infrastructure", "severity": "High"},
    {"id": 15, "location": "Hadapsar", "category": "Road Infrastructure", "severity": "High"},
    {"id": 16, "location": "Hadapsar", "category": "Road Infrastructure", "severity": "Medium"},
    {"id": 17, "location": "Hadapsar", "category": "Road Infrastructure", "severity": "High"},
    {"id": 18, "location": "Hadapsar", "category": "Water Supply", "severity": "High"},
    {"id": 19, "location": "Hadapsar", "category": "Water Supply", "severity": "High"},
    {"id": 20, "location": "Hadapsar", "category": "Water Supply", "severity": "Medium"},
    {"id": 21, "location": "Hadapsar", "category": "Water Supply", "severity": "High"},
    {"id": 22, "location": "Hadapsar", "category": "Electricity", "severity": "Medium"},
    {"id": 23, "location": "Hadapsar", "category": "Sanitation", "severity": "High"},
    {"id": 24, "location": "Hadapsar", "category": "Sanitation", "severity": "Medium"},
    {"id": 25, "location": "Hadapsar", "category": "Public Transport", "severity": "Low"},

    # Baner
    {"id": 26, "location": "Baner", "category": "Road Infrastructure", "severity": "Medium"},
    {"id": 27, "location": "Baner", "category": "Road Infrastructure", "severity": "High"},
    {"id": 28, "location": "Baner", "category": "Road Infrastructure", "severity": "Medium"},
    {"id": 29, "location": "Baner", "category": "Water Supply", "severity": "High"},
    {"id": 30, "location": "Baner", "category": "Water Supply", "severity": "High"},
    {"id": 31, "location": "Baner", "category": "Electricity", "severity": "High"},
    {"id": 32, "location": "Baner", "category": "Electricity", "severity": "Medium"},
    {"id": 33, "location": "Baner", "category": "Public Transport", "severity": "Medium"},
    {"id": 34, "location": "Baner", "category": "Public Transport", "severity": "Low"},

    # Shivajinagar
    {"id": 35, "location": "Shivajinagar", "category": "Road Infrastructure", "severity": "High"},
    {"id": 36, "location": "Shivajinagar", "category": "Road Infrastructure", "severity": "Medium"},
    {"id": 37, "location": "Shivajinagar", "category": "Water Supply", "severity": "Low"},
    {"id": 38, "location": "Shivajinagar", "category": "Electricity", "severity": "High"},
    {"id": 39, "location": "Shivajinagar", "category": "Electricity", "severity": "High"},
    {"id": 40, "location": "Shivajinagar", "category": "Sanitation", "severity": "Medium"},
    {"id": 41, "location": "Shivajinagar", "category": "Public Transport", "severity": "High"},
    {"id": 42, "location": "Shivajinagar", "category": "Public Transport", "severity": "Medium"},
    {"id": 43, "location": "Shivajinagar", "category": "Public Transport", "severity": "High"},

    # Viman Nagar
    {"id": 44, "location": "Viman Nagar", "category": "Road Infrastructure", "severity": "Medium"},
    {"id": 45, "location": "Viman Nagar", "category": "Road Infrastructure", "severity": "Low"},
    {"id": 46, "location": "Viman Nagar", "category": "Water Supply", "severity": "Medium"},
    {"id": 47, "location": "Viman Nagar", "category": "Electricity", "severity": "Medium"},
    {"id": 48, "location": "Viman Nagar", "category": "Sanitation", "severity": "High"},
    {"id": 49, "location": "Viman Nagar", "category": "Sanitation", "severity": "Medium"},
    {"id": 50, "location": "Viman Nagar", "category": "Public Transport", "severity": "High"},
]


def detect_hotspots() -> list[dict]:
    """
    Aggregate complaints by location + category and calculate hotspot scores.

    Hotspot score = complaint_count * 10 + high_severity_count * 5 (capped at 100)
    Classification: 0-29 = Low, 30-59 = Medium, 60-100 = High
    """
    # Group by location + category
    groups: dict[tuple[str, str], list[dict]] = {}

    for complaint in MOCK_COMPLAINTS:
        key = (complaint["location"], complaint["category"])
        if key not in groups:
            groups[key] = []
        groups[key].append(complaint)

    hotspots = []

    for (location, category), complaints in groups.items():
        complaint_count = len(complaints)
        high_severity_count = sum(1 for c in complaints if c["severity"] == "High")

        hotspot_score = complaint_count * 10 + high_severity_count * 5
        hotspot_score = min(hotspot_score, 100)

        if hotspot_score <= 29:
            hotspot_level: Literal["Low", "Medium", "High"] = "Low"
        elif hotspot_score <= 59:
            hotspot_level = "Medium"
        else:
            hotspot_level = "High"

        hotspots.append({
            "location": location,
            "category": category,
            "complaint_count": complaint_count,
            "high_severity_count": high_severity_count,
            "hotspot_score": hotspot_score,
            "hotspot_level": hotspot_level,
        })

    # Sort by hotspot_score descending
    hotspots.sort(key=lambda x: x["hotspot_score"], reverse=True)

    return hotspots