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
points execute this English-named core directly.  The temporary `启动.py`
compatibility shim was removed after callers migrated.

## Completed batch 7: plugin runtime implementation

`plugin_system.py` now owns the real controller base class, Studio message
handlers, fixed-step drivers, safe dispatch and plugin error isolation.
Runtime and algorithm code now use the English plugin core directly.  The old
`插件系统.py` compatibility shim was removed after its last callers migrated.

## Completed batch 8: project and plugin assembly implementations

`project_registry.py` now owns project JSON loading, algorithm discovery,
parameter persistence and legacy algorithm-id normalization.
`plugin_assembler.py` now owns dynamic algorithm imports, plugin-class discovery,
compatibility checks and project assembly.  The old `项目.py` and `装配器.py`
compatibility shims were removed after their last callers migrated.

## Completed batch 20: migration cleanup

Removed obsolete compatibility shims for the plugin system, project registry,
plugin assembler and runtime startup.  Removed the retired shell-fingerprint
check and the one-off macOS view-composition spike scripts; Git history remains
the source for those completed architecture experiments.

## Completed batch 9: model loading and model state bridge

`model_loader.py` now owns MuJoCo XML loading, Windows non-ASCII path fallback,
and automatic composition with the shared scene.  `model_bridge.py` now owns the
model library, persistent model/project settings, model-switch commands and the
model/project state publishers used by the UI.  Active runtime and Windows-host
callers use their English public APIs.

At that stage, `模型加载.py` and `模型桥.py` remained thin compatibility shims.
The model-loading shim was removed in batch 14 and the model-bridge shim in
batch 15 after their callers and wire contracts moved.

## Completed batch 10: experiment bridge implementation

`experiment_bridge.py` now owns experiment selection, Run/Pause/Reset event
handling, timed result recording, automatic stop and result export.  The shared
runtime and command/contract lookup tables resolve the English module directly.

The experiment wire contract was migrated in contract version 17 together with
its React consumers: `experiment.state`, `command.experiment`, and their payload
fields are English.  The temporary `实验桥.py` shim has been deleted; this feature
chain no longer depends on a Chinese module or compatibility alias.

The plugin runtime now resolves the English `receive_model()` lifecycle hook
first and falls back to legacy `收到模型()`, allowing new internal plugins to stay
English without breaking existing controller plugins.

## Completed batch 11: planning bridge and wire contract

`planning_bridge.py` directly replaces the removed `规划桥.py`.  Runtime loading,
planning commands, result snapshots, React state and command calls now use
`PlanningCommand`, `PlanningResult`, `TrajectoryPlanner`, `command.planning` and
`planning.result`.  Contract version 18 migrates every planning payload field to
English; no Chinese planning-bridge compatibility module remains.

## Completed batch 12: trajectory planning core

`trajectory_planning.py` directly replaces `轨迹规划.py`.  The planning kernel,
its dataclasses, functions, report fields and local identifiers now use English
names.  `planning_bridge.py` and `trajectory_planning_selfcheck.py` call that
English API directly; the former Chinese module and self-check filename were
removed without compatibility shims.  User-facing Chinese diagnostics and GUI
labels remain unchanged.

## Completed batch 13: inverse kinematics core

`inverse_kinematics.py` now owns the damped-least-squares solver, end-effector
discovery, joint-limit handling and Cartesian-waypoint conversion directly.
The former `逆解.py` implementation and the English wrapper around it were
replaced by one English implementation, with no compatibility module or
Chinese Python identifiers left in this feature chain.

## Completed batch 14: model loading core

`model_loader.py` now uses English identifiers throughout its XML, include-file,
asset, Windows-path fallback and shared-scene composition code.  Runtime callers
use the English module directly, and the former `模型加载.py` compatibility shim
has been deleted.  Model XML paths and Chinese GUI labels are intentionally
unchanged because they are data and user-facing text, not Python identifiers.

## Completed batch 15: model management and wire contract

`model_bridge.py` now directly owns the model library, model switching,
model/project snapshots, algorithm-selection commands and related publishers
with English Python identifiers.  Contract version 19 migrates the active wire
topics to `model.state`, `model.library`, `project.state`, `command.model` and
`command.algorithms`, including their payload fields and React consumers.  The
former `模型桥.py` compatibility shim has been deleted.  Existing Chinese model
catalog keys and GUI labels remain data or user-facing text and are therefore
outside this code-identifier migration.

## Completed batch 16: simulation and gravity control

`simulation_control.py` now directly owns the Run/Pause/Reset gate, gravity
switching, simulation-speed command and simulation-state publisher with English
Python identifiers.  Contract version 20 migrates this wire chain to
`command.simulation`, `command.gravity` and `simulation.state`, with English
payload fields shared by Python and React.  The former `重力桥.py` implementation
has been deleted.  Chinese button labels and operator-facing status messages
remain user-interface text rather than code identifiers.

## Completed batch 17: parameter editing and transactions

`parameter_bridge.py` now directly owns parameter discovery, live parameter
updates, atomic multi-parameter transactions, rollback and parameter-table
publishing.  Contract version 21 migrates this feature chain to
`parameter.table`, `parameter.transaction`, `command.parameters` and
`command.parameter_transaction`, with English payload fields shared by Python
and React.  The transaction self-check now exercises the English API directly,
and the former `参数桥.py` module has been deleted without a compatibility shim.

## Completed batch 18: controller parameter API

The controller parameter extension point now uses
`adjustable_parameters()` and `set_parameter()` throughout the base plugin,
all six tunable built-in plugins, project-parameter restoration, algorithm
metadata collection and the parameter bridge.  Parameter declarations now use
`value`, `range`, `step` and `unit`.  The parameter bridge no longer probes the
former Chinese method names or declaration fields, and the naming check rejects
any reintroduction of those removed methods.  Existing experiment parameter
keys such as `KP`, `KD`, `积分上限` and `监看关节` remain unchanged data, so saved
projects continue to load without conversion.

## Completed batch 19: plugin metadata and lifecycle API

Built-in controller and support plugins now expose English metadata
(`name`, `english_name`, `version`, `description`, `author`, `takes_control`)
and English lifecycle hooks (`receive_model`, `check_model_compatibility`,
`bind_model_path`, `model_changed`, `step`, `metrics`, `status`).  Explicit
module exports use `plugin_class`.  The assembler, controller registry,
parameter and metric collectors, project-parameter restoration, recorder
metadata path and lifecycle event fields all consume that API directly; no
runtime fallback probes the former Chinese names.  User-facing plugin names,
metric labels and persisted metadata keys remain Chinese data where appropriate.

## Recommended migration order

1. Entry points and command-line options.
2. Runtime core modules and their public interfaces.
3. Controller/plugin modules.
4. Configuration directories and schemas.
5. Model/tool/output directory names and packaging paths.

Chinese UI text is not part of this migration; translating the interface and
renaming internal code are separate concerns.
