from pydantic import BaseModel

from hotel_assistance.domain.models.filter_definition import FilterDefinition


class CandidateFilter(BaseModel):
    """A registry filter preselected as potentially relevant to a user message.

    ``score`` is retriever-specific and only meaningful for ranking within a
    single retrieval; it is not a probability.
    """

    definition: FilterDefinition
    score: float
