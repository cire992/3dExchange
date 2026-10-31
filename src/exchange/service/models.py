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
    root: int = Field(description="With `key`, the file as a FileRef, for linking it elsewhere")
    key: str
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


# Jobs and environments (6g) -----------------------------------------------------------------------


class Progress(BaseModel):
    """A worker's latest progress line: a scan's (phase 1 discovery, 2 identification, 3
    enrichment), or a requisition run's (requisition, item, step and message)."""

    model_config = {"extra": "allow"}
    phase: int | None = None
    environment: str | None = None
    step: str | None = Field(None, description="e.g. discovery, identification, hashing, thumbnails")
    done: int = 0
    total: int = 0
    requisition: str | None = Field(None, description="A requisition run: the requisition's name")
    item: str | None = Field(None, description="A requisition run: the asset it is converting")
    message: str | None = None


class RootReport(BaseModel):
    model_config = {"extra": "allow"}
    path: str
    confidence: float
    signals: list[str]
    variant: str | None = None
    registered: bool
    status: str = Field(description="scanned, detected (a dry run) or offline")
    files: int = 0
    new: int = 0
    changed: int = 0
    unchanged: int = 0
    gone: int = 0
    offline_days: int | None = None
    identification: dict[str, Any] | None = None


class EnvironmentReport(BaseModel):
    model_config = {"extra": "allow"}
    id: int | None = Field(None, description="Null in a dry run for an environment not yet registered")
    name: str
    type_id: str
    roots: list[RootReport]
    enrichment: dict[str, Any] | None = None


class ScanReport(BaseModel):
    """What ``exchange scan`` (or ``rescan``) reports; a dry run only detects."""

    model_config = {"extra": "allow"}
    folder: str | None = None
    dry_run: bool
    environments: list[EnvironmentReport]
    links_skipped: list[str] = []
    excluded: list[str] = []
    errors: list[str] = []
    notes: list[str] = []
    cancelled: bool = False


class Job(BaseModel):
    id: int
    kind: Literal["scan", "detect", "rescan", "classify", "requisitions", "remove"]
    label: str
    state: Literal["running", "done", "failed", "stopped"]
    writes: bool = Field(description="It writes the library: one such job runs at a time")
    environments: list[int] = Field(description="The environments it was asked for; empty is all")
    started_at: str
    finished_at: str | None = None
    progress: Progress | None = None
    error: str | None = Field(None, description="Why it failed, or what stopping it kept")
    version: int = Field(description="Grows with every change; ask again with since=version to wait for the next")
    report: ScanReport | None = Field(None, description="A scan, detection or rescan's report, once it has ended")
    result: dict[str, Any] | None = Field(None, description="Another job's result, once it has ended (classify: "
                                          "counts; requisitions: what ran)")


class JobList(BaseModel):
    version: int = Field(description="Grows with every change of any job")
    jobs: list[Job] = Field(description="Running first, then the latest finished; without reports")


class FolderJob(BaseModel):
    folder: str = Field(description="An absolute folder path")


class EnvironmentsJob(BaseModel):
    environments: list[int] | None = Field(None, description="Environment ids; none or empty is every one")


class ClassifyJob(EnvironmentsJob):
    regroup: bool = Field(False, description="Also regroup hand-installed Daz products (after theme, author or "
                          "category edits; minutes on a big library)")


class VariantRef(BaseModel):
    id: str
    name: str


class EnvironmentType(BaseModel):
    id: str
    name: str
    handler: str = Field(description="mo2, daz, unreal or folder: how its files are organized")
    multi_root: bool = Field(description="Every root of this type joins one environment (Daz content directories)")
    fallback: bool = Field(description="Takes the files no other type claims (loose files)")
    ignore_globs: list[str] = Field(description="Always ignored")
    variants: list[VariantRef]


class FoundSource(BaseModel):
    path: str
    name: str
    via: str = Field(description="Where it was found (Steam, Epic, Daz, MO2...)")
    type_id: str | None = Field(None, description="The environment type it matches, if any")
    confidence: float = 0.0
    signals: list[str] = []
    registered: bool = False


class Mo2Profiles(BaseModel):
    profiles: list[str]
    selected: str | None = Field(None, description="The profile the instance's ini selects")


class EnvironmentConfig(BaseModel):
    """An environment's settings; in a change, the fields given replace the ones it has (null or an
    empty list removes one)."""

    model_config = {"extra": "forbid"}
    ignore: list[str] | None = Field(None, description="Ignore rules (globs), from the next rescan")
    mo2_profile: str | None = None
    visibility: str | None = Field(None, description="personal or publishable")
    endpoint: str | None = Field(None, description="The folder requisitions write to; null is the default")


class ConfigResult(BaseModel):
    user_config: dict[str, Any] = Field(description="All its settings now")


class EnvironmentDetail(Environment):
    user_config: dict[str, Any] = Field(description="The settings the user chose")
    layer_config: dict[str, Any] = Field(description="What scans found (an MO2 instance's profiles...)")


class RootPlan(BaseModel):
    path: str
    confidence: float = 0.0
    signals: list[str] = []


class EnvironmentPlan(BaseModel):
    type_id: str
    name: str | None = Field(None, description="Default: from the type and the folder")
    roots: list[RootPlan]
    config: EnvironmentConfig = EnvironmentConfig()


class RegisterEnvironments(BaseModel):
    environments: list[EnvironmentPlan]
    exclude: list[str] = Field([], description="Folders found inside added ones that scans must never index")


class RegisteredEnvironment(BaseModel):
    id: int
    name: str
    type_id: str


class Registered(BaseModel):
    environments: list[RegisteredEnvironment]


class Changes(BaseModel):
    available: bool = Field(description="False without watchdog: no change notices")
    environments: list[int] = Field(description="Environments whose roots changed since they were last scanned")
    version: int = Field(description="Ask again with since=version to wait for the next change")


# Requisitions, processes and endpoints (6g, part 2) ------------------------------------------------


class ParameterView(BaseModel):
    id: str
    type: Literal["str", "int", "float", "bool", "choice", "path"]
    default: Any = None
    label: str
    help: str = ""
    choices: list[str] = []
    min: float | None = None
    max: float | None = None


class PrerequisiteView(BaseModel):
    id: str
    label: str
    ok: bool
    detail: str = Field(description="The path found, or how to fix it")
    tool: str | None = Field(None, description="The shared tool id it needs a path for (blender, texconv...)")


class ProcessView(BaseModel):
    id: str
    name: str
    version: str
    author: str
    description: str
    builtin: bool
    trusted: bool
    state: Literal["ready", "not trusted", "needs setup"] = Field(description="Only ready ones are offered")
    path: str
    input_types: list[str]
    input_tags: list[str]
    output_environment: str
    output_dossier_type: str
    prerequisites: list[PrerequisiteView]
    problems: list[str] = Field(description="What is wrong with a trusted package's chain")
    trust: list[str] = Field(description="What trusting it lets it do, to show before asking")
    parameters: list[ParameterView]
    roles: list[str] = Field(description="What its output can be in a place, e.g. prop (the manifest's [output] roles); "
                       "empty for built-ins")


class ProcessList(BaseModel):
    processes: list[ProcessView]
    problems: list[str] = Field(description="Packages that could not be read, and why")


class ToolPath(BaseModel):
    tool: str = Field(description="A tool id, e.g. blender")
    path: str | None = Field(None, description="The executable; null forgets it")


class PresetView(BaseModel):
    name: str
    description: str = ""
    environment: str | None = Field(None, description="The environment type it was made for")
    shipped: bool = Field(description="From a process package: read-only")
    processes: list[str]
    options: dict[str, dict[str, Any]] = Field(description="Option values by process")


class PresetSave(BaseModel):
    name: str
    options: dict[str, dict[str, Any]]
    description: str = ""
    environment: str | None = None


class EndpointView(BaseModel):
    environment_id: int
    environment: str
    type_id: str
    folder: str | None = Field(None, description="Where output goes (null when it has no online folder)")
    label: str | None = None
    custom: bool = Field(description="The user chose the folder (otherwise the type's default)")
    visibility: str
    problem: str | None = None


class RoutesRequest(BaseModel):
    uids: list[str] = Field(min_length=1)
    environment: int


class RouteChoice(BaseModel):
    processes: list[str]
    route: Literal["convert", "copy"]
    label: str


class PlanRequest(BaseModel):
    uids: list[str] = Field(min_length=1, description="Assets or products; several are planned with the same options")
    environment: int = Field(description="The target environment")
    processes: list[str] | None = Field(None, description="A chain from /requisitions/routes; null is automatic")
    options: dict[str, dict[str, Any]] = Field({}, description="Option values by process; they win over the preset's")
    preset: str | None = Field(None, description="Start from a preset; null is the options last used with each process")
    endpoint_folder: str | None = Field(None, description="Write here instead of the environment's endpoint")
    on_collision: Literal["ask", "overwrite", "rename", "skip"] = "ask"
    excluded: list[str] = Field([], description="Items (asset uids) left out")
    name: str | None = Field(None, description="The requisition's name, for one asset")


class EndpointRef(BaseModel):
    folder: str
    root: str
    visibility: str
    label: str


class PlanItemView(BaseModel):
    dossier_uid: str
    name: str
    type_id: str
    source_entry_id: int | None = None
    source: str = Field(description="Where the source entry is, in words")
    route: Literal["convert", "copy", "none"]
    processes: list[str]
    process_names: list[str]
    params: dict[str, dict[str, Any]]
    include: bool
    problems: list[str]


class PlanView(BaseModel):
    name: str
    environment_id: int
    on_collision: str
    endpoint: EndpointRef
    warnings: list[str]
    items: list[PlanItemView]


class OptionForm(BaseModel):
    process: str
    name: str
    values: dict[str, Any] = Field(description="What the plan would use")
    parameters: list[ParameterView]


class PlanResult(BaseModel):
    plans: list[PlanView]
    problems: list[str] = Field(description="Assets that could not be planned, and warnings")
    forms: list[OptionForm] = Field(description="One per process in the included items")
    included: int


class Queued(BaseModel):
    ids: list[int]


RequisitionState = Literal["queued", "held", "running", "needs_attention", "fulfilled", "partially_fulfilled",
                           "failed", "stale", "removed", "replaced"]


class RequisitionRow(BaseModel):
    model_config = {"extra": "allow"}
    id: int
    uid: str
    name: str
    state: RequisitionState
    position: int
    environment_id: int
    environment: str
    on_collision: str
    message: str | None = None
    replaces: int | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    items: int = Field(description="Included items")
    done: int


class RequisitionItem(BaseModel):
    model_config = {"extra": "allow"}
    id: int
    dossier_uid: str
    name: str
    source_entry_id: int | None = None
    processes: list[dict[str, Any]] = Field(description='[{"id", "version"}]')
    params: dict[str, dict[str, Any]]
    include: int
    state: str
    message: str | None = None
    outputs: list[dict[str, Any]]


class RequisitionWrite(BaseModel):
    model_config = {"extra": "allow"}
    id: int
    item_id: int | None = None
    path: str
    action: Literal["created", "overwritten", "sidecar"]
    recycled_to: str | None = None
    written_at: str
    removed_at: str | None = None


class RequisitionDetail(BaseModel):
    model_config = {"extra": "allow"}
    id: int
    uid: str
    name: str
    state: str
    position: int
    environment_id: int
    endpoint: EndpointRef
    on_collision: str
    message: str | None = None
    replaces: int | None = None
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    items: list[RequisitionItem]
    writes: list[RequisitionWrite]


class HoldRequest(BaseModel):
    held: bool = True


class MoveRequest(BaseModel):
    position: int = Field(ge=1, description="1 is first")


class ResumeRequest(BaseModel):
    on_collision: Literal["ask", "overwrite", "rename", "skip"] | None = Field(
        None, description="How to settle collisions now; null keeps the requisition's")


class StaleRequisition(BaseModel):
    id: int
    why: str


class RunRequest(BaseModel):
    ids: list[int] | None = Field(None, description="Only these requisitions; none is the whole queue")


class RemoveRequest(BaseModel):
    requisition: int


# Claims (R4a) ------------------------------------------------------------------------------------


class ClaimPath(BaseModel):
    status: Literal["ready", "not_ready", "none"] = Field(
        description="ready: a route can be walked now. not_ready: a chain exists and `process` names the first "
                    "process that needs setup. none: no process takes the thing to the place, or the dossier or "
                    "place is not in the library; `problem` says which")
    route: Literal["convert", "copy", "children"] | None = Field(
        description="children means each child dossier takes its own route; null when status is none")
    processes: list[str] = Field(
        description="The chain in order (for route children, the processes of all the children's chains, each "
                    "once); empty when there is none")
    process: str | None = Field(description="The first process that is not ready, when status is not_ready")
    problem: str | None = Field(description="Why the path can't be walked yet; null when it can")
    source_entry_id: int | None = Field(description="The ledger entry the route reads from; null when there is none")


class ClaimView(BaseModel):
    """A claim as the list shows it. A claim file may be hand-edited and then hold anything, so any field may
    read as its text or as null; these descriptions cover a file the API wrote."""
    id: str = Field(description="The file's name without .md")
    thing: str | None = Field(description="The dossier's uid")
    thing_name: str | None = Field(description="The dossier's name when the claim was made, as stored in the file; "
                                   "not refreshed on reads, so after a rename it differs from the dossier's name")
    as_: str | None = Field(alias="as", description="What the thing is in the place, e.g. prop; null for no role")
    place: str | None = Field(description="The environment's uid")
    place_name: str | None = Field(description="The environment's name when the claim was made, as stored in the "
                                   "file; not refreshed on reads, so after a rename it differs from the environment's")
    folder: str | None = Field(description="Where the output should go: absolute, or relative to the place; null "
                               "is the place's default folder, which a walk also uses when the place's root is "
                               "offline")
    milestone: str | None = Field(description="claimed, acquired, converted or installed. An open claim's is derived "
                                  "from the library on every read; a closed claim keeps the one it had")
    created: str | None = Field(description="The day the claim was made, as an ISO date")
    closed: str | None = Field(description="The day the claim was closed, as an ISO date; null while open")
    turn: Literal["you", "exchange", "build", "none"] = Field(
        description="Whose move it is. you: the user's (`turn_line` says what). exchange: a requisition of the "
                    "claim is queued or running in Exchange. build: no process takes the thing to the place yet, "
                    "so one has to be built (also when the place is not in the library: `path.problem` says "
                    "so). none: the claim is closed")
    turn_line: str = Field(description="What the turn's owner has to do when it is `you` or `build`; empty for "
                           "`exchange` and `none`")
    already_there: bool = Field(description="No role or folder and no requisitions, and the place already holds "
                                "the thing: it has a live entry there on an online root")
    path: ClaimPath = Field(description="The processes that take the thing to the place in the claim's role (`as`); "
                            "derived on every read, never written")


class ClaimRequisition(BaseModel):
    """One requisition a claim has walked. See `ClaimView` on hand-edited files."""
    uid: str | None = Field(description="The requisition's uid as the file lists it")
    id: int | None = Field(description="Null when the uid no longer resolves to a requisition")
    state: RequisitionState | None = Field(description="Null when `id` is")
    message: str | None = Field(description="Null when `id` is, and when the requisition has no message")


class ClaimDetail(ClaimView):
    notes: str = Field(description="The claim file's body, under its front matter")
    requisitions: list[ClaimRequisition] = Field(
        description="The requisitions the claim has walked, in the order its file lists them")


class ClaimList(BaseModel):
    claims: list[ClaimView] = Field(description="Newest created first; a claim with no created date comes last")
    problems: list[str] = Field(description="A line for each claim file that could not be read")


class ClaimPreviewRequest(BaseModel):
    uid: str = Field(description="The dossier to claim")
    environment: int = Field(description="The id of the environment it should end up in")
    as_: str | None = Field(None, alias="as", description="What it is there, e.g. prop; null for no role")
    folder: str | None = Field(None, description="Absolute, or relative to the place; it may not leave the place")


class ClaimRequest(ClaimPreviewRequest):
    note: str = Field("", description="The claim's first note")


class ClaimClose(BaseModel):
    reason: str | None = Field(None, description="Added to the claim's notes")
