# Naming policy and migration boundary

The project is being migrated from a Chinese internal module layout to a stable
ASCII/English engineering interface.  The migration is incremental so existing
experiments and plugins keep working during the transition.

## New code

- Python packages, module filenames, public classes/functions and CLI options use English ASCII names.
- Runtime configuration keys and machine-readable identifiers use English ASCII names.
- User-visible UI copy, experiment display names, comments and learning notes may remain Chinese.
- Files are UTF-8 without BOM.

## Compatibility boundary

- `run_yubi.py`, `run_experiment_cli.py` and `compare_experiments_cli.py` are the supported ASCII entry points.
- The legacy `软件/`, `算法库/`, `实验/`, `项目/`, `模型/` and `工具/` paths remain valid for now.
- Do not rename a legacy module without first adding an English replacement and a thin compatibility shim.
- A migration is complete only after imports, JSON paths, frontend build paths, tests and documentation all use the new name.

## Completed batch 1: experiment and controller path

The following English public modules are now available and are used by the
registered experiment/controller runtime:

- `plugin_system.py`, `ui_bridge.py`, `command_bridge.py`
- `model_loader.py`, `inverse_kinematics.py`
- `project_registry.py`, `plugin_assembler.py`
- `runtime_engine.py`, `console_support.py`

Run `python scripts/check_naming.py` to ensure migrated callers do not regress to
direct legacy imports.  This check intentionally permits untouched legacy files;
it enforces the migration boundary rather than pretending the whole repository is
already English-only.

## Completed batch 2: desktop runtime path

The desktop launcher and main-window runtime now depend on English public APIs:

- `desktop_app.py`, `official_api.py`, `web_bridge.py`
- `simulation_control.py`, `model_bridge.py`, `contract.py`
- `platform_adapters/`

The existing Chinese implementation modules remain behind these interfaces as a
temporary compatibility layer.  New launchers and runtime callers must use the
English modules; a later batch can rename or remove legacy files after all
remaining callers and packaging paths have moved.

## Completed batch 3: browser runtime path

The standalone browser host now uses the same English runtime APIs as the
desktop host.  Use `run_yubi_web.py` instead of invoking the legacy Chinese
module path directly.  Both hosts now call `web_bridge.start()` and
`runtime_engine.start()` with English keyword arguments.

## Completed batch 4: active plugin dependencies

The legacy-named plugins still keep their filenames and UI-facing metadata for
project compatibility, but their Python imports now use English public APIs.
New wrappers cover parameter identification, identification messages and
recording commands:

- `parameter_identification.py`
- `identification_bridge.py`
- `recording_bridge.py`

Do not duplicate a plugin under a second filename yet: the algorithm discovery
system would expose both copies.  Plugin filenames and project JSON references
must move together in a later compatibility-aware batch.

## Completed batch 5: plugin filenames and JSON identifiers

The shared plugin implementations now use ASCII filenames, and current project
and experiment JSON files reference their English identifiers.  Legacy Chinese
identifiers are normalized through `project_registry.ALGORITHM_ALIASES`, so old
project files remain loadable without keeping duplicate plugin files.

Examples: `数据录制` → `data_recorder`, `轨迹目标执行` →
`trajectory_target_player`, and `关节pd控制` → `joint_pd_control`.

## Completed batch 6: simulation runtime implementation

`runtime_engine.py` now contains the real shared simulation runtime instead of
wrapping the legacy module.  Desktop, browser and headless experiment entry
points execute this English-named core directly.  `启动.py` is now only a small
compatibility shim for older tools and external scripts.

## Completed batch 7: plugin runtime implementation

`plugin_system.py` now owns the real controller base class, Studio message
handlers, fixed-step drivers, safe dispatch and plugin error isolation.
`插件系统.py` is only a compatibility shim.  Runtime and algorithm code now use
the English plugin core directly.

## Completed batch 8: project and plugin assembly implementations

`project_registry.py` now owns project JSON loading, algorithm discovery,
parameter persistence and legacy algorithm-id normalization.
`plugin_assembler.py` now owns dynamic algorithm imports, plugin-class discovery,
compatibility checks and project assembly.  `项目.py` and `装配器.py` remain only
as compatibility shims.

## Completed batch 9: model loading and model state bridge

`model_loader.py` now owns MuJoCo XML loading, Windows non-ASCII path fallback,
and automatic composition with the shared scene.  `model_bridge.py` now owns the
model library, persistent model/project settings, model-switch commands and the
model/project state publishers used by the UI.  Active runtime and Windows-host
callers use their English public APIs.

`模型加载.py` and `模型桥.py` remain thin compatibility shims, so older tools and
third-party plugins can continue importing the former names during the gradual
migration.

## Completed batch 10: experiment bridge implementation

`experiment_bridge.py` now owns experiment selection, Run/Pause/Reset event
handling, timed result recording, automatic stop and result export.  The shared
runtime and command/contract lookup tables resolve the English module directly.
`实验桥.py` remains a compatibility shim for older callers.

The current frontend contract still uses Chinese wire field names.  Those keys
are deliberately unchanged in this batch because changing them requires a
versioned contract and matching React migration; they are no longer used as the
implementation's internal variable or method names.

The plugin runtime now resolves the English `receive_model()` lifecycle hook
first and falls back to legacy `收到模型()`, allowing new internal plugins to stay
English without breaking existing controller plugins.

## Recommended migration order

1. Entry points and command-line options.
2. Runtime core modules and their public interfaces.
3. Controller/plugin modules.
4. Configuration directories and schemas.
5. Model/tool/output directory names and packaging paths.

Chinese UI text is not part of this migration; translating the interface and
renaming internal code are separate concerns.
