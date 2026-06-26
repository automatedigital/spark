"""Pydantic request bodies shared by the Spark dashboard backend routes."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from spark_cli.context_models import ContextItem


class ConfigUpdate(BaseModel):
    config: dict


class EnvVarUpdate(BaseModel):
    key: str
    value: str


class EnvVarDelete(BaseModel):
    key: str


class EnvVarReveal(BaseModel):
    key: str


class AdminActionStart(BaseModel):
    args: dict[str, Any] = {}
    confirm: bool = False


class GatewayControlRequest(BaseModel):
    action: str
    confirm: bool = False


class ProfileCreateRequest(BaseModel):
    name: str
    clone_from: str | None = None
    clone_config: bool = False
    clone_all: bool = False
    no_alias: bool = True


class ProfileRenameRequest(BaseModel):
    new_name: str
    confirm: bool = False


class ProfileExportRequest(BaseModel):
    output_path: str | None = None
    confirm: bool = False


class ProfileImportRequest(BaseModel):
    archive_path: str
    name: str | None = None
    confirm: bool = False


class McpServerCreate(BaseModel):
    name: str
    url: str | None = None
    command: str | None = None
    args: list[str] = []
    env: dict[str, str] = {}


class PluginActionRequest(BaseModel):
    name: str
    confirm: bool = False


class FeedbackSubmitBody(BaseModel):
    name: str = ""
    email: str = ""
    area: str = ""
    note: str


class OnboardingSkillsRequest(BaseModel):
    mode: str


class OpenExternalRequest(BaseModel):
    url: str


class OAuthSubmitBody(BaseModel):
    session_id: str
    code: str


class CronJobCreate(BaseModel):
    prompt: str
    schedule: str
    name: str = ""
    deliver: str = "local"


class CronJobUpdate(BaseModel):
    updates: dict


class SkillToggle(BaseModel):
    name: str
    enabled: bool


class RawConfigUpdate(BaseModel):
    yaml_text: str


class KanbanUpdate(BaseModel):
    status: str


class ConversationCreate(BaseModel):
    message: str
    model: str | None = None
    context_items: list[ContextItem] = Field(default_factory=list)


class ConversationMessage(BaseModel):
    message: str
    context_items: list[ContextItem] = Field(default_factory=list)


class ConversationInterrupt(BaseModel):
    message: str | None = None


class ConversationModelBody(BaseModel):
    model: str


class ConversationForkBody(BaseModel):
    from_message_index: int | None = None


class ConversationRetryBody(BaseModel):
    message_index: int
    message: str | None = None


class ConversationApprovalBody(BaseModel):
    choice: str
    resolve_all: bool = False


class TokenEstimateRequest(BaseModel):
    prompt: str = ""
    context_items: list[ContextItem] = Field(default_factory=list)
    brief: str = ""
    session_id: str | None = None
    history_message_count: int = 0
    model: str | None = None


class CanvasChatBody(BaseModel):
    message: str
    history: list[dict[str, Any]] = Field(default_factory=list)
    model: str | None = None
    slug: str | None = None


class BriefUpdate(BaseModel):
    text: str


class ManifestUpdate(BaseModel):
    data: dict = {}


class SummarizeFileRequest(BaseModel):
    path: str
    workspace_slug: str | None = None


class WorkspaceConvCreate(BaseModel):
    message: str
    model: str | None = None
    context_items: list[ContextItem] = Field(default_factory=list)
