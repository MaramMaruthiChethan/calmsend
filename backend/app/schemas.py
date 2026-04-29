from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    recipient: str = Field(default="Recipient", max_length=80)
    source_app: str = Field(default="generic", max_length=40)
    content_type: str = Field(default="chat", max_length=40)
    delay_mode: str = Field(default="smart", max_length=20)


class AnalyzeResponse(BaseModel):
    label: str
    confidence: float
    cooldown_seconds: int
    reasoning: list[str]
    rewritten_message: str
    can_send_now: bool
    model_accuracy: float
    source_app: str
    content_type: str
    delay_mode: str
    risk_score: int
    send_action: str
    blocked_features: list[str]


class IntegrationDescriptor(BaseModel):
    id: str
    name: str
    category: str
    host_patterns: list[str]
    supported_content: list[str]
    notes: str
    launch_url: str


class LinkedAppSetting(BaseModel):
    id: str
    enabled: bool
    delay_mode: str


class SettingsResponse(BaseModel):
    default_delay_mode: str
    linked_apps: list[LinkedAppSetting]
