"""The shapes the service returns. They are the contract with the desktop shell, which generates
its TypeScript types from the committed OpenAPI schema (``docs/api/openapi.json``).

Values mirror ``exchange.library.query``; where that returns filesystem paths for thumbnails, the
service returns URLs instead, served by the service itself.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Health(BaseModel):
    service: Literal["exchange"] = "exchange"
    version: str
    api: int = Field(description="The API version; paths start with /api/v{api}")
    schema_version: int = Field(description="The library database schema this service uses")


class Root(BaseModel):
    id: int
    path: str
    status: Literal["online", "offline"]
    offline_since: str | None = None


class ContainerCount(BaseModel):
    id: int
    name: str
    kind: str | None = None
    count: int


class TypeCount(BaseModel):
    type_id: str
    name: str
    count: int


class SidebarEnvironment(BaseModel):
    id: int
    name: str
    type_id: str
    status: Literal["online", "offline", "partial"]
    count: int
    roots: list[Root]
    containers: list[ContainerCount]
    types: list[TypeCount]


class Sidebar(BaseModel):
    all: int = Field(description="Assets with at least one live entry")
    unidentified_dossiers: int
    unattached_files: int = Field(description="Counted when each online root was last scanned")
    environments: list[SidebarEnvironment]


class Environment(BaseModel):
    id: int
    uid: str
    name: str
    type_id: str
    status: Literal["online", "offline", "partial"] = Field(description="From its roots, as in the sidebar")
    added_at: str
    last_scanned_at: str | None = None
    roots: list[Root]


class Brick(BaseModel):
    """One item card in the browser."""

    uid: str
    name: str
    type_id: str
    type_name: str
    confidence: float
    unidentified: bool
    thumbnail_url: str | None = Field(description="Served by this service; null without a thumbnail")
    format: str | None = Field(description="The primary file's extension, e.g. .glb")
    environments: list[str]
    entries: int
    children: int


class Page(BaseModel):
    items: list[Brick]
    total: int
    offset: int


class FieldValue(BaseModel):
    value: Any = None
    source: str | None = Field(None, description="scan, user, or a lookup source")


class DossierRef(BaseModel):
    uid: str
    name: str | None = None
    type_id: str | None = None


class EnvironmentRef(BaseModel):
    id: int
    name: str
    type_id: str


class EntryFile(BaseModel):
    id: int
    rel_path: str
    path: str = Field(description="Absolute path on this PC")
    size: int | None = None
    hash: str | None = None
    state: str | None = None
    role: str


class Entry(BaseModel):
    id: int
    container: str
    container_kind: str | None = None
    status: str
    source_container: str | None = None
    created_at: str | None = None
    retired_at: str | None = None
    variant: str | None = None
    moved_from: str | None = None
    files: list[EntryFile]


class Ledger(BaseModel):
    environment: EnvironmentRef
    entries: list[Entry]


class Dependency(BaseModel):
    reference: str
    status: str
    target: DossierRef | None = None


class HistoryItem(BaseModel):
    id: int | None = Field(None, description="The curation log id; null for entry events")
    at: str | None = None
    action: str
    payload: dict[str, Any]
    undoable: bool = False


class TagSource(BaseModel):
    tag: str
    sources: list[str]
    confidence: float
    user: Literal["add", "remove"] | None = None


class Suggestion(BaseModel):
    id: int
    kind: str
    payload: dict[str, Any]


class CollectionRef(BaseModel):
    uid: str
    name: str


class DossierDetail(BaseModel):
    """Everything the inspector shows for one asset."""

    uid: str
    name: str
    name_overridden: bool
    type_id: str
    type_name: str
    type_overridden: bool
    confidence: float
    unidentified: bool
    signals: Any = Field(None, description="What produced the identification and its confidence")
    fields: dict[str, FieldValue]
    parent_fields: dict[str, FieldValue] = Field(
        default_factory=dict, description="The parent product's fields (origin usually lives there)")
    tags: list[str]
    variant: Any = None
    thumbnail_url: str | None = None
    parent: DossierRef | None = None
    children: list[DossierRef]
    ledgers: list[Ledger]
    dependencies: list[Dependency]
    required_by: list[DossierRef]
    history: list[HistoryItem]
    variants: list[str]
    tag_sources: list[TagSource]
    aliases: list[DossierRef]
    suggestions: list[Suggestion]
    collections: list[CollectionRef]


class Collection(BaseModel):
    uid: str
    name: str
    query: str | None = Field(None, description="A smart collection's search")
    smart: bool
    count: int | None = Field(None, description="Null when a smart collection's search no longer compiles")


class Problem(BaseModel):
    detail: str
