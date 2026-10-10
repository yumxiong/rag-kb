"""Deterministic message byte limits; no provider tokenizer or network needed."""

import hashlib
import json
from typing import List

from langchain_core.documents import Document
from langchain_core.prompts import PromptTemplate
from langchain_openai.chat_models.base import _convert_message_to_dict

from app.core.anonymous_session import SessionError

MAX_MESSAGES_BYTES = 32 * 1024
QA_PROMPT = PromptTemplate.from_template(
    """你是一个智能助手，请根据以下文档内容回答用户的问题。

文档内容：
{context}

问题：{question}

请注意：
1. 请尽量基于提供的文档内容来回答问题
2. 如果文档中没有相关信息，请明确说明
3. 回答要准确、简洁、有帮助
4. 如果涉及多个方面，请分点说明

回答："""
)


def serialized_messages_size(messages) -> int:
    """Include roles, system instructions, query, context and JSON escaping.

    Use the installed ChatOpenAI serializer. Count ASCII-escaped JSON as UTF-8
    to cover HTTPX 0.27's wire representation as well as newer compact UTF-8.
    """
    return len(
        json.dumps(
            [_convert_message_to_dict(message) for message in messages],
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    )


def question_messages(question: str, documents: List[Document]):
    return QA_PROMPT.format_prompt(
        context="\n\n".join(doc.page_content for doc in documents), question=question
    ).to_messages()


def fit_question_documents(question: str, documents: List[Document]) -> List[Document]:
    """Keep complete chunks in retrieval priority order within the byte budget.

    Skip a chunk that does not fit, then consider the next candidate. Keeping
    whole chunks avoids citing a tail that the model never received.
    """
    if serialized_messages_size(question_messages(question, [])) > MAX_MESSAGES_BYTES:
        raise SessionError("invalid_request", 400)
    selected = []
    for document in documents:
        if not document.page_content:
            continue
        candidate = selected + [document]
        if (
            serialized_messages_size(question_messages(question, candidate))
            <= MAX_MESSAGES_BYTES
        ):
            selected.append(document)
    return selected


def question_context_hash(documents: List[Document]) -> str:
    """Hash full selected content, order and citation metadata, not a prefix."""
    content = [
        {
            "content": doc.page_content,
            "document_id": doc.metadata.get("document_id"),
            "filename": doc.metadata.get("filename"),
            "page": doc.metadata.get("page"),
        }
        for doc in documents
    ]
    return hashlib.sha256(
        json.dumps(content, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
