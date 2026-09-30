from pydantic import BaseModel, HttpUrl

class ChatRequest(BaseModel):
    prompt: str

class URL(BaseModel):
    url: str