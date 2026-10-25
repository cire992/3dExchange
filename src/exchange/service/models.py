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


# Editing (Roadmap phase 6e) ---------------------------------------------------------------------

Refresh = Literal["none", "detail", "collections", "all"]


class EditResult(BaseModel):
    """One undoable edit, as the window reports it."""

    log_id: int = Field(description="The curation log entry; POST /history/{id}/undo undoes it")
    label: str = Field(description="What the edit was, for Undo and Redo, e.g. 'tag 3 assets'")
    new_uid: str | None = Field(None, description="The asset or collection the edit created, if any")
    refresh: Refresh = Field(description="What the edit can have changed: the page and inspector (detail), "
                             "also the sidebar's collections (collections), or also the sidebar's counts (all)")
    session: Session


class Session(BaseModel):
    """This service session's Undo and Redo, as the window's Edit menu shows them."""

    undo: str | None = Field(None, description="The label Undo would undo; null when there is nothing")
    redo: str | None = None


EditResult.model_rebuild()


class UndoResult(BaseModel):
    label: str | None = Field(None, description="What was undone or redone; null when there was nothing")
    refresh: Refresh
    session: Session


class FieldEdit(BaseModel):
    uids: list[str] = Field(min_length=1)
    field: str = Field(description="One of the editable fields (GET /choices); names are set one asset at a time")
    value: Any = Field(None, description="The new value; null reverts to the scanned one")


class TagEdit(BaseModel):
    uids: list[str] = Field(min_length=1)
    add: list[str] = []
    remove: list[str] = Field([], description="Removing a scanned tag hides it")


class TagRevert(BaseModel):
    uid: str
    tag: str


class ParentEdit(BaseModel):
    uids: list[str] = Field(min_length=1)
    parent: str | None = Field(description="The product to put them in; null takes them out of any product")


class ParentRevert(BaseModel):
    uid: str


class MergeEdit(BaseModel):
    uid: str = Field(description="The asset found twice; its entries join `into`")
    into: str


class FoldEdit(BaseModel):
    uid: str = Field(description="A variant of `into` (Donut01_Blue of Donut01_Pink)")
    into: str
    variant: str
    target_variant: str | None = Field(None, description="The variant name for `into`'s own entries, if they have none")


class SplitEdit(BaseModel):
    uid: str
    entries: list[int] = Field(min_length=1, description="Entry ids that become an asset of their own")
    name: str | None = None


class PromoteEdit(BaseModel):
    uid: str
    variant: str


class FileRef(BaseModel):
    root: int
    key: str = Field(description="The file's rel_key in that root (case-folded, '/' separators)")


class DeskFolder(BaseModel):
    root: int
    path: str = Field(description="A folder in that root, '/' separators; '' is the whole root")


class ProductEdit(BaseModel):
    name: str
    children: list[str] = []
    folder: DeskFolder | None = Field(None, description="The unattached files under this folder join the product")


class LinkEdit(BaseModel):
    uid: str
    files: list[FileRef] = []
    folder: DeskFolder | None = Field(None, description="Link the unattached files under this folder")


class UnlinkEdit(BaseModel):
    files: list[FileRef] = Field(min_length=1)


class DismissEdit(BaseModel):
    uids: list[str] = Field(min_length=1)
    dismissed: bool = Field(True, description="False counts them as assets again")


class IgnoreEdit(BaseModel):
    environment: int
    folder: str
    ignored: bool = True


class CollectionCreate(BaseModel):
    name: str
    query: str | None = Field(None, description="A saved search makes a smart collection")


class MembersEdit(BaseModel):
    uids: list[str] = Field(min_length=1)
    present: bool = Field(True, description="False removes them")


class WordEdit(BaseModel):
    value: str = Field(description="The term the word belongs to: a tag, variant group, channel or author")
    word: str
    present: bool = Field(True, description="False removes it (and excludes it, in a generated lexicon)")


class SuggestionIds(BaseModel):
    ids: list[int] = Field(min_length=1)


class SuggestionItem(BaseModel):
    id: int
    kind: str
    subject: str | None = None
    subject_name: str | None = None
    confidence: float
    state: str
    payload: dict[str, Any]


class Suggestions(BaseModel):
    total: int = Field(description="Pending suggestions of this kind (or all kinds)")
    counts: dict[str, int] = Field(description="Pending suggestions by kind")
    offset: int
    items: list[SuggestionItem]


class DeskRoot(BaseModel):
    id: int
    path: str
    environment_id: int
    environment: str


class DeskFolderCount(BaseModel):
    name: str
    path: str
    count: int


class DeskLevel(BaseModel):
    folders: list[DeskFolderCount] = Field(description="Subfolders with their unattached files (all levels), largest first")
    files: int = Field(description="Unattached files directly in this folder")
    total: int


class DeskFile(BaseModel):
    id: int
    rel_path: str
    rel_key: str
    size: int | None = None


class LexiconTermView(BaseModel):
    value: str
    words: list[str]
    patterns: list[str]
    found: list[str] = Field([], description="Words scans found (generated lexicons); not in the file")


class LexiconView(BaseModel):
    id: str
    name: str
    kind: str
    generated: bool = Field(description="Scans add words to it (known authors)")
    terms: list[LexiconTermView]
    exclude: list[str] = Field([], description="Found words the user removed; scans never add them back")


class HistoryEntry(BaseModel):
    id: int
    at: str
    action: str
    dossiers: list[str]
    details: dict[str, Any] = Field(description="The action's own details (field, value, tags, names...)")
    undoable: bool


class TypeChoice(BaseModel):
    id: str
    name: str
    extends: str | None = None


class Choices(BaseModel):
    types: list[TypeChoice]
    tags: list[str] = Field(description="The category lexicon's tags, for completion")
    fields: list[str] = Field(description="Fields POST /edits/fields can set")
