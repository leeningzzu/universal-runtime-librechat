# Windows Product Shell & Packaging｜Cross-Chat User-Journey Contract Archive R001

STATUS = PRODUCT_CONTRACT_CANDIDATE / SUPPORTING_CROSS_CHAT_ARCHIVE
AUTHORITY_STATUS = NON_AUTHORITY_UNTIL_EXPLICIT_ACCEPTANCE_OR_PROMOTION
CURRENT_ROUTE_CHANGE = NO
CURRENT_UNIQUE_NEXT_ACTION_PRESERVED = HUMAN_PROJECT_TO_WEBCODEX_EFFECTFUL_LOCAL_WORK_SAME_CHAT_RETEST_R002
PRIMARY_CONSUMERS = PRODUCT_SHELL_BASELINE_FREEZE | PORTABILITY_UPDATE_ROLLBACK | WINDOWS_DISTRIBUTION_INSTALLER_FREEZE

## 1. Purpose

Consolidate the repeatedly discussed Windows shell/packaging decisions into one user-centered contract so they survive Chat rollover without turning current packaging choices into premature Stable Authority.

This archive does not choose the final EXE/installer/updater technology, does not modify Production, and does not replace the current Project→WebCodex Human Gate.

## 2. Evidence basis

Exact current-project artifacts:

- `artifacts/handoff/WEB_R004_PRODUCT_BASELINE_ACCEPTANCE_R001/NEW_CHAT_HANDOFF_WEB_R004_PRODUCT_BASELINE_ACCEPTANCE_R001.md`
  - SHA256 `939efae03731ce792b8220e48ec7cc465593b63227b8488997647127c9c6a5b5`
  - establishes Daily Entry/startup/repair, rollback readiness and functional S1 thin shell through existing Daily Entry + Edge app-mode.
- `artifacts/handoff/WEB_R004_PRODUCT_BASELINE_ACCEPTANCE_R001/BUILD_STATUS_WEB_R004_PRODUCT_BASELINE_ACCEPTANCE_R001.md`
  - SHA256 `68fa9142f900246382345ca55de03c315167531c5a0657b16a996f4f9e5c75c1`
  - records S1 functional thin shell PASS and defers Tauri native EXE and S2 installer/update/rollback.
- `artifacts/handoff/PROJECT_FIRST_SETTLED_ROUTE_REBIND_R001/CURRENT_ROUTE_LOCK_R001.md`
  - SHA256 `412adaad21b936375e98d67e7e067fe923581fe16a4caa6e71e34028e1996497`
  - preserves the Daily/Thin Shell node, later Product Shell Baseline Freeze, Portability/Update/Rollback and Windows Distribution/Installer Freeze.
- `artifacts/handoff/R012_R021_CURRENT_CANDIDATE_WEBCODEX_COMPOSITION_CLOSURE_R001/SHELL_NODE_ROUTE_PREFLIGHT_R001.md`
  - SHA256 `c426f9fdf43bc7381d52a59313789c80cdf930b6293d150d6c2a867bb43a6604`
  - forbids R021 from choosing Tauri/MSIX/Velopack, freezing packaging, rebuilding LibreChat UI or creating a second shell.
- `artifacts/handoff/R012_R020_PROJECT_CORE_NATURAL_USE_ACCEPTANCE_R001/R012_R020_PROJECT_CORE_NATURAL_USE_ACCEPTANCE_R001.md`
  - SHA256 `3d42cdf95679920fefe55118bfb06418bc7045308349fe782355f85228c76f26`
  - proves the current Daily launcher ownership path, network-neutral product configuration and zero-manual Agent/Skill/MCP target.

Cross-Chat contextual reconstruction, not formal Authority:
- 2026-09-18: user-facing working name accepted as `Inquiry Desk`; `Universal Runtime` remains internal Authority/control-plane name.
- 2026-09-18/19: current accepted route recorded as `Universal Runtime.lnk → Daily launcher → Edge app-mode → LibreChat`; launcher already owns prerequisite checks, component startup, health wait, existing-window activation and repair entry.
- 2026-09-19: Tauri side-by-side preflight found WebView2 present but Rust/Cargo/Tauri/C++ build prerequisites absent; no dependency installation or Candidate creation occurred.
- 2026-09-20: current thin shell preserved; native EXE/installer/update/rollback deferred until the product/Pack/portability route justifies it.
- 2026-09-20 onward: Edge/PWA/app-mode first; Tauri v2/WebView2 only for proven lifecycle gaps; MSIX/App Installer/WinGet/Velopack remain S2 comparators.
- 2026-09-20 onward: WebCodex and Agents remain optional capabilities, not Core launch prerequisites; proxy/VPN/Clash remains user environment and cannot be an internal product dependency.
- 2026-09-27: Tauri 2.x remained a preferred native-shell comparator; updater/signing/downgrade/rollback semantics remained future S2 work, not a current implementation choice.

## 3. Settled role map

| Role | Owns | Must not own |
|---|---|---|
| Inquiry Desk thin shell | launch, window, user-visible health/repair/update entry | Chat/Project reimplementation; Runtime Authority |
| LibreChat | Chat, history, Projects, files, Memory/Library/Knowledge, native tools/MCP/Agents | Windows filesystem or Promotion Authority |
| Universal Runtime | Authority, Project/Source/Memory/Pack binding, permission, revision, Promotion, audit | desktop window framework or duplicate chat UI |
| Local Action Host | Windows canonical read/write/process/git/test inside bound scope | Project identity, generic SaaS connector platform |
| Installer/updater route | install, prerequisite/service lifecycle, update/repair/rollback/uninstall | Authority migration by convenience |
| MCP | optional interoperability transport | Project identity, filesystem permission, Authority |
| Provider such as ChatAnywhere | optional model/provider route | shell identity, hidden fallback, internal proxy dependency |

## 4. Current accepted S1 baseline

`Desktop shortcut / current product entry → owner-managed launcher → Edge app-mode → LibreChat`

This baseline remains accepted because it already delivers a functional one-window Web/Desktop experience and owns current startup/repair composition. It is not the final distribution freeze and must not become a reason to skip S2.

DO NOW:
- preserve one product entry;
- preserve LibreChat as the current primary/replacable shell;
- improve capabilities inside the existing shell;
- keep rollback and Developer/Production separation;
- record material Edge/app-mode limitations when natural use proves them.

DO NOT NOW:
- build Electron/Tauri/WinUI/WPF/Wails merely for polish;
- choose MSIX/Velopack/Tauri updater prematurely;
- create a second LibreChat shell;
- expose Docker/MCP/ports/PowerShell to normal users;
- make WebCodex, Agent selection, MCP configuration or a proxy a launch prerequisite.

## 5. Normal-user journey contract

### 5.1 First installation / first run

Target:
1. User starts one signed installer or managed portable entry.
2. Product detects or installs only the selected route's required prerequisites.
3. Product starts its internal components and opens one Inquiry Desk window.
4. User completes only unavoidable authentication, provider credential or local-folder consent.
5. Product opens a usable Project/Chat surface.

The user must not:
- open PowerShell/CMD;
- locate install/runtime files the machine can locate;
- install/configure Docker, MCP, WebCodex or a proxy manually;
- enter ports, container names or Runtime paths;
- understand Agent/Skill/MCP/Pack/SHA/Promotion jargon for ordinary use.

### 5.2 Daily launch

Target = one user action from desktop/Start menu/taskbar to an existing or new product window.

The product/launcher owns:
- duplicate-window prevention or existing-window focus;
- prerequisite/service health checks;
- bounded startup/repair;
- clear progress/error state;
- authentication/session restoration when still valid;
- Project/history/data continuity.

Normal daily use must not display a terminal window as the primary UX.

### 5.3 Normal work

Default flow:

`Open Inquiry Desk → Project → New Chat → direct request`

Manual Agent selection = 0 by default. Manual Skill selection = 0. Manual MCP configuration = 0. A local file/action request may trigger the bound Local Action capability, but read-only and effectful permissions remain distinct and effectful work requests one complete approval.

### 5.4 Failure and repair

A local UI/runtime/provider failure must be classified before repair:
- shell/component unavailable;
- local data unavailable;
- provider/network unavailable;
- local workspace binding unavailable;
- update mismatch.

Repair must:
- preserve Project/Mongo/Library/Memory/user files by default;
- never silently factory-reset data;
- avoid proxy/tunnel workarounds;
- return one actionable recovery path or one copyable diagnostic bundle;
- retain an exact rollback route.

### 5.5 Update and rollback

Update discovery may be automatic; installation/Promotion is Candidate-first and explicit when material.

An accepted update must preserve:
- authentication/session where technically compatible;
- Projects, conversations, files, Memory and Library;
- logical workspace bindings;
- previous accepted version for rollback;
- audit/provenance.

Rollback restores the product version/binding; it does not rewrite history or delete newer user data silently.

### 5.6 Move to another Windows PC

Project/export identity contains logical workspace IDs, not old usernames, drive letters, install roots or raw WebCodex/MCP handles.

On the new supported Windows PC:
1. product imports/restores Project data;
2. machine-local resolver locates or asks once for the local workspace only when machine discovery cannot resolve it;
3. resolver binds the current executor implementation;
4. Project identity/history remain unchanged;
5. exact rebind/rollback receipt is produced.

### 5.7 Uninstall

Uninstall must distinguish:
- remove product code only;
- retain user data for reinstall/migration;
- explicitly remove user data.

No uninstall route may silently delete Project history, Source/Artifact data or external canonical folders.

## 6. Native EXE / packaging re-entry triggers

Re-enter native shell/installer technology selection when at least one material trigger is proven:
- second-machine installation or ordinary-user setup burden;
- Start-menu/desktop integration quality;
- true single-instance/window focus/window-state restore;
- tray/background/autostart lifecycle;
- deep link, file association or native notification;
- reliable host-side Runtime/sidecar lifecycle;
- signed install/update channel;
- repair/uninstall/rollback;
- material Edge app-mode limitation;
- published Windows support and enterprise deployment need.

No single trigger preselects Tauri, MSIX, Velopack or another technology. At S2, compare complete lifecycle routes and choose the one that deletes the most custom/user burden with the lowest authority, dependency and removal cost.

## 7. Technology status — current, non-Authority

- Edge app-mode / current launcher: accepted functional S1 baseline.
- Tauri v2 + WebView2: preferred comparator for native window/tray/single-instance/autostart/deep-link/window-state/sidecar needs; not adopted now.
- Tauri updater: comparator only; signed-version, downgrade and Runtime-authorized rollback remain required if selected.
- MSIX / App Installer / WinGet: comparator for install/update/distribution policy.
- Velopack: comparator for update/channel/delta/rollback gaps.
- Electron: defer unless evidence proves total lifecycle value exceeds footprint/duplication.
- direct WinUI/WPF/WebView2: defer unless a narrow native boundary cannot be met by a mature thinner route.
- Wails: defer unless current stable Windows lifecycle evidence becomes stronger.
- Docker/container runtime: current implementation detail only; S2 must decide whether installer-managed container lifecycle is acceptable or a native service route deletes more user burden.

## 8. Acceptance matrix for Product Shell / Distribution Freeze

| Scenario | Required observable result |
|---|---|
| Clean first install | No developer checkout knowledge; no manual proxy/Docker/MCP/executor setup |
| Repeat launch | One existing or new window; no duplicate service stack |
| Valid login/session | User resumes without unnecessary re-authentication |
| Provider outage | Local shell/history/Projects remain available; provider failure is explicit |
| Component failure | Bounded repair preserves user data |
| Update Candidate | Old/new exact versions known; data continuity proven |
| Rollback | Previous accepted product version restored without history rewrite |
| Different username/location | Product starts; no developer-machine path identity leak |
| Workspace move | Logical binding rebinds without Project identity migration |
| Uninstall/reinstall | User chooses data retention; reinstall restores retained data |
| Local effectful work | One complete approval; result returns to the same Project Chat |
| Advanced diagnostics | Internal concepts available only when deliberately opened |

## 9. Negative acceptance / release blockers

BLOCK when normal use requires any of:
- internal HTTP/SOCKS proxy, VPN or tunnel;
- manual Docker/WSL/container/MCP/WebCodex setup;
- hard-coded developer username, drive, install root or raw executor handle in portable state;
- whole-drive container mount by default;
- terminal commands for ordinary launch/repair/update;
- repeated manual Agent/Skill/MCP selection;
- silent provider fallback;
- update/repair that resets user data;
- no exact rollback;
- primitive/component health presented as complete user-journey PASS.

## 10. Open decisions / proof ceiling

NOT YET PROVEN:
- final supported Windows matrix and architecture set;
- final product name/installer filename;
- final installer/updater technology;
- installer-managed Docker/container route versus native services;
- signed update/channel and credential-store route;
- full fresh-machine held-out acceptance;
- native tray/autostart/deep-link/file-association scope;
- ChatAnywhere provider acceptance;
- final human Project→Local Action effectful approval and same-chat result-return retest.

Therefore:

PRODUCT_SHELL_BASELINE_FREEZE = NOT_RUN
PORTABILITY_UPDATE_ROLLBACK = NOT_RUN
WINDOWS_DISTRIBUTION_INSTALLER_FREEZE = NOT_RUN
PRODUCT_PASS = NO
PROGRAM_PASS = NO

## 11. Route preservation

This archive is a supporting governance/product-contract correction. It does not replace the active route.

CURRENT_UNIQUE_NEXT_ACTION = HUMAN_PROJECT_TO_WEBCODEX_EFFECTFUL_LOCAL_WORK_SAME_CHAT_RETEST_R002
NEXT_REQUIRED_SUCCESSOR_AFTER_CURRENT_STAGE = LOCAL_PACK_LIFECYCLE_R001
