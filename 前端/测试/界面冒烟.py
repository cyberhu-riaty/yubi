#!/usr/bin/env python3
"""
界面冒烟.py —— 用 Chrome DevTools Protocol 把界面真的打开一遍（不是产品代码，不参与打包）。

为什么要有它：
    这一层是纯界面，`tsc` 只能证明类型对，证明不了"真的画出来了"。
    实测踩到的两个只有真跑才发现的问题：
      · `用SyncExternalStore` 的 getSnapshot 每次返回新对象 → 无限重画 → **整页白屏**
        （控制台报 `The result of getSnapshot should be cached`）
      · 中文类名 Tailwind 扫不到 → 类名写了、样式没生成
    两个都不是类型错误，只能靠"跑一遍 + 看真的 DOM/截图"发现。

它做什么：
    ① 需要先起一个对端：`前端/测试/假后端.py`（提供 ws 与产物 HTTP，同源 8712）
    ② 起 headless Chrome，按 CDP 导航、等待、取 `document.body.innerText`、截图
    ③ 检查若干**必须出现**的事实（模型名、握手行、主题速率、状态栏字段…）
    ④ 切皮肤 / 切语言 / 切页签 / 切到验证视图，各再取一次并留下一张图

用法：
    .venv/bin/python 前端/测试/假后端.py &          # 另开一个终端
    .venv/bin/python 前端/测试/界面冒烟.py --输出 /tmp/冒烟
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

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
调试端口 = 9333
地址 = "http://127.0.0.1:8712/"


class 页:
    def __init__(self, 连):
        self.连 = 连
        self.号 = 0

    async def 调(self, 方法: str, 参: dict | None = None):
        self.号 += 1
        await self.连.send(json.dumps({"id": self.号, "method": 方法, "params": 参 or {}}))
        while True:
            回 = json.loads(await self.连.recv())
            if 回.get("id") == self.号:
                if "error" in 回:
                    raise RuntimeError(f"{方法} 失败：{回['error']}")
                return 回.get("result", {})

    async def 文本(self) -> str:
        回 = await self.调("Runtime.evaluate", {"expression": "document.body.innerText", "returnByValue": True})
        return 回["result"]["value"]

    async def 点(self, 文字: str) -> bool:
        """按可见文字点一个按钮/链接（找不到返回 False，不静默成功）"""
        脚本 = """
        (() => {
          const 要找 = %s;
          const 们 = [...document.querySelectorAll('button,[role=tab],[role=switch],a,label')];
          // 用 textContent 而不是 innerText：滚动区外/折叠区里的内容 innerText 会返回空串，
          // 冒烟脚本会因此"找不到按钮"（踩过：外观视图在滚动区外，innerText 判成不存在）
          const 中 = 们.find(e => (e.textContent||'').trim().includes(要找) || (e.title||'').includes(要找));
          if (!中) return false;
          中.click(); return true;
        })()
        """ % json.dumps(文字, ensure_ascii=False)
        回 = await self.调("Runtime.evaluate", {"expression": 脚本, "returnByValue": True})
        return bool(回["result"]["value"])

    async def 执行(self, 脚本: str):
        回 = await self.调("Runtime.evaluate", {"expression": 脚本, "returnByValue": True})
        return 回["result"].get("value")

    async def 截图(self, 路径: str) -> None:
        回 = await self.调("Page.captureScreenshot", {"format": "png"})
        with open(路径, "wb") as f:
            f.write(base64.b64decode(回["data"]))


async def 主(输出目录: str) -> int:
    os.makedirs(输出目录, exist_ok=True)
    配置 = os.path.join(输出目录, "chrome-profile")
    shutil.rmtree(配置, ignore_errors=True)

    进程 = subprocess.Popen(
        [CHROME, "--headless=new", "--no-sandbox", "--disable-gpu", "--no-first-run",
         "--no-default-browser-check", f"--user-data-dir={配置}",
         f"--remote-debugging-port={调试端口}", "--window-size=1440,900", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(40):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{调试端口}/json/version", timeout=0.5)
                break
            except Exception:
                time.sleep(0.25)
        else:
            print("Chrome 没起来（CDP 端口不通）", file=sys.stderr)
            return 2

        目标 = json.load(urllib.request.urlopen(f"http://127.0.0.1:{调试端口}/json/list"))
        页目标 = [t for t in 目标 if t["type"] == "page"][0]
        失败: list[str] = []

        async with websockets.connect(页目标["webSocketDebuggerUrl"], max_size=32 * 1024 * 1024) as 连:
            P = 页(连)
            await P.调("Page.enable")
            await P.调("Runtime.enable")
            await P.调("Page.navigate", {"url": 地址})
            await asyncio.sleep(8)

            文 = await P.文本()
            (open(os.path.join(输出目录, "01-定义.txt"), "w", encoding="utf-8").write(文))
            await P.截图(os.path.join(输出目录, "01-定义.png"))

            必须 = [
                "驭臂",                 # 标题条
                "自由度 nq", "执行器数 nu",
                "握手成功",             # 真握手日志
                "主题速率",
                "指标",                 # 真收到的主题
                "曲线帧率",
                "仿真时间",
                # ★ 中区文案在 P3 改成实话了：原生 3D 真接上了（由宿主窗口放在中区
                #   **下方**），所以这里断言的是"说清楚 3D 在哪"，而不是旧文案
                #   "尚未接入"。断言的意图没变：中区不能假装自己有几何。
                "原生 3D 就在窗口下方",
                "模型与关节状态",
                "已连接",
            ]
            for 词 in 必须:
                if 词 not in 文:
                    # 中文模型名要等 2 Hz 那一帧，重取一次再判
                    await asyncio.sleep(1.5)
                    文 = await P.文本()
                    if 词 not in 文:
                        失败.append(f"定义视图里没看到「{词}」")

            # ★ 模型名不写死：假后端报「冒烟测试臂」，真后端报真型号。
            #   钉死夹具名会让这套冒烟**只能对着假后端跑**，
            #   而真正要验的恰恰是"真后端的数据有没有画出来"。
            if "显示名" not in (await P.文本()):
                失败.append("定义视图里没看到模型「显示名」行")

            # 曲线真的在长：直接问仓库"一共收到多少个曲线点"。
            #   ★ 不去正则匹配页面数字 —— 那会随排版失效（实测踩过两次：
            #     先按曲线名匹配（真后端名字不同），再按"最大数字"匹配（取到无关数字）。
            #     页面暴露 `window.驭臂` 之后，测试问的是内部真实状态。
            读1 = await P.执行("window.驭臂 ? window.驭臂.曲线点数() : null")
            await asyncio.sleep(2.5)
            读2 = await P.执行("window.驭臂 ? window.驭臂.曲线点数() : null")
            名 = await P.执行("window.驭臂 ? window.驭臂.曲线名() : null")
            if not 读1 or not 读2 or int(读2) <= int(读1):
                失败.append(f"曲线点数没在长大（{读1} → {读2}）—— 指标可能没进来")
            elif not 名:
                失败.append("仓库里一条曲线都没有")

            # 切到「验证」步骤：曲线视图 + 参数表
            if not await P.点("验证"):
                失败.append("点不到「验证」")
            await asyncio.sleep(3)
            文验证 = await P.文本()
            open(os.path.join(输出目录, "02-验证.txt"), "w", encoding="utf-8").write(文验证)
            await P.截图(os.path.join(输出目录, "02-验证.png"))
            for 词 in ["曲线（实时）", "参数表", "时间窗", "显示"]:
                if 词 not in 文验证:
                    失败.append(f"验证视图里没看到「{词}」")
            # canvas 真的画了东西（不是空白）
            非空 = await P.执行("""
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
            if 非空 != "ok":
                失败.append(f"曲线 canvas 没画出内容：{非空}")

            # 参数编辑链路：真在输入框里改一个值，看它有没有经
            # 命令.改参数 → 回执 → 参数表回灌 走一圈回到界面上。
            #   ★ 必须用原生 setter + input 事件：直接改 `.value` 不会触发 React 的 onChange，
            #     那样测的是"我自己改的 DOM"，不是产品代码。
            输入框数 = await P.执行("document.querySelectorAll('input.参数输入').length")
            # ★ 全名从**仓库**取，不从 DOM 猜：参数表的键就是「插件名·参数名」，
            #   界面渲染用的也是它。之前从 aria-label 里正则剥后缀，
            #   结果剥出了短名（KD），后端正确地拒了命令 —— 看起来像"编辑没实现"。
            全名 = await P.执行("""
            (() => {
              const s = window.驭臂 && window.驭臂.取状态();
              const 表 = (s && s.参数 && s.参数.数据 && s.参数.数据.参数) || {};
              const k = Object.keys(表).sort()[0];
              return k || null;
            })()
            """)
            if not 输入框数:
                失败.append("参数表里没有可编辑输入框")
            elif not 全名:
                失败.append("仓库里没有参数项")
            else:
                # 界面绑定对不对：输入框的 aria-label 必须含这个全名
                # ★ 用 JS 比较，不用 CSS 属性选择器：`[aria-label^="中文"]` 在本机
                #   Chrome 上匹配不到（CSS 选择器对非 ASCII 属性值的解析有坑），
                #   而这只影响测试写法，不影响产品 —— 在 JS 里 startsWith 最稳。
                绑定 = await P.执行("""
                (() => {
                  const el = document.querySelector('input.参数输入');
                  const a = el && el.getAttribute('aria-label');
                  return a ? a.startsWith(%s) : false;
                })()
                """ % json.dumps(全名))
                if 绑定 != True:
                    失败.append(f"输入框的 aria-label 没绑定到参数全名「{全名}」")
                改前 = await P.执行("document.querySelector('input.参数输入').value")
                目标 = "321" if str(改前) != "321" else "322"
                发了 = await P.执行("""
                (() => {
                  const el = document.querySelector('input.参数输入');
                  if (!el) return 'no-input';
                  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
                  setter.call(el, '%s');
                  el.dispatchEvent(new Event('input', { bubbles: true }));
                  return 'ok';
                })()
                """ % 目标)
                await asyncio.sleep(2.5)
                改后 = await P.执行("document.querySelector('input.参数输入').value")
                真值 = await P.执行("""
                (() => {
                  const s = window.驭臂 && window.驭臂.取状态();
                  const 表 = (s && s.参数 && s.参数.数据 && s.参数.数据.参数) || {};
                  const k = Object.keys(表).sort()[0];
                  return k ? 表[k].值 : null;
                })()
                """)
                if 发了 != "ok":
                    失败.append(f"触发输入事件失败：{发了}")
                elif str(改后) != 目标:
                    失败.append(f"参数编辑没走通（{改前} → 目标 {目标} → 实际 {改后}）")
                elif 真值 is None or abs(float(真值) - float(目标)) > 1e-6:
                    失败.append(f"后端回灌的参数真值不对（{真值}，期望 {目标}）")

            # 辨识视图：结果/拟合表
            if not await P.点("辨识"):
                失败.append("点不到「辨识」")
            await asyncio.sleep(2.5)
            文辨识 = await P.文本()
            open(os.path.join(输出目录, "03-辨识.txt"), "w", encoding="utf-8").write(文辨识)
            await P.截图(os.path.join(输出目录, "03-辨识.png"))
            for 词 in ["参数辨识"]:
                if 词 not in 文辨识:
                    失败.append(f"辨识视图里没看到「{词}」")

            # 部署视图：必须是「未接入」
            if not await P.点("部署"):
                失败.append("点不到「部署」")
            await asyncio.sleep(1.2)
            文部署 = await P.文本()
            open(os.path.join(输出目录, "04-部署.txt"), "w", encoding="utf-8").write(文部署)
            await P.截图(os.path.join(输出目录, "04-部署.png"))
            if "未接入" not in 文部署:
                失败.append("部署视图没有「未接入」状态（验收项：必须有）")

            # 规划视图：必须是「未实现」
            if not await P.点("规划"):
                失败.append("点不到「规划」")
            await asyncio.sleep(1.0)
            文规划 = await P.文本()
            if "未实现" not in 文规划:
                失败.append("规划视图没有「未实现」状态")

            # 切皮肤：data-风格 与计算样式都要跟着变
            if not await P.点("外观"):
                失败.append("点不到「外观」")
            await asyncio.sleep(1.0)
            await P.执行("""[...document.querySelectorAll('button')]
                .find(b => (b.textContent||'').includes('航天测控'))?.click()""")
            await asyncio.sleep(0.8)
            风格 = await P.执行("document.documentElement.dataset['风格'] || document.documentElement.getAttribute('data-风格')")
            底 = await P.执行("getComputedStyle(document.body).backgroundColor")
            if 风格 != "航天测控":
                失败.append(f"皮肤没切过去（data-风格={风格}）")
            if 底 in (None, "", "rgba(0, 0, 0, 0)"):
                失败.append(f"切肤后 body 背景没拿到（{底}）")
            await P.截图(os.path.join(输出目录, "05-皮肤-航天测控.png"))

            # 切语言：英文
            await P.执行("""[...document.querySelectorAll('button')]
                .find(b => (b.textContent||'').trim() === 'English')?.click()""")
            await asyncio.sleep(0.8)
            文英 = await P.文本()
            open(os.path.join(输出目录, "06-英文.txt"), "w", encoding="utf-8").write(文英)
            await P.截图(os.path.join(输出目录, "06-英文.png"))
            for 词 in ["Define", "Deploy", "Appearance", "not connected"]:
                if 词 not in 文英:
                    失败.append(f"英文界面里没看到「{词}」")

            # 换回中文，检查 localStorage 真的记住了
            存 = await P.执行("localStorage.getItem('驭臂.语言') + '|' + localStorage.getItem('驭臂.风格')")
            if "en" not in (存 or ""):
                失败.append(f"语言没落盘：{存}")

        print(f"产物看：{输出目录}")
        if 失败:
            print(f"❌ 冒烟不通过（{len(失败)} 条）：")
            for f in 失败:
                print("  ·", f)
            return 1
        print("✅ 冒烟通过：真实数据、曲线、页签、皮肤、语言都验证过了")
        return 0
    finally:
        进程.terminate()
        try:
            进程.wait(timeout=5)
        except Exception:
            进程.kill()


if __name__ == "__main__":
    解析 = argparse.ArgumentParser()
    解析.add_argument("--输出", default="/tmp/驭臂冒烟", help="截图与文本的落盘目录")
    参 = 解析.parse_args()
    sys.exit(asyncio.run(主(参.输出)))
