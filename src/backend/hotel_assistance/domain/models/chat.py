from enum import StrEnum

from pydantic import BaseModel


class ChatRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class ChatTurn(BaseModel):
    role: ChatRole
    content: str
