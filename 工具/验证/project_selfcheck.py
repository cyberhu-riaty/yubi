"""
project_selfcheck.py —— 项目 / 模型 / 算法 三者的交叉一致性自检（方案 C 专用）

为什么需要它
----------------------------------------------------------------------------
方案 C 把"用哪些算法"从代码搬到了数据（`项目/*.json` + `算法库/`）。数据化的代价是
**对不上不会报错，只会静默少东西**：
    · 项目里写了一个算法名，但算法库里没有那个文件 → 装配报告里一行 ✗，容易没看见
    · 算法库里躺着一个从没被任何项目用到的算法 → 你以为在用，其实从没加载过
    · 两个算法文件里的插件类**重名** → 参数面板按"插件名"寻址，会串台
    · 项目指向的模型文件被挪走/改名 → 点开这个项目就是空场景

这些都属于"改一处忘了改另一处"，正是应该交给脚本看住的那类问题。
本脚本只读不写（`--修复` 除外，它只补 `_说明` 之类的注释字段，不动你的算法列表）。

用法
----------------------------------------------------------------------------
    .venv/bin/python 工具/验证/project_selfcheck.py
    .venv/bin/python 工具/验证/project_selfcheck.py --详表

退出码：0 = 全部通过；1 = 有错误（可直接接进 pre-commit 或 工具/跑检查.sh）
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

# ---- 定位包根：本文件在 优化（…）/验证/ 下，上两级是包根 ----
directory = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(directory))
SOFTWARE = os.path.join(ROOT, "软件")
if SOFTWARE not in sys.path:
    sys.path.insert(0, SOFTWARE)

import project_registry as projects                                       # noqa: E402
import plugin_assembler as assembler                                      # noqa: E402


class CheckResults:
    """收集"通过 / 警告 / 错误"三类结论，最后统一决定退出码。

    为什么警告不算失败：有些问题是**设计选择**而不是缺陷（比如一个算法暂时没被
    任何项目用到，可能是在等一个新的实验项目）。警告打出来给人看，但不拦提交。
    """

    def __init__(self) -> None:
        self.passed = 0
        self.warnings: list[str] = []
        self.errors: list[str] = []

    def check(self, description: str, condition: bool, failure_reason: str = "") -> bool:
        if condition:
            self.passed += 1
        else:
            self.errors.append(f"{description} —— {failure_reason}" if failure_reason else description)
        return condition

    def warn(self, description: str) -> None:
        self.warnings.append(description)


def find_undefined_globals(function, module) -> list[str]:
    """从一个函数的字节码里找出"被当成全局名读取、但模块里没有"的名字。

    ★ 为什么要走字节码（而不是"调一次试试"）：
      第一版实现是"给每个消息处理器喂一个假事件、看它抛不抛异常"。它对
      `展示姿态插件` 那个真实的 bug **完全无效** —— 因为 `改暂停状态()` 开头是

          if not self._关闭:      # 假事件里 _关闭 是 False
              return False        # ← 提前返回，后面用 `sim` 的那段根本没执行

      也就是说"冒烟调用"只覆盖了提前返回的那条分支，检查是**假绿**的。
      要抓住"搬运漏导入"，必须做**静态**检查，不能靠跑一遍。
      （实测确认过：拿掉 `sim` 的导入，冒烟版仍然全绿。）

    原理与边界：
      · `LOAD_GLOBAL` 在 CPython 3.10 里只由 `LOAD_FAST` 指令消解遮蔽 ——
        所以"同一个名字、前面紧邻的是 LOAD_FAST"就是局部赋值的情况，跳过。
      · 只对**本模块自己定义**的函数/方法做检查（不递归进 import 来的函数）。
      · 名字在内建里（`len`/`print`…）通过 `builtins` 兜底，不算未定义。
    """
    import builtins
    import dis

    if not hasattr(function, "__code__"):
        return []
    code = function.__code__
    names = set(code.co_names) | {c for c in code.co_consts if isinstance(c, str)}
    undefined: list[str] = []
    previous = None
    for instruction in dis.get_instructions(function):
        if instruction.opname == "LOAD_GLOBAL" and instruction.argval not in ("__name__", "__file__"):
            name = str(instruction.argval)
            if name in code.co_varnames:              # 同名局部变量会遮蔽全局 → 误报，跳过
                previous = instruction
                continue
            if not hasattr(module, name) and not hasattr(builtins, name):
                undefined.append(name)
        # 记录"上一条是不是 LOAD_FAST 同名"（判断遮蔽）
        previous = instruction
    return sorted(set(undefined))


def check_algorithm_names(path: str) -> list[str]:
    """扫一个算法文件：所有**本文件定义**的函数/方法里，有没有用未定义的全局名。"""
    import ast
    import types

    findings: list[str] = []
    try:
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=path)
    except SyntaxError as exc:
        return [f"语法错误：{exc}"]

    module, reason = assembler.import_algorithm_file(path)
    if module is None:
        return []                              # 导入失败在上面已经报过了，不重复
    filename = os.path.abspath(path)

    plugin_class, reason = assembler.find_plugin_class(module)
    if plugin_class is None:
        return []                              # 定位不到插件类，上面也报过了
    filename = os.path.abspath(path)

    def visit(function, display_name: str) -> None:
        if not callable(function) or not hasattr(function, "__code__"):
            return
        if os.path.abspath(function.__code__.co_filename) != filename:
            return                             # import 来的，不查（不是本文件的代码）
        missing = find_undefined_globals(function, module)
        if missing:
            findings.append(f"{display_name} 用到未定义的名字：{'、'.join(missing)}")
        # 内层函数 / lambda 是独立 code object，单独扫一遍
        for constants in function.__code__.co_consts:
            if isinstance(constants, types.CodeType):
                missing_inner = find_undefined_globals(constants, module)
                if missing_inner:
                    findings.append(f"{display_name}.{constants.co_name}() 用到未定义的名字："
                                f"{'、'.join(missing_inner)}")

    # ① 插件类自己的方法
    #   ★ 必须从**类**上取方法，不能在模块命名空间里找：本项目的算法方法
    #     （`改暂停状态` / `每步控制` …）全是类的方法，`getattr(模块, 名字)` 是 None，
    #     于是整个扫描一条都查不出来（第一版就是这么写的，**静默假绿**）。
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or getattr(plugin_class, "__name__", "") != node.name:
            continue
        for member in node.body:
            if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(getattr(plugin_class, member.name, None), f"{node.name}.{member.name}()")

    # ② 模块级的普通函数（算法文件里也可能有辅助函数）
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            visit(getattr(module, node.name, None), f"{node.name}()")
    return findings


def collect_assignment_names(node) -> set[str]:
    """从一个 AST 子树里收集所有"被赋值的名字"（含元组/列表解包）。

    ★ 为什么单独写一个：`a, b = f()` 的 target 是 `ast.Tuple` 而不是 `ast.Name`，
      只判断 `ast.Name` 会把整条赋值漏掉（实测误报过）。
      星号解包 `a, *rest = ...` 里的 `ast.Starred` 也要递归进去。
    """
    import ast

    findings: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
            findings.add(child.id)
        elif isinstance(child, (ast.AnnAssign, ast.AugAssign)):
            t = child.target
            if isinstance(t, ast.Name):
                findings.add(t.id)
        elif isinstance(child, ast.NamedExpr) and isinstance(child.target, ast.Name):
            findings.add(child.target.id)
    return findings


def find_undefined_entry_names(path: str) -> list[str]:
    """扫 `主程序.py` 里"被读取但从未被赋值/导入/声明"的名字。

    ★ 为什么专门给主程序做这一层（这是**闪退级**事故换来的）：
      方案 C 改造时把主程序里旧的局部变量名 `插件` 删掉了，
      但 `注册表 = 插件框架.安全注册表(插件)` 这一行漏改 ——
      于是**双击图标直接闪退**：`NameError: name '插件' is not defined`。

      更难受的是：当时"开窗冒烟测试"是全绿的 —— 因为它直接调
      `启动.启动外壳()`，绕过了 `主程序.main()`；而 `--检查` 又在开窗前就 `return 0`。
      于是这条真实路径**没有任何检查覆盖**。教训：入口必须有自己的检查，
      只测内部函数不算测过。

    实现：只做函数作用域内的名字解析；模块级名字（含条件分支里定义的）与内建算已知。
    `for` / 推导式 / `except as` / 内层 def-class-import / `with as` 都要收进局部名，
    否则会大量误报。
    """
    import ast
    import builtins

    try:
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=path)
    except SyntaxError as exc:
        return [f"语法错误：{exc}"]

    module_names_in_scope: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                module_names_in_scope.add((a.asname or a.name).split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            module_names_in_scope.add(node.name)
        else:
            # 模块级的任何赋值都要算已知：**元组解包**、注解赋值、增强赋值、walrus、
            # 以及 if/try/for/while 体内定义的。漏掉元组解包会误报 ——
            # 实测 `启动模型, 启动模型原因 = 决定启动模型()` 就被误报成未定义。
            module_names_in_scope.update(collect_assignment_names(node))

    # ★ 闭包：嵌套函数能读到**外层函数**的局部变量。
    #   第一版只收集"本函数自己的 Store + 模块级"，于是旧桌面入口里
    #   嵌套的 `收到状态()` 用到外层的 `视口槽` 就被误报成"未定义"。
    #   这里先把"每个函数的祖先链"建出来，检查时把祖先的局部名也算进来。
    ancestors: dict[int, list] = {}

    def _record_ancestors(node, link):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                ancestors[id(child)] = list(link)
                _record_ancestors(child, link + [child])
            elif isinstance(child, ast.ClassDef):
                _record_ancestors(child, link)          # 类体不算闭包作用域
            else:
                _record_ancestors(child, link)

    _record_ancestors(tree, [])

    def _walk_scope(node):
        """遍历本函数体，但**不进入**嵌套的函数/类/lambda。

        ★ 为什么要停边界：每个嵌套函数会**单独**被检查一次；
          如果外层也扫进去，嵌套函数的形参（如 `收到状态(快照)` 的 `快照`）
          在外层就是"未定义" → 假红。名字解析必须是不可穿透的作用域。
        """
        for child in ast.iter_child_nodes(node):
            # 嵌套函数/类**本身**要 yield（它的名字是本层的局部名），
            # 但它的**函数体**不能进（那是它自己的作用域）。
            yield child
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
                continue
            yield from _walk_scope(child)

    def _scope_names(function_node) -> set[str]:
        """这个函数**自己**引入的名字（不含祖先）。"""
        name: set[str] = {a.arg for a in function_node.args.args}
        name |= {a.arg for a in function_node.args.kwonlyargs}
        if function_node.args.vararg:
            name.add(function_node.args.vararg.arg)
        if function_node.args.kwarg:
            name.add(function_node.args.kwarg.arg)
        for child in _walk_scope(function_node):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                name.add(child.id)
            if isinstance(child, ast.arg):
                name.add(child.arg)
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and child is not function_node:
                name.add(child.name)
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                for a in child.names:
                    name.add((a.asname or a.name).split(".")[0])
            if isinstance(child, ast.ExceptHandler) and child.name:
                name.add(child.name)
            if isinstance(child, ast.comprehension) and isinstance(child.target, ast.Name):
                name.add(child.target.id)
            if isinstance(child, (ast.For, ast.AsyncFor)) and isinstance(child.target, ast.Name):
                name.add(child.target.id)
            if isinstance(child, ast.withitem) and isinstance(child.optional_vars, ast.Name):
                name.add(child.optional_vars.id)
        return name

    findings: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        local_names: set[str] = {a.arg for a in node.args.args} | {a.arg for a in node.args.kwonlyargs}
        if node.args.vararg:
            local_names.add(node.args.vararg.arg)
        if node.args.kwarg:
            local_names.add(node.args.kwarg.arg)
        declarations: set[str] = set()
        for child in _walk_scope(node):
            if isinstance(child, ast.Global):
                declarations.update(child.names)
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                local_names.add(child.id)
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and child is not node:
                local_names.add(child.name)
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                for a in child.names:
                    local_names.add((a.asname or a.name).split(".")[0])
            if isinstance(child, ast.ExceptHandler) and child.name:
                local_names.add(child.name)
            if isinstance(child, ast.comprehension) and isinstance(child.target, ast.Name):
                local_names.add(child.target.id)
            if isinstance(child, (ast.For, ast.AsyncFor)) and isinstance(child.target, ast.Name):
                local_names.add(child.target.id)
            if isinstance(child, ast.withitem) and isinstance(child.optional_vars, ast.Name):
                local_names.add(child.optional_vars.id)
        # 闭包：把每一层祖先函数自己引入的名字也算进"可见"
        outer_names: set[str] = set()
        for ancestor in ancestors.get(id(node), []):
            outer_names |= _scope_names(ancestor)
        missing = sorted({
            child.id for child in _walk_scope(node)
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)
            and child.id not in local_names and child.id not in module_names_in_scope and child.id not in declarations
            and child.id not in outer_names
            and not hasattr(builtins, child.id)
        })
        if missing:
            findings.append(f"{node.name}() 里用到未定义的名字：{'、'.join(missing)}")
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description="项目 / 模型 / 算法 一致性自检")
    ap.add_argument("--verbose", "--详表", action="store_true", help="逐项打印，而不只打印结论")
    args = ap.parse_args()

    summary = CheckResults()
    print("=" * 74)
    print("  校验项目 —— 项目 / 模型 / 算法 三者对不对得上（方案 C）")
    print("=" * 74)

    # ---- ① 算法库本身 ----
    algorithms = projects.discover_algorithms()
    summary.check("算法库非空", bool(algorithms),
            f"{projects.relative_to_package(projects.ALGORITHM_DIRECTORY)} 里一个算法都没有")
    algorithm_names = [d["plugin"] for d in algorithms]
    duplicates = sorted({n for n in algorithm_names if algorithm_names.count(n) > 1})
    summary.check("算法文件名互不重复", not duplicates, f"重复的是：{'、'.join(duplicates)}")

    # 每个算法文件都要能导入、且能唯一定位到一个插件类
    class_names: dict[str, list[str]] = {}
    import_failures: list[str] = []
    for d in algorithms:
        module, reason = assembler.import_algorithm_file(d["file"])
        if module is None:
            import_failures.append(f"{d['插件']}（{reason}）")
            continue
        plugin_class, reason = assembler.find_plugin_class(module)
        if plugin_class is None:
            import_failures.append(f"{d['插件']}（{reason}）")
            continue
        class_names.setdefault(plugin_class.__name__, []).append(d["plugin"])
    summary.check("每个算法文件都能导入并定位到唯一插件类", not import_failures,
            "；".join(import_failures))

    # 插件**类名**重名：装配器按类名去重，参数面板按插件名寻址，重名会串台
    duplicate_classes = {k: v for k, v in class_names.items() if len(v) > 1}
    summary.check("插件类名互不重复", not duplicate_classes,
            "；".join(f"{k} 出现在 {v}" for k, v in duplicate_classes.items()))

    # ---- ①-b 名字解析检查：抓"搬运漏导入"这类只有运行到才暴露的错误 ----
    #   为什么要静态查而不是"调一次"：调用只能覆盖到提前返回的分支。
    #   实测教训：`展示姿态插件` 从 重力桥.py 搬走时漏了 `sim` 导入，
    #   而 `改暂停状态()` 开头 `if not self._关闭: return False` 会提前返回 ——
    #   喂假事件的冒烟检查给了**假绿**，一开窗才每帧 NameError（然后被永久停用）。
    name_issues: list[str] = []
    for d in algorithms:
        name_issues.extend(f"{d['plugin']}：{p}" for p in check_algorithm_names(d["file"]))
    summary.check("算法文件里没有未定义的全局名（抓搬运漏导入）", not name_issues,
            "；".join(name_issues))

    # ---- ①-c 入口检查：主程序里有没有"未定义的名字"（闪退级事故的防线）----
    #   背景：`注册表 = 插件框架.安全注册表(插件)` 漏改成 `插件清单`，
    #   导致双击图标闪退；而开窗冒烟测试因为绕过 main() 而全绿。
    # ★ 入口可能有多个版本（自研窗口 / 官方 ImGui；发布版可能只带其中一个）。
    #   这里**按存在的那个查**，不写死文件名 —— 否则裁掉一个入口，整套校验就红。
    entry_candidates = ["desktop_app.py", "web_app.py"]
    entry_script = next((os.path.join(SOFTWARE, n) for n in entry_candidates
                   if os.path.exists(os.path.join(SOFTWARE, n))), "")
    entry_name = os.path.basename(entry_script) if entry_script else "（无入口）"
    if not entry_script:
        summary.check("找到至少一个启动入口", False, "软件/ 下没有 主程序*.py")
    else:
        entry_issues = find_undefined_entry_names(entry_script)
        summary.check(f"{entry_name} 里没有未定义的名字（会闪退）", not entry_issues, "；".join(entry_issues))

    # ---- ①-c2 每个软件模块都能 import（抓"类声明被写坏"这类问题）----
    #   为什么单独查这一条：本轮真出过一次 —— 加字段时注释插错位置，把
    #   `class 算法选择器:` 这一行连同类体吃进了上一个类的 docstring，于是
    #   `模型桥.py` 一 import 就抛 TypeError（报的是"消息类型不对"，
    #   根因却是**类嵌套错了**，症状很绕）。逐模块 import 能直接指出是哪个文件。
    import importlib
    # `native_host.py` 和 `runloop_timers.py` 依赖 macOS 的 PyObjC。
    # Windows 由 `platform_adapters/windows.py` 提供宿主；在 Windows 强行导入前两者
    # 只会得到缺少 objc 的假失败，并不能说明当前平台不可运行。
    skip_on_platform = {"runloop_timers", "native_host"} if sys.platform != "darwin" else set()
    module_names = sorted(
        os.path.splitext(f)[0] for f in os.listdir(SOFTWARE)
        if (f.endswith(".py") and not f.startswith("主程序")
            and os.path.splitext(f)[0] not in skip_on_platform)   # 入口由下面的 --冒烟/--检查 覆盖
    )
    if SOFTWARE not in sys.path:
        sys.path.insert(0, SOFTWARE)
    import_failures = []
    for name in module_names:
        try:
            importlib.import_module(name)
        except Exception as exc:                                          # noqa: BLE001
            import_failures.append(f"{name}.py → {type(exc).__name__}: {exc}")
    summary.check(f"软件/ 下 {len(module_names)} 个模块都能 import", not import_failures,
            "；".join(import_failures))

    # ---- ①-d 入口能走到"开窗前"那一步（真跑一遍 main()，不靠"看着对"）----
    #   ★ 用 `--冒烟` 而不是 `--检查`：`--检查` 在装配之后就 return 了，
    #     而 `注册表 = 插件框架.安全注册表(插件清单)` 那一行在它**之后** ——
    #     当初漏改变量名导致双击闪退，正是崩在这一行，而当时的自检全是绿的。
    #     `--冒烟` 会把 环境自检 → 装配 → 参数解析 → 注册表组装 → ViewerConfig
    #     全部真跑一遍，只差最后"开窗"这一步，所以闪退类缺陷无处可藏。
    # ★ 只跑**这个入口真的支持**的参数：不同入口的参数表不一样
    #   （自研窗口有 --检查/--项目/--开重力，官方 ImGui 有 --冒烟/--列项目）。
    #   直接套用会得到"参数不存在"的假红。
    if entry_script:
        _source = open(entry_script, encoding="utf-8").read()
        for argument, description in (("--冒烟", "能走到开窗前"), ("--检查", "能正常跑完"),
                           ("--列项目", "能正常跑完")):
            if argument not in _source:
                continue          # 这个入口没这个参数，跳过（不是缺陷）
            process = subprocess.run([sys.executable, "-X", "utf8", entry_script, argument],
                                     cwd=ROOT, capture_output=True, encoding="utf-8", timeout=180)
            summary.check(f"`{entry_name} {argument}` {description}（exit=0）", process.returncode == 0,
                    (process.stderr or process.stdout or "")[-500:])

    # ---- ② 项目文件 ----
    project_entries = projects.list_projects()
    summary.check("存在至少一个项目", bool(project_entries),
            f"{projects.relative_to_package(projects.PROJECT_DIRECTORY)} 下没有有效的项目文件")

    referenced_algorithms: set[str] = set()
    model_inventory: list[tuple[str, str]] = []
    for name in project_entries:
        data = projects.load_project(name)
        if not summary.check(f"项目「{name}」可读", data is not None):
            continue

        # 模型字段必须能解析到一个存在的文件
        model_reference = str(data.get("model") or "")
        absolute_model_path = projects.absolute_path(model_reference)
        summary.check(f"项目「{name}」的模型文件存在", bool(model_reference) and os.path.exists(absolute_model_path),
                f"写法 {model_reference!r} → 解析为 {absolute_model_path}（不存在）")
        model_inventory.append((name, os.path.normpath(absolute_model_path)))

        # 算法字段：解析出来的条目必须和"项目里写的"一样多（少一个就说明有引用不到的）
        original = data.get("algorithms", "*")
        entries = projects.parse_algorithms(data)
        expected_count = len(algorithms) if isinstance(original, str) and original.strip() in ("*", "全部", "all")\
            else (len(original) if isinstance(original, list) else 0)
        summary.check(f"项目「{name}」声明的算法都能解析", len(entries) == expected_count,
                f"声明 {expected_count} 个、解析出 {len(entries)} 个（详见上面的警告）")
        referenced_algorithms.update(str(a.get("plugin")) for a in entries)

        # 装配一遍（不带模型 → 不做兼容性预检，只看"装得出来吗"）
        instance, report = assembler.assemble_project(data, name)
        failures = [line for line in report if str(line).startswith("✗")]
        summary.check(f"项目「{name}」能装配出算法", not failures, "；".join(failures))
        if not instance:
            summary.warn(f"项目「{name}」装配出 0 个算法（算法字段是空的？）")
        if args.verbose:
            print(f"\n── 项目 {name}（{len(instance)} 个算法）")
            for line in report:
                print(f"     {line}")

    # ---- ③ 模型 ↔ 项目 的对应关系 ----
    # 规则：每个可控制的机械臂都应该能在项目里找到归宿（否则点它就没算法）
    uncovered: list[str] = []
    for m in projects.model_library_entries():
        if not m.get("controllable", m.get("可控制")):
            continue
        path = os.path.normpath(projects.absolute_path(
            str(m.get("torque_model") or m.get("扭矩模型") or "")))
        matches = [n for n, p in model_inventory if p == path]
        if not matches:
            uncovered.append(str(m.get("display_name") or m.get("identifier")
                                  or m.get("显示名") or m.get("标识")))
    if uncovered:
        summary.warn(f"这些机械臂还没有对应的项目（点开它们不会挂任何算法）：{'、'.join(uncovered)}")

    # 一个模型挂多个项目 → 不算错，但要说清楚（点模型时只会用第一个）
    from collections import Counter
    counts = Counter(p for _n, p in model_inventory)
    for path, count in counts.items():
        if count > 1:
            related = [n for n, p in model_inventory if p == path]
            summary.warn(f"同一个模型有 {count} 个项目：{'、'.join(related)}"
                    f" —— 点这个模型时只会用文件名排序第一个（这是设计如此，不是错误）")

    # ---- ⑤ 桌面的"启动项"链接是否还有效（这一次就是它断掉，用户以为软件坏了）----
    #   背景：`.app` 改名后，桌面上那个软链还指着旧名字 → 点下去毫无反应。
    #   程序本身没问题，但用户看到的现象是"软件打不开"，所以必须看住。
    import glob as _glob
    desktop = os.path.expanduser("~/Desktop")
    links = [p for p in _glob.glob(os.path.join(desktop, "*"))
             if os.path.islink(p)]
    broken_links = [os.path.basename(p) for p in links if not os.path.exists(p)]
    summary.check("桌面上的符号链接都没有断", not broken_links,
            f"这些链接指向的目标不存在：{'、'.join(broken_links)}"
            f"（软件改名/移动后要更新链接，否则双击没反应）")
    # 顺带确认"至少有一个指向本项目的启动项"
    points_to_project = [p for p in links
                if os.path.exists(p) and os.path.realpath(p).startswith(os.path.realpath(ROOT))]
    if not points_to_project:
        summary.warn(f"桌面上没有指向本项目的启动项（{desktop}）—— "
                f"想双击启动可以建一个指向 <包根>/*.app 的链接")

    # ---- ④ 没被任何项目用到的算法 ----
    unused = sorted(set(algorithm_names) - referenced_algorithms)
    if unused:
        summary.warn(f"这些算法没被任何项目用到（算法库里放着但不会加载）：{'、'.join(unused)}")

    # ---- ⑤ 老目录是否还留着（迁移残留会让"到底加载哪个"变得含糊）----
    legacy_directory = os.path.join(SOFTWARE, "plugins")
    if os.path.isdir(legacy_directory):
        remaining = sorted(f for f in os.listdir(legacy_directory) if f.endswith(".py"))
        if remaining:
            summary.warn(f"老算法目录 软件/plugins/ 里还有 .py：{'、'.join(remaining)}"
                    f" —— 装配器仍会扫它，建议全部迁到 算法库/ 后删掉这个目录")

    # ---- 结论 ----
    print()
    for warning in summary.warnings:
        print(f"⚠ {warning}")
    if summary.warnings:
        print()
    for error in summary.errors:
        print(f"✗ {error}")
    print()
    print("=" * 74)
    if summary.errors:
        print(f"  结果：{summary.passed} 项通过 / {len(summary.warnings)} 条提醒 / "
              f"**{len(summary.errors)} 项错误** —— 请先修上面的 ✗")
    else:
        print(f"  结果：{summary.passed} 项全部通过"
              + (f"（另有 {len(summary.warnings)} 条提醒，不影响使用）" if summary.warnings else "，没有提醒"))
    print("=" * 74)
    return 1 if summary.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
