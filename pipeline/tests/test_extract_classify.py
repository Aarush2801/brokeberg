from typing import Any

import pytest
from extract_docs import x_post
from pydantic import ValidationError
from sqlalchemy.orm import Session

from brokeberg.extract.classify import Classification, classify
from brokeberg.extract.doc import ExtractState
from brokeberg.taxonomy import Topic


def test_classify_dedupes_and_keeps_policy_areas_within_topics(
    db_session: Session, fake_llm: Any
) -> None:
    fake_llm.set(
        Classification,
        Classification.model_validate(
            {
                "topics": ["trade_tariffs", "housing", "trade_tariffs"],
                "policy_areas": ["trade_tariffs", "taxation"],
                "jurisdiction_level": "federal",
                "election_relevance": 0.2,
                "confidence": 0.85,
            }
        ),
    )
    out = classify(x_post(), ExtractState(session=db_session))
    assert out.topics == [Topic.TRADE_TARIFFS, Topic.HOUSING]
    assert out.policy_areas == [Topic.TRADE_TARIFFS]  # taxation was not a topic


def test_unknown_topic_rejected() -> None:
    with pytest.raises(ValidationError):
        Classification.model_validate(
            {"topics": ["vibes"], "policy_areas": [], "jurisdiction_level": "federal",
             "election_relevance": 0.1, "confidence": 0.9}
        )
