# genie-spaces-content

The **content monorepo** for the Genie/AI-BI promotion accelerator — the promotable artifacts
(Genie Space definitions, AI/BI dashboards, seed data) that get promoted from dev to prod.

This repo is the **PR target** for the promotion pipeline: the
[`genie-promote-cicd`](https://github.com/malcolndandaro/genie-promote-cicd) app opens a
`promote/<slug>` PR here for each Genie Space promotion, and this repo's CI (which checks out the
app repo for its pipeline logic) runs the deterministic checks + the governed deploy behind a
Steward approval gate.

## Layout

```
src/
├── genie/        # per-space Genie Space definitions (serialized_space + .title + .access.json sidecars)
├── dashboards/   # AI/BI (Lakeview) dashboard JSON
└── setup/        # synthetic seed data for the demo domain
```

## Why a separate repo

The app engine/tooling (FastAPI, Svelte, the reviewer, CI workflow *logic*) lives in
`genie-promote-cicd`; this repo holds **only** the promotable content. See that repo's
`docs/adr/` and the `app-ux-overhaul` design decisions (D9, RS2, GR5) for the split rationale —
in short: content and engine evolve on different cadences, and a non-technical business user
authoring a Genie Space should never see the app's source.

Promotion history + audit is **not** in this repo's git log — it lives in the app's Lakebase
store (the authoritative record). This repo is a fresh start; its history begins at the split.
