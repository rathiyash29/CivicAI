# MOCK DUPLICATE DETECTION - In production this will use database records and scalable similarity search.

import re
from typing import Literal

# Common English stop words to filter out
STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "has", "he", "in", "is", "it", "its", "of", "on", "that", "the",
    "to", "was", "were", "will", "with", "our", "your", "their",
    "this", "these", "those", "or", "but", "not", "have", "had",
    "been", "being", "do", "does", "did", "can", "could", "should",
    "would", "may", "might", "must", "shall", "here", "there",
    "where", "when", "why", "how", "what", "which", "who", "whom",
    "i", "you", "we", "they", "me", "him", "her", "us", "them",
    "my", "mine", "his", "hers", "ours", "yours", "theirs",
    "am", "is", "are", "was", "were", "be", "been", "being",
    "there", "here", "everywhere", "somewhere", "anywhere", "nowhere",
    "in", "on", "at", "by", "for", "with", "about", "against",
    "between", "into", "through", "during", "before", "after",
    "above", "below", "to", "from", "up", "down", "in", "out",
    "over", "under", "again", "further", "then", "once", "all",
    "any", "both", "each", "few", "more", "most", "other", "some",
    "such", "no", "nor", "not", "only", "own", "same", "so",
    "than", "too", "very", "s", "t", "can", "will", "just",
    "don", "should", "now", "d", "ll", "m", "o", "re", "ve", "y"
}


def normalize_text(text: str) -> set[str]:
    """
    Normalize text for comparison:
    - lowercase
    - remove punctuation
    - split into words
    - remove stop words
    - return set of meaningful words
    """
    # Lowercase
    text = text.lower()
    # Remove punctuation (keep alphanumeric and spaces)
    text = re.sub(r'[^\w\s]', ' ', text)
    # Split into words
    words = text.split()
    # Filter out stop words and very short words
    meaningful_words = {w for w in words if w not in STOP_WORDS and len(w) > 2}
    return meaningful_words


def find_similarity(text1: str, text2: str) -> float:
    """
    Calculate similarity between two texts using Jaccard index on meaningful words.
    Returns score from 0 to 100.
    """
    words1 = normalize_text(text1)
    words2 = normalize_text(text2)

    if not words1 or not words2:
        return 0.0

    intersection = words1 & words2
    union = words1 | words2

    jaccard = len(intersection) / len(union) if union else 0.0
    return round(jaccard * 100, 1)


def are_duplicates(text1: str, text2: str, threshold: float = 65) -> bool:
    """
    Check if two texts are likely duplicates based on similarity threshold.
    """
    similarity = find_similarity(text1, text2)
    return similarity >= threshold


# Sample existing complaints for duplicate checking
SAMPLE_COMPLAINTS = [
    {
        "id": 1,
        "text": "There are huge potholes on the road near the college",
        "location": "Pune"
    },
    {
        "id": 2,
        "text": "No water supply in our residential area for two days",
        "location": "Pune"
    },
    {
        "id": 3,
        "text": "Street lights are not working in our area",
        "location": "Pune"
    }
]


def check_duplicate(text: str, location: str = "", threshold: float = 65) -> dict:
    """
    Check if the given complaint text is similar to any existing complaint.
    Returns result with similar complaints above threshold.
    """
    similar_complaints = []

    for existing in SAMPLE_COMPLAINTS:
        # Calculate text similarity
        text_similarity = find_similarity(text, existing["text"])

        # Boost similarity if locations match
        location_match = location.strip().lower() == existing["location"].strip().lower()
        if location_match and text_similarity > 0:
            # Boost by 10% for location match, cap at 100
            text_similarity = min(text_similarity + 10, 100)

        if text_similarity >= threshold:
            similar_complaints.append({
                "id": existing["id"],
                "text": existing["text"],
                "location": existing["location"],
                "similarity": text_similarity
            })

    # Sort by similarity descending
    similar_complaints.sort(key=lambda x: x["similarity"], reverse=True)

    return {
        "success": True,
        "is_duplicate": len(similar_complaints) > 0,
        "similar_complaints": similar_complaints,
        "duplicate_count": len(similar_complaints)
    }