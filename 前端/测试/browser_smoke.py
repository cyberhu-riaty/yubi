#!/usr/bin/env python3
"""
browser_smoke.py —— 用 Chrome DevTools Protocol 把界面真的打开一遍（不是产品代码，不参与打包）。

为什么要有它：
    这一层是纯界面，`tsc` 只能证明类型对，证明不了"真的画出来了"。
    实测踩到的两个只有真跑才发现的问题：
      · `用SyncExternalStore` 的 getSnapshot 每次返回新对象 → 无限重画 → **整页白屏**
        （控制台报 `The result of getSnapshot should be cached`）
      · 中文类名 Tailwind 扫不到 → 类名写了、样式没生成
    两个都不是类型错误，只能靠"跑一遍 + 看真的 DOM/截图"发现。

它做什么：
    ① 需要先起一个对端：`前端/测试/fake_backend.py`（提供 ws 与产物 HTTP，默认同源 8712；
       真后端占着 8712 时用 `驭臂_测试端口=8713` 换端口）
    ② 起 headless Chrome，按 CDP 导航、等待、取 `document.body.innerText`、截图
    ③ 检查若干**必须出现**的事实（模型名、握手行、主题速率、状态栏字段…）
    ④ 切皮肤 / 切语言 / 切页签 / 切到验证视图，各再取一次并留下一张图

用法：
    .venv/bin/python 前端/测试/fake_backend.py &          # 另开一个终端
    .venv/bin/python 前端/测试/browser_smoke.py --输出 /tmp/冒烟
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

import websockets

def find_browser() -> str:
    """测试工具也要跨平台：优先环境变量，其次查 PATH 和常见安装位置。"""
    candidate = [
        os.environ.get("驭臂_测试浏览器", ""),
        shutil.which("google-chrome") or "",
        shutil.which("chrome") or "",
        shutil.which("msedge") or "",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for path in candidate:
        if path and os.path.isfile(path):
            return path
    return "chrome"


CHROME = find_browser()
DEBUG_PORT = 9333
# 端口可用环境变量改（与假后端共用同一个变量）：真后端正在 8712 上跑时不必抢端口。
PORT = int(os.environ.get("驭臂_测试端口", "8712"))
URL = f"http://127.0.0.1:{PORT}/"


class Page:
    def __init__(self, connection):
        self.connection = connection
        self.request_id = 0

    async def call(self, method: str, params: dict | None = None):
        self.request_id += 1
        await self.connection.send(json.dumps({"id": self.request_id, "method": method, "params": params or {}}))
        while True:
            response = json.loads(await self.connection.recv())
            if response.get("id") == self.request_id:
                if "error" in response:
                    raise RuntimeError(f"{method} 失败：{response['error']}")
                return response.get("result", {})

    async def text(self) -> str:
        response = await self.call("Runtime.evaluate", {"expression": "document.body.innerText", "returnByValue": True})
        return response["result"]["value"]

    async def click(self, label: str) -> bool:
        """按可见文字点一个按钮/链接（找不到返回 False，不静默成功）"""
        script = """
        (() => {
          const 要找 = %s;
          const 们 = [...document.querySelectorAll('button,[role=tab],[role=switch],a,label')];
          // 用 textContent 而不是 innerText：滚动区外/折叠区里的内容 innerText 会返回空串，
          // 冒烟脚本会因此"找不到按钮"（踩过：外观视图在滚动区外，innerText 判成不存在）
          const 中 = 们.find(e => (e.textContent||'').trim().includes(要找) || (e.title||'').includes(要找));
          if (!中) return false;
          中.click(); return true;
        })()
        """ % json.dumps(label, ensure_ascii=False)
        response = await self.call("Runtime.evaluate", {"expression": script, "returnByValue": True})
        return bool(response["result"]["value"])

    async def evaluate(self, script: str):
        response = await self.call("Runtime.evaluate", {"expression": script, "returnByValue": True})
        return response["result"].get("value")

    async def screenshot(self, path: str) -> None:
        response = await self.call("Page.captureScreenshot", {"format": "png"})
        with open(path, "wb") as f:
            f.write(base64.b64decode(response["data"]))


async def main(output_dir: str) -> int:
    os.makedirs(output_dir, exist_ok=True)
    profile = os.path.join(output_dir, "chrome-profile")
    shutil.rmtree(profile, ignore_errors=True)

    process = subprocess.Popen(
        [CHROME, "--headless=new", "--no-sandbox", "--disable-gpu", "--no-first-run",
         "--no-default-browser-check", f"--user-data-dir={profile}",
         f"--remote-debugging-port={DEBUG_PORT}", "--window-size=1440,900", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(40):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json/version", timeout=0.5)
                break
            except Exception:
                time.sleep(0.25)
        else:
            print("Chrome 没起来（CDP 端口不通）", file=sys.stderr)
            return 2

        target = json.load(urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json/list"))
        page_target = [t for t in target if t["type"] == "page"][0]
        failed: list[str] = []

        async with websockets.connect(page_target["webSocketDebuggerUrl"], max_size=32 * 1024 * 1024) as connection:
            P = Page(connection)
            await P.call("Page.enable")
            await P.call("Runtime.enable")
            # 固定 CSS 像素视口：headless 的 --window-size 在部分版本上只影响
            # 截图位图，不影响 innerWidth；不固定的话媒体查询会在 980px 上做判断。
            await P.call("Emulation.setDeviceMetricsOverride", {
                "width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False,
            })
            await P.call("Page.navigate", {"url": URL})
            await asyncio.sleep(8)

            text = await P.text()
            (open(os.path.join(output_dir, "01-定义.txt"), "w", encoding="utf-8").write(text))
            await P.screenshot(os.path.join(output_dir, "01-定义.png"))

            required = [
                "驭臂",                 # 标题条
                "自由度 nq", "执行器数 nu",
                "帧率",
                "仿真时间",
                "实时倍率",             # 系统主题里的 RTF，不是墙钟冒充的
                # ★ 中区文案在 P3 改成实话了：原生 3D 真接上了（由宿主窗口放在中区
                #   **右侧**），所以这里断言的是"说清楚 3D 在哪"，而不是旧文案
                #   "尚未接入"。断言的意图没变：中区不能假装自己有几何。
                "原生 3D 在宿主窗口右侧",
                "模型与关节状态",
                "已连接",
                # 兼容性不能只埋在装配报告里：假后端的报告写了「不兼容」，
                # 定义页顶部必须出现可处理提示。
                "有算法与当前模型不兼容",
            ]
            for word in required:
                if word not in text:
                    # 中文模型名要等 2 Hz 那一帧，重取一次再判
                    await asyncio.sleep(1.5)
                    text = await P.text()
                    if word not in text:
                        failed.append(f"定义视图里没看到「{word}」")

            # ★ 模型名不写死：假后端报「冒烟测试臂」，真后端报真型号。
            #   钉死夹具名会让这套冒烟**只能对着假后端跑**，
            #   而真正要验的恰恰是"真后端的数据有没有画出来"。
            if "显示名" not in (await P.text()):
                failed.append("定义视图里没看到模型「显示名」行")

            # 全局仿真控制：Pause 保持时间，Run 继续累加，Reset 才归零。
            if not all(x in text for x in ("运行", "暂停", "复位")):
                failed.append("中区没有完整的 Run / Pause / Reset 控件")
            elif not await P.evaluate("""
            (() => {
              const 组 = [...document.querySelectorAll('[role=group]')]
                .find(e => (e.getAttribute('aria-label') || '').includes('仿真控制'));
              const 按钮 = 组 && [...组.querySelectorAll('button')]
                .find(e => (e.textContent || '').trim() === '运行');
              if (!按钮) return false;
              按钮.click(); return true;
            })()
            """):
                failed.append("点不到仿真「运行」")
            else:
                await asyncio.sleep(0.8)
                before_run = await P.evaluate("window.驭臂.取状态().仿真.数据.simulation_time")
                await asyncio.sleep(0.8)
                after_run = await P.evaluate("window.驭臂.取状态().仿真.数据.simulation_time")
                if not isinstance(before_run, (int, float)) or not isinstance(after_run, (int, float)) or after_run <= before_run:
                    failed.append(f"Run 后 data.time 没有增加（{before_run} → {after_run}）")
                if not await P.click("暂停"):
                    failed.append("点不到仿真「暂停」")
                else:
                    await asyncio.sleep(0.5)
                    before_pause = await P.evaluate("window.驭臂.取状态().仿真.数据.simulation_time")
                    await asyncio.sleep(0.7)
                    after_pause = await P.evaluate("window.驭臂.取状态().仿真.数据.simulation_time")
                    if abs(float(after_pause) - float(before_pause)) > 0.05:
                        failed.append(f"Pause 后 data.time 仍在增加（{before_pause} → {after_pause}）")
                if not await P.click("复位"):
                    failed.append("点不到仿真「复位」")
                else:
                    await asyncio.sleep(0.5)
                    reset_state = await P.evaluate("""
                    (() => {
                      const x = window.驭臂.取状态().仿真.数据;
                      return {状态:x.state, 时间:x.simulation_time, 次数:x.reset_count};
                    })()
                    """)
                    if not reset_state or reset_state.get("状态") != "paused" or float(reset_state.get("时间", 1)) > 0.05 or int(reset_state.get("次数", 0)) < 1:
                        failed.append(f"Reset 后状态不正确：{reset_state}")

            # 算法配置闭环：选择只产生“待应用”，临时应用后后端回灌“当前生效”，
            # 再保存时只落盘，不应要求用户重新勾一次。
            await P.evaluate("[...document.querySelectorAll('button.段头')].find(e => e.textContent.includes('算法库'))?.click()")
            await asyncio.sleep(0.4)
            text = await P.text()
            if "算法库" not in text or "当前生效" not in text or "未保存" not in text:
                failed.append("定义视图没有显示算法库的生效/存盘状态")
            selected = await P.evaluate("""
            (() => {
              const 名 = [...document.querySelectorAll('label span.font-semibold')]
                .find(e => (e.textContent || '').trim() === 'OSC');
              const 框 = 名 && 名.closest('label')?.querySelector('input[type=checkbox]');
              if (!框 || 框.checked) return false;
              框.click(); return true;
            })()
            """)
            await asyncio.sleep(0.3)
            if not selected or "待启用" not in (await P.text()):
                failed.append("算法勾选没有进入待应用状态")
            elif not await P.click("临时应用"):
                failed.append("点不到算法「临时应用」")
            else:
                await asyncio.sleep(0.8)
                osc_active = await P.evaluate("""
                (() => {
                  const s = window.驭臂 && window.驭臂.取状态();
                  const 们 = (s && s.插件 && s.插件.数据 && s.插件.数据.插件) || [];
                  const x = 们.find(e => e.插件 === 'osc');
                  return !!(x && x.当前启用);
                })()
                """)
                if not osc_active:
                    failed.append("算法临时应用后没有回灌当前生效状态")
                if not await P.click("保存到项目"):
                    failed.append("临时应用后点不到「保存到项目」")
                else:
                    await asyncio.sleep(0.8)
                    saved = await P.evaluate("""
                    (() => {
                      const s = window.驭臂 && window.驭臂.取状态();
                      return !!(s && s.项目 && s.项目.数据 && s.项目.数据.saved);
                    })()
                    """)
                    if not saved:
                        failed.append("算法保存后仍显示未存盘")

            # 曲线真的在长：直接问仓库"一共收到多少个曲线点"。
            #   ★ 不去正则匹配页面数字 —— 那会随排版失效（实测踩过两次：
            #     先按曲线名匹配（真后端名字不同），再按"最大数字"匹配（取到无关数字）。
            #     页面暴露 `window.驭臂` 之后，测试问的是内部真实状态。
            first_read = await P.evaluate("window.驭臂 ? window.驭臂.曲线点数() : null")
            await asyncio.sleep(2.5)
            second_read = await P.evaluate("window.驭臂 ? window.驭臂.曲线点数() : null")
            name = await P.evaluate("window.驭臂 ? window.驭臂.曲线名() : null")
            if not first_read or not second_read or int(second_read) <= int(first_read):
                failed.append(f"曲线点数没在长大（{first_read} → {second_read}）—— 指标可能没进来")
            elif not name:
                failed.append("仓库里一条曲线都没有")

            # 切到「验证」步骤：曲线视图 + 参数表
            if not await P.click("验证"):
                failed.append("点不到「验证」")
            await asyncio.sleep(3)
            validation_text = await P.text()
            open(os.path.join(output_dir, "02-验证.txt"), "w", encoding="utf-8").write(validation_text)
            await P.screenshot(os.path.join(output_dir, "02-验证.png"))
            for word in ["曲线（实时）", "参数表", "时间窗", "显示"]:
                if word not in validation_text:
                    failed.append(f"验证视图里没看到「{word}」")
            # canvas 真的画了东西（不是空白）
            nonempty = await P.evaluate("""
            (() => {
              const c = [...document.querySelectorAll('canvas')].sort((a,b)=>b.width*b.height-a.width*a.height)[0];
              if (!c) return '没有 canvas';
              const g = c.getContext('2d');
              const 数 = g.getImageData(0,0,c.width,c.height).data;
              let 异 = 0;
              for (let i=0;i<数.length;i+=4*97) { if (数[i]||数[i+1]||数[i+2]) 异++; }
              return 异 > 20 ? 'ok' : ('空白('+异+')');
            })()
            """)
            if nonempty != "ok":
                failed.append(f"曲线 canvas 没画出内容：{nonempty}")

            # 参数编辑链路：真在输入框里改一个值，看它有没有经
            # command.parameters → 回执 → parameter.table 回灌后回到界面。
            #   ★ 必须用原生 setter + input 事件：直接改 `.value` 不会触发 React 的 onChange，
            #     那样测的是"我自己改的 DOM"，不是产品代码。
            input_count = await P.evaluate("document.querySelectorAll('input.参数输入').length")
            # ★ 全名从**仓库**取，不从 DOM 猜：参数表的键就是「插件名·参数名」，
            #   界面渲染用的也是它。之前从 aria-label 里正则剥后缀，
            #   结果剥出了短名（KD），后端正确地拒了命令 —— 看起来像"编辑没实现"。
            full_name = await P.evaluate("""
            (() => {
              const s = window.驭臂 && window.驭臂.取状态();
              const 表 = (s && s.参数 && s.参数.数据 && s.参数.数据.parameters) || {};
              const k = Object.keys(表).sort()[0];
              return k || null;
            })()
            """)
            if not input_count:
                failed.append("参数表里没有可编辑输入框")
            elif not full_name:
                failed.append("仓库里没有参数项")
            else:
                # 界面绑定对不对：输入框的 aria-label 必须含这个全名
                # ★ 用 JS 比较，不用 CSS 属性选择器：`[aria-label^="中文"]` 在本机
                #   Chrome 上匹配不到（CSS 选择器对非 ASCII 属性值的解析有坑），
                #   而这只影响测试写法，不影响产品 —— 在 JS 里 startsWith 最稳。
                binding = await P.evaluate("""
                (() => {
                  const el = document.querySelector('input.参数输入');
                  const a = el && el.getAttribute('aria-label');
                  return a ? a.startsWith(%s) : false;
                })()
                """ % json.dumps(full_name))
                if binding != True:
                    failed.append(f"输入框的 aria-label 没绑定到参数全名「{full_name}」")
                before_change = await P.evaluate("document.querySelector('input.参数输入').value")
                parameter_details = await P.evaluate("""
                (() => {
                  const 表 = window.驭臂.取状态().参数.数据.parameters;
                  const 项 = 表[Object.keys(表).sort()[0]];
                  return {范围: 项.range, 步长: 项.step};
                })()
                """)
                current_value = float(before_change)
                step = float(parameter_details.get("步长") or 1.0)
                bounds = parameter_details.get("范围") or [float("-inf"), float("inf")]
                new_value = current_value + step if current_value + step <= bounds[1] else current_value - step
                target = f"{new_value:g}"
                sent = await P.evaluate("""
                (() => {
                  const el = document.querySelector('input.参数输入');
                  if (!el) return 'no-input';
                  el.focus();
                  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
                  setter.call(el, '%s');
                  el.dispatchEvent(new Event('input', { bubbles: true }));
                  return 'ok';
                })()
                """ % target)
                await asyncio.sleep(0.2)
                await P.call("Input.dispatchKeyEvent", {
                    "type": "keyDown", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13,
                })
                await P.call("Input.dispatchKeyEvent", {
                    "type": "keyUp", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13,
                })
                await asyncio.sleep(2.5)
                after_change = await P.evaluate("document.querySelector('input.参数输入').value")
                actual = await P.evaluate("""
                (() => {
                  const s = window.驭臂 && window.驭臂.取状态();
                  const 表 = (s && s.参数 && s.参数.数据 && s.参数.数据.parameters) || {};
                  const k = Object.keys(表).sort()[0];
                  return k ? 表[k].value : null;
                })()
                """)
                if sent != "ok":
                    failed.append(f"触发输入事件失败：{sent}")
                elif str(after_change) != target:
                    failed.append(f"参数编辑没走通（{before_change} → 目标 {target} → 实际 {after_change}）")
                elif actual is None or abs(float(actual) - float(target)) > 1e-6:
                    failed.append(f"后端回灌的参数真值不对（{actual}，期望 {target}）")

            # 辨识视图：结果/拟合表
            if not await P.click("辨识"):
                failed.append("点不到「辨识」")
            await asyncio.sleep(2.5)
            identification_text = await P.text()
            open(os.path.join(output_dir, "03-辨识.txt"), "w", encoding="utf-8").write(identification_text)
            await P.screenshot(os.path.join(output_dir, "03-辨识.png"))
            for word in ["参数辨识"]:
                if word not in identification_text:
                    failed.append(f"辨识视图里没看到「{word}」")

            # 部署视图：必须是「未接入」
            if not await P.click("部署"):
                failed.append("点不到「部署」")
            await asyncio.sleep(1.2)
            deployment_text = await P.text()
            open(os.path.join(output_dir, "04-部署.txt"), "w", encoding="utf-8").write(deployment_text)
            await P.screenshot(os.path.join(output_dir, "04-部署.png"))
            if "未接入" not in deployment_text:
                failed.append("部署视图没有「未接入」状态（验收项：必须有）")

            # 规划视图：功能已实现，空状态必须是「尚无航点」而不是「未实现」；
            # 并且要给出"至少记录 2 个航点"的可执行条件。
            if not await P.click("规划"):
                failed.append("点不到「规划」")
            await asyncio.sleep(1.0)
            planning_text = await P.text()
            if "尚无航点" not in planning_text:
                failed.append("规划视图没有空状态「尚无航点」")
            if "至少 2 个航点" not in planning_text:
                failed.append("规划视图没有说明「至少 2 个航点」的启用条件")

            # 切皮肤：data-风格 与计算样式都要跟着变
            if not await P.click("外观"):
                failed.append("点不到「外观」")
            await asyncio.sleep(1.0)
            background_before = await P.evaluate("getComputedStyle(document.body).backgroundColor")
            await P.evaluate("""[...document.querySelectorAll('button')]
                .find(b => (b.textContent||'').includes('航天测控'))?.click()""")
            await asyncio.sleep(0.8)
            theme = await P.evaluate("document.documentElement.dataset['风格'] || document.documentElement.getAttribute('data-风格')")
            background = await P.evaluate("getComputedStyle(document.body).backgroundColor")
            if theme != "航天测控":
                failed.append(f"皮肤没切过去（data-风格={theme}）")
            if background in (None, "", "rgba(0, 0, 0, 0)"):
                failed.append(f"切肤后 body 背景没拿到（{background}）")
            elif background_before == background:
                failed.append(f"切肤后 body 背景没变（{background}）—— 默认皮肤的 :root 可能覆盖了其他皮肤")
            await P.screenshot(os.path.join(output_dir, "05-皮肤-航天测控.png"))

            # 切语言：英文
            await P.evaluate("""[...document.querySelectorAll('button')]
                .find(b => (b.textContent||'').trim() === 'English')?.click()""")
            await asyncio.sleep(0.8)
            english_text = await P.text()
            open(os.path.join(output_dir, "06-英文.txt"), "w", encoding="utf-8").write(english_text)
            await P.screenshot(os.path.join(output_dir, "06-英文.png"))
            for word in ["Define", "Deploy", "Appearance", "not connected"]:
                if word not in english_text:
                    failed.append(f"英文界面里没看到「{word}」")

            # 换回中文，检查 localStorage 真的记住了
            stored = await P.evaluate("localStorage.getItem('驭臂.语言') + '|' + localStorage.getItem('驭臂.风格')")
            if "en" not in (stored or ""):
                failed.append(f"语言没落盘：{stored}")

        print(f"产物看：{output_dir}")
        if failed:
            print(f"❌ 冒烟不通过（{len(failed)} 条）：")
            for f in failed:
                print("  ·", f)
            return 1
        print("✅ 冒烟通过：真实数据、曲线、页签、皮肤、语言都验证过了")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except Exception:
            process.kill()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", "--输出", dest="output_path", default="/tmp/驭臂冒烟", help="截图与文本的落盘目录")
    params = parser.parse_args()
    sys.exit(asyncio.run(main(params.output_path)))
