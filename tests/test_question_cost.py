"""Byte boundaries include Unicode, JSON escaping and complete message roles."""

from langchain_core.documents import Document
from langchain_core.messages import HumanMessage

from app.core.question_cost import (
    MAX_MESSAGES_BYTES,
    fit_question_documents,
    question_context_hash,
    question_messages,
    serialized_messages_size,
)


def test_exact_32k_boundary_and_one_more_byte():
    overhead = serialized_messages_size([HumanMessage(content="")])
    message = HumanMessage(content="x" * (MAX_MESSAGES_BYTES - overhead))
    assert serialized_messages_size([message]) == MAX_MESSAGES_BYTES
    message.content += "x"
    assert serialized_messages_size([message]) == MAX_MESSAGES_BYTES + 1


def test_selects_complete_chunks_in_retrieval_order():
    documents = [
        Document(page_content=value) for value in ("a" * 20000, "b" * 20000, "c" * 100)
    ]
    selected = fit_question_documents("question", documents)
    assert selected == [documents[0], documents[2]]
    assert (
        serialized_messages_size(question_messages("question", selected))
        <= MAX_MESSAGES_BYTES
    )


def test_full_content_order_and_citation_metadata_affect_hash():
    first = Document(page_content="prefix" * 100 + "a", metadata={"page": 1})
    second = Document(page_content="prefix" * 100 + "b", metadata={"page": 1})
    assert question_context_hash([first]) != question_context_hash([second])
    assert question_context_hash([first, second]) != question_context_hash(
        [second, first]
    )
    before = question_context_hash([first])
    first.metadata["page"] = 2
    assert question_context_hash([first]) != before
