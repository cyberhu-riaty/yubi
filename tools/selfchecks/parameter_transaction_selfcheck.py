#!/usr/bin/env python3
"""Verify that a parameter transaction either commits fully or changes nothing."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "runtime"))

details: list[str] = []
passed = 0
failed = 0


def check(condition: bool, description: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        details.append(f"  ✓ {description}")
    else:
        failed += 1
        details.append(f"  ✗ {description}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--brief", action="store_true")
    args = parser.parse_args()

    import parameter_bridge
    import plugin_assembler
    import plugin_system

    plugins, _ = plugin_assembler.assemble_project(
        {"算法": [{"插件": "joint_pd_control"}], "参数": {}},
        "事务自检",
    )
    registry = plugin_system.SafeRegistry(plugins)
    emitted: list = []
    persisted: list = []
    applier = (
        parameter_bridge.ParameterApplier(
            persist_parameters=lambda name, values: persisted.append((name, values))
        )
        .rebind(registry)
        .bind_publisher(emitted.append)
    )
    instance = list(applier._plugin_by_name.values())[0]  # noqa: SLF001
    plugin_name = str(instance.name)
    kp_name = f"{plugin_name}·KP"
    kd_name = f"{plugin_name}·KD"

    def submit(items: dict[str, float]):
        emitted.clear()
        persisted.clear()
        applier.on_transaction(parameter_bridge.ParameterTransactionCommand(
            action="apply",
            parameters=tuple(
                {"full_name": name, "value": value}
                for name, value in items.items()
            ),
        ))
        return emitted[-1] if emitted else None

    original_kp, original_kd = float(instance.KP), float(instance.KD)
    result = submit({kp_name: original_kp + 50.0, kd_name: original_kd + 5.0})
    check(result is not None and result.state == "committed",
          f"① 合法提交 → {getattr(result, 'state', '无')}")
    check(
        abs(float(instance.KP) - (original_kp + 50.0)) < 1e-9
        and abs(float(instance.KD) - (original_kd + 5.0)) < 1e-9,
        f"① 两个参数都真的生效（KP={instance.KP}、KD={instance.KD}）",
    )
    check(len(getattr(result, "changes", ())) == 2,
          f"① 差异表 {len(getattr(result, 'changes', ()))} 条（应为 2）")
    check(len(persisted) == 1, "① 提交时写了存盘（1 次）")

    before = (float(instance.KP), float(instance.KD))
    result = submit({kp_name: before[0] + 100.0, kd_name: 99999.0})
    check(result is not None and result.state == "rolled_back",
          f"② 越界提交 → {getattr(result, 'state', '无')}")
    check((float(instance.KP), float(instance.KD)) == before,
          f"② 失败后原值逐项相等（{instance.KP}、{instance.KD}）")
    check(len(persisted) == 0, "② 回滚时没有存盘")

    result = submit({"不存在的插件·KP": 1.0})
    check(result is not None and result.state == "rolled_back", "③ 未知插件 → 回滚")
    check(len(getattr(result, "failures", ())) >= 1, "③ 给出了失败原因")

    result = submit({f"{plugin_name}·没有这个参数": 1.0})
    check(result is not None and result.state == "rolled_back", "④ 未知参数 → 回滚")

    result = submit({})
    check(result is not None and result.state == "rolled_back", "⑤ 空改动 → 明确回执")

    if not args.brief:
        print("=" * 78)
        print("  参数事务自检（全成功 或 一个都不动）")
        print("=" * 78)
        print("\n".join(details))
        print()
    print("=" * 74)
    print(f"  结果：{passed} 通过 / {failed} 失败")
    print("=" * 74)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
