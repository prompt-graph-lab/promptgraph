# Graph Edit Illustration Browser

## Purpose

The Graph Edit Illustration Browser is a display-only performance boundary around the existing right-column editor list. It reduces Streamlit work by deciding the current visible page before dispatching any per-record editor. It does not redefine which records Graph Edit considers authoritative and does not change any production operation target.

```text
Full Project
├─ Graph
├─ PromptCloud
├─ Batch Edit
├─ Module / Attribute operations
├─ save / export
└─ Graph Edit Illustration Browser
   └─ filter + collapse + pagination limit editor rendering only
```

## Planning boundary

`core/graph_edit_illustration_browser.py` is a Streamlit-independent planner. It receives the exact non-deleted, optionally Graph-node-filtered list previously rendered by Graph Edit. That input remains authoritative, including its existing compatibility treatment of separator and Workbench records; the Browser does not invent a new editable-record predicate.

The planner performs only a lightweight pass over `project.prompt_lines` and the authoritative input to produce:

- position-based Scene membership from active separator handles;
- `all`, `outside_scenes`, and `scene:<separator-id>` filter choices;
- duplicate-label display disambiguation without using labels as identity;
- normalized all-view collapsed group keys using `scene:<separator-id>` or `outside_scenes`;
- page size normalization for 12, 24, or 48, with default 12;
- 1-based page clamping and the ordered `page_entries` slice;
- counts, empty/all-collapsed state, diagnostics, and current-Illustration reveal target.

Malformed, missing, deleted, or duplicate separator identities fail closed to outside-Scene membership or filter fallback. Existing core reason and diagnostic contracts are not rewritten. The planner never mutates the Project, session state, Gallery state, filesystem, settings, or serialized scope.

## Render owner

`app.py` has one Graph Edit Browser owner. `render_graph_edit_illustration_browser_page()` iterates only `page_entries` and calls `render_graph_edit_illustration_editor()` for those records. The extracted editor preserves the prior prompt/negative-prompt editing, selection/highlight, Focus Edit, reorder, duplicate, delete, history/save ownership, and widget keys.

Collapsed and page-out records never enter that renderer. Therefore their list thumbnails, filesystem existence checks made by thumbnail resolution, text widgets, and editor operations are not executed. A collapsed Streamlit expander is not used as the performance boundary; Python dispatch is skipped before the editor call.

Graph, PromptCloud, Batch Edit, Module / Attribute operations, save, and export keep their existing full-Project inputs and run outside this page dispatcher. Reorder continues to use the existing full-Project adjacency logic rather than page-local order.

## Filter, collapse, and pagination

The default view is `all`, page 1, page size 12, with no collapsed Scene. Page size choices are 12, 24, and 48. There is deliberately no `All` option because rendering every editor would recreate the performance problem.

In the all filter, Scene visibility is applied before pagination. Users can show all, close all, or toggle individual Scene groups and the outside-Scene group. Collapse identity uses the same typed namespace as filters: a Scene whose separator ID is `outside_scenes` has the group key `scene:outside_scenes`, while the special outside group remains `outside_scenes`. IDs such as `all` are likewise isolated as `scene:all`. A specific Scene filter always shows that Scene and the outside-Scene filter always shows outside records, regardless of the retained all-view collapse state. Filter, page-size, and collapse changes return to page 1; structural changes clamp the durable page to the available range.

Top controls provide First, Previous, page number, Next, and Last. Footer controls provide Previous and Next. Filter, page size, and page use durable Browser values plus separate temporary widget mirrors, avoiding hidden-widget cleanup, duplicate widget keys, and Gallery coupling.

## Current Illustration and state lifecycle

The Browser uses the existing highlighted Illustration ID; it does not create another current-selection owner. When that Illustration is outside the active filter/page, the UI reports it without changing selection. `現在のイラストを表示` explicitly selects its Scene (or outside-Scene filter) and calculated page. Missing, deleted, ambiguous, separator, and Workbench targets do not expose the reveal action.

The existing `text_<line-id>` and `negative_text_<line-id>` widgets remain explicit unsaved drafts until `Save Changes` succeeds. The Browser records only the IDs dispatched by the latest completed page render and compares those current-page widget values with the Project before filter, page, page-size, collapse, or reveal navigation. Any positive or negative draft blocks navigation and leaves Project, history, autosave, selection, and Browser location unchanged. The warning provides an explicit current-page discard action that restores both widget values from the Project without saving. Hidden-page widget values are not inspected, and no second draft model is introduced.

Browser state is session-only:

- filter;
- page;
- page size;
- collapsed typed group keys;
- one-shot notice;
- latest rendered page line IDs for the unsaved-navigation guard;
- temporary filter, page-size, and page-number widget mirrors.

It survives Graph Edit/Gallery/Trash/workspace round trips and ordinary same-Project reruns. The canonical `reset_graph_project_session_state()` resets it only after successful Project replacement alongside other temporary Graph UI state. Failed Project Open returns before that reset. Browser callbacks do not modify the Project, current/focused/highlighted Illustration, Graph selection, history, save state, or Gallery state.

## Compatibility and non-goals

This slice adds no Project or PromptLine schema, settings value, saved scope, Scene runtime object, shared Gallery resolver, background worker, filesystem watcher, persistent index, or thumbnail-cache format. Gallery pagination, Gallery Scene collapse, Gallery selections, and Gallery Preview/Apply state keep independent owners. Broader editor virtualization, Candidate pagination, inspector relocation, and Selected Illustration/Workbench redesign remain outside this Pro v1 slice.
