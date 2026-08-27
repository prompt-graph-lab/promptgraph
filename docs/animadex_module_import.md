# AnimaDex Module Import

Status: v1 browser/import implemented. The read-only discovery groundwork,
AnimaDex Browser, Global Module import path, and imported-metadata preservation
are implemented.

PromptGraph-Pro can now discover local AnimaDex-style SQLite, CSV, and thumbnail/data directories, preview one normalized character record, and import it as a Global Module after explicit confirmation.

Full local AnimaDex-style databases are treated as mixed local libraries. Character, Artist, Copyright/Work/Series, directory, and unknown records are separated during discovery so artist/copyright rows do not fill the character browser by accident.

## Implemented State

- Added `core.animadex_discovery` as a read-only local discovery helper.
- Detects likely local AnimaDex SQLite files, CSV exports, and image/thumbnail directories.
- Opens SQLite files in read-only mode and inspects table/column metadata.
- Samples likely character rows from SQLite and CSV data into normalized preview records.
- Samples directory-only image records for thumbnail/data folders when no tabular trigger metadata is available.
- Added `AnimaDex Browser (Experimental)` inside the Pro Persistent Module Library sidebar.
- Supports manual local path discovery, source summaries, record search, one-record selection, thumbnail preview, Global Module preview, and explicit import.
- Imports only into the user-level Global Module Library after clicking `Import as Global Module`.
- Preserves `animadex_metadata` and other unknown Global Module extension fields when edited modules are saved or renamed in Global Module Manager.
- Current: separates SQLite/CSV records into Characters, Artists, Copyrights, and unknown buckets, with Characters as the default browser/import type.
- Current: searches large SQLite DBs with query + result limit instead of loading all rows into memory.
- Current: can explicitly save one local file or directory path as the editor-wide `animadex_local_path` default in `.editor_settings.json`.
- Current: restores that saved path into a new session, keeps it across Project and workspace transitions, and clears only the durable default when requested.
- Current: uses 500 as the new-session Search/display limit while keeping 100, 500, and 1000 as session-only choices.

Browsing does not mutate prompt lines, Project Modules, project JSON, Gallery routes, generated candidates, or images.

The discovery helper does not mutate project JSON, prompt lines, Project Modules, or the Global Module Library. It does not call remote APIs, look up Civitai data, or download assets.

The browser import action writes to the user-level Global Module Library only after clicking `Import as Global Module`.

## UI Entry Point

Open the dedicated authoring workspace:

1. Sidebar `Workspace`
2. `Module / Attribute Authoring`
3. `Module Library / Creation`
4. `AnimaDex Browser (Experimental)`

The browser is collapsed by default. Enter a local AnimaDex DB file, CSV file, or data directory path, then click `Discover AnimaDex Data`.

The v1 browser keeps discovery results in Streamlit session state so normal app reruns do not rescan the path automatically.

`Save as default` normalizes the current file or directory path and stores it as a Global Editor Setting in `.editor_settings.json`. The path may be saved while an external drive, network share, or later-mounted directory is unavailable; the Browser reports its current availability. `Clear saved default` removes only the durable default and leaves the current session input and discovery summary intact. Neither action scans the path. The path is not stored in Project JSON or the Global Module Library.

The Search/display limit defaults to 500 in a new session. Users may still choose 100, 500, or 1000, and the current session selection continues to drive both discovery sampling and record search. The limit itself is not persisted.

The `Global Module Library Search` shown above this browser is a separate
session-only query over already-imported Global Modules. It scopes
`Global → Project` and `Manage Global Modules`; it does not change the AnimaDex
path, discovery summary, 100 / 500 / 1000 limit, or record-search query.
Conversely, AnimaDex search results are not included in the Global Library
matched count. An explicit AnimaDex import reloads the latest Global Library,
applies the import without reverting unrelated writes from another session,
saves through the existing normalization contract, and caches the canonical
persisted Library. The current Global Library query is then reapplied without
persisting that query or rescanning AnimaDex. A failed save does not replace the
previous cache.

The current browser flow is:

```text
Module Library / Creation
-> AnimaDex Browser (Experimental)
-> local DB / CSV / directory path
-> optionally Save as default
-> Discover AnimaDex Data
-> choose record type and search fields
-> search records by character/name, series/copyright/work, trigger, tags, or traits
-> select one record
-> preview thumbnail and Global Module mapping
-> Import as Global Module
```

The default record type is `Characters`. `Artists` and `Copyrights` are preview-only in the current browser; `Import as Global Module` is enabled for Character records.

Rich card/image browsing remains a Pro v1.1/Desktop direction. Multiple AnimaDex roots, recent-path management, automatic discovery, background scanning, and an OS-native path picker are outside the current Pro v1 behavior.

## Supported Local Input Types

Current v1 inputs are local only:

- local SQLite DB files
- local CSV exports
- local data/image/thumbnail directories

### SQLite DB

Likely SQLite files are detected by `.db`, `.sqlite`, or `.sqlite3` extension, and by file names containing SQLite/AnimaDex-style terms. The helper inspects:

- table names from `sqlite_schema`
- table columns from `pragma table_info`
- a limited preview sample from tables classified as character, artist, copyright/work/series, or unknown
- query-limited search results from classified tables when the browser search field is used

Observed/expected useful fields include:

- identity: `id`, `character_id`, `uid`, `uuid`, `key`, `hash`
- names: `name`, `display_name`, `title`, `character`, `character_name`, `chara`
- work/copyright: `copyright`, `copyright_name`, `series`, `series_name`, `work`, `work_name`, `franchise`
- prompt identity: `trigger`, `activation_text`, `prompt`, `main_tag`, `tag`
- tag payload: `core_tags`, `tags`, `prompt_tags`, `stable_tags`, `tag_string`
- traits: `hair_color`, `hair_length`, `eye_color`, `gender`, plus `trait*` or `facet*` columns
- assets: `image_path`, `thumbnail_path`, `thumb_path`, `cover_path`
- metadata: `lora`, `lora_name`, `lora_info`, `model`, `source_url`, `url`, `count`, `popularity`, `post_count`, `favorites`, `score`

Table classification is intentionally conservative:

- table names such as `characters`, `character`, `chars`, or `chara` are treated as character sources;
- table names such as `artists` or `artist` are treated as artist sources;
- table names such as `copyrights`, `copyright`, `works`, `work`, `series`, or `franchise` are treated as copyright/work sources;
- columns are used as secondary signals when table names are generic.

Artist and copyright/work tables are not merged into `character_records`.

Unknown schema variants are expected. The discovery helper records tables/columns even when it cannot confidently normalize character records.

### CSV Exports

CSV files are listed for inspection even when their filenames are generic. The helper separately marks whether the file appears to contain character, artist, copyright/work, or unknown records. CSV headers are matched against the same field aliases as SQLite columns. CSV rows are sampled only for preview.

Useful CSV forms:

- one character per row with `trigger` and `tags`
- one character per row with `character`, `copyright`, and trait columns
- AnimaDex-style exports that include local thumbnail/image paths

### Local Data Directory With Thumbnails

Image files are detected by local extension:

- `.png`
- `.jpg`
- `.jpeg`
- `.webp`
- `.gif`
- `.bmp`

Directories whose path includes `thumb`, `thumbnail`, `cover`, `preview`, `image`, or `images` are marked as likely thumbnail directories. The helper also creates sampled `source_type: "directory"` records from local image stems so a future browser can preview image-only sources. These records have empty `trigger` and `core_tags` until the user maps them to real character metadata. The helper also attempts a simple filename-stem match between sampled SQLite/CSV records and nearby image files, but this is only a preview convenience. Missing image files must remain warnings in the UI, not import blockers.

## Normalized Character Record

The browser/import path uses this normalized preview shape as the bridge from AnimaDex local data into PromptGraph module preview:

```python
AnimaDexCharacterRecord = {
    "character_id": "stable local key",
    "name": "display name",
    "character": "character tag/name",
    "copyright": "work/copyright",
    "copyright_name": "display work name",
    "trigger": "primary identity trigger",
    "core_tags": ["optional", "tag-style", "identity", "tokens"],
    "traits": {
        "hair color": "value",
        "hair length": "value",
        "eye color": "value",
        "gender": "value",
    },
    "lora_info": "optional LoRA/model text",
    "source_url": "optional source URL text",
    "image_path": "optional local image path",
    "thumbnail_path": "optional local thumbnail path",
    "count": "optional count/popularity text",
    "popularity": "same source value when present",
    "source_type": "sqlite | csv | directory",
    "source_path": "local source file path",
    "source_detail": "table name, CSV file name, or directory image path",
}
```

## Current PromptGraph Module Mapping

Global Module name:

- Prefer display name or character name.
- Include copyright/work only when needed to disambiguate duplicate character names.

Module body:

- `trigger`
- optional `core_tags`; the browser default is ON when core tags are present
- selected stable tags or traits only after user review

Core tokens:

- `trigger` by default.
- `core_tags` only when the user enables tag-style strict mode for Illustrious, NovaAnime, NoobAI, SDXL, or similar workflows; the browser default is OFF.
- The browser toggle `Include core_tags in Core tokens` defaults OFF.
- The browser toggle `Include core_tags in module body` defaults ON when the record has core tags.
- If a record has no trigger but does produce body tokens, the first body token is shown and saved as a fallback Core token with a warning.
- imported Global Modules use `type: "character"`.

The v1 import target is Characters -> Global Module. Artist and Copyright/Work records can be inspected to help search and disambiguation, but they are not imported as Global Modules yet.

Attribute labels:

- `copyright`
- `hair color`
- `hair length`
- `eye color`
- `gender`
- `lora info`
- `source url`
- `thumbnail path`

The default mapping should be trigger-first. Anima understands character identity strongly, so `trigger` is the safest Core identity anchor. `core_tags` are valuable for tag-style models, but they should stay optional because overly strict Core Tokens can make Candidate Scanner results too sparse.

## Persisted Global Module Fields

Imported modules use the existing Global Module Library entry shape:

- `body`
- `type: "character"`
- `core_tokens`
- `min_match_tokens`
- `animadex_metadata`

`animadex_metadata` stores reviewable local-source metadata from the selected record, including source path/detail, traits, thumbnail/image paths, LoRA text, source URL text, and count/popularity when present. This is stored as module metadata only; it is not copied into project Attribute Labels or prompt lines by the browser.

Global Module Manager edits preserve `animadex_metadata` and other unknown Global Module metadata fields by default. Editing a module updates only the user-editable module fields (`body`, `type`, `core_tokens`, and `min_match_tokens`) unless a future UI explicitly edits extension metadata.

Duplicate names are safe:

- the suggested name is auto-disambiguated with copyright/work or a short stable source key when possible;
- if the user edits the name to an existing Global Module, import requires the explicit `Overwrite/update existing Global Module` checkbox.

## Unknowns And Risks

- Real AnimaDex installations may use schema names not covered by the initial aliases.
- Some exports may store tags as JSON, nested strings, or separate tag tables rather than a single row field.
- A DB may have multiple character-like tables; the browser UI should show source/table selection instead of guessing silently.
- Some full AnimaDex imports may split character, artist, copyright/work, traits, tags, and LoRA data across multiple tables; current search focuses on single classified tables and does not solve arbitrary joins yet.
- Thumbnail paths may be relative to the DB file, the CSV file, or a separate data root.
- Duplicate character names need clear disambiguation using copyright/work and stable IDs.
- `source_url` may point to external sites, but v1 should only display stored text and never fetch it automatically.
- LoRA information may be a model name, filename, hash, or free text; it should remain metadata until users explicitly decide how to use it.
- Batch import is not implemented in v1.
- Directory-only thumbnail records can be previewed, but import is disabled unless the record has usable trigger/body tokens.
- Trait and LoRA joins may still be limited when a source schema stores them in separate tables.
- Metadata persistence depends on the current Global Module entry format and is not projected into Project Module attributes.

## Safety Boundaries

AnimaDex Module Import v1 is intentionally local, manual, and preview-first.

It does not implement:

- remote AnimaDex sync
- remote API calls
- Civitai lookup
- automatic downloads
- automatic prompt conversion or prompt rewriting
- Project Module mutation during browsing/import
- prompt line mutation
- Gallery route, candidate, or variant mutation
- batch import
- full trait/LoRA joins across arbitrary database schemas
- background sync or full DB cache import

## Recommended Next Implementation Plan

1. Add richer source/table selection for SQLite databases with multiple character-like tables.
2. Add optional batch import after duplicate handling and preview ergonomics are proven.
3. Add schema adapters for known AnimaDex exports that split traits/tags/LoRA data across tables.
4. Add optional Attribute Label projection when loading a Global Module into a project, not during AnimaDex browsing.
5. Add better thumbnail root configuration for exports whose image paths are relative to a separate data root.

Future work should still avoid remote lookup, Civitai integration, automatic prompt rewriting, and background synchronization unless those features are designed explicitly.

## Validation Notes

Expected validation for this feature area:

- `python -m compileall .`
- `git diff --check .`
- Confirm the Streamlit app starts.
- Confirm normal Module/Gallery behavior is unchanged.
- Confirm the discovery helper handles missing DB/CSV/thumbnails gracefully.
- Confirm this doc clearly states implemented behavior versus planned importer behavior.
- Confirm selecting an AnimaDex record shows a preview but does not import until the explicit button click.
- Confirm imported Global Modules appear in the existing Global Module Manager.
