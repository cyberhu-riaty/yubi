"""顺序运行同一任务的多个控制器，并生成统一的轨迹对比报告。"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
import html
import json
from pathlib import Path

import numpy as np

from experiment_registry import PACKAGE_ROOT, experiment_registry
from run_experiment import run


DEFAULT_TRAJECTORY_GROUP = (
    "ur5e_pd_waypoint_tracking",
    "ur5e_pid_waypoint_tracking",
    "ur5e_pd_gravity_ff_waypoint_tracking",
)


def _read_curves(directory: Path) -> dict:
    with (directory / "states.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise RuntimeError(f"结果没有采样：{directory}")

    def columns(prefix: str) -> list[str]:
        result = [name for name in rows[0] if name.startswith(prefix)]
        return sorted(result, key=lambda name: int(name.rsplit("_", 1)[1]))

    def matrix(prefix: str) -> list[list[float]]:
        names = columns(prefix)
        return [[float(row[name]) for name in names] for row in rows]

    return {
        "time": [float(row["time_s"]) for row in rows],
        "qpos": matrix("qpos_"),
        "qref": matrix("qref_"),
        "error": matrix("error_"),
        "ctrl": matrix("ctrl_"),
    }


def _summary(metrics: dict) -> dict:
    peak = np.asarray(metrics.get("peak_abs_ctrl", []), dtype=float)
    rms = np.asarray(metrics.get("rms_ctrl", []), dtype=float)
    return {
        "rmse_deg": float(np.degrees(metrics.get("overall_rmse_rad", float("nan")))),
        "max_error_deg": float(np.degrees(metrics.get("overall_max_abs_error_rad", float("nan")))),
        "worst_joint": str(metrics.get("worst_joint_name", "—")),
        "peak_ctrl": float(np.max(peak)) if peak.size else float("nan"),
        "rms_ctrl": float(np.sqrt(np.mean(rms**2))) if rms.size else float("nan"),
        "effort": float(metrics.get("control_effort_integral", float("nan"))),
        "saturation_percent": 100.0 * float(metrics.get("control_saturation_ratio", 0.0)),
    }


def _write_report(output: Path, runs: list[dict]) -> None:
    payload = {"group": "ur5e_waypoint_controller_comparison", "runs": runs}
    (output / "comparison.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")

    rows = []
    for item in runs:
        summary = item["summary"]
        rows.append(
            "<tr>"
            f"<td>{html.escape(item['name'])}</td>"
            f"<td>{summary['rmse_deg']:.4f}</td>"
            f"<td>{summary['max_error_deg']:.4f}</td>"
            f"<td>{html.escape(summary['worst_joint'])}</td>"
            f"<td>{summary['rms_ctrl']:.3f}</td>"
            f"<td>{summary['peak_ctrl']:.3f}</td>"
            f"<td>{summary['effort']:.3f}</td>"
            f"<td>{summary['saturation_percent']:.2f}%</td>"
            "</tr>")
    table_rows = "".join(rows)
    chart_payload = [{
        "key": item["key"], "name": item["name"], "curves": item["curves"],
        "joint_names": item["metrics"].get("joint_names", []),
    } for item in runs]
    document = """<!doctype html><meta charset='utf-8'><title>轨迹控制算法对比</title>
<style>body{font:14px system-ui;margin:24px;color:#17212b}table{border-collapse:collapse;width:100%;margin:16px 0 28px}th,td{border:1px solid #d7dee5;padding:8px;text-align:right}th:first-child,td:first-child{text-align:left}canvas{width:100%;height:300px;border:1px solid #ccd4dc;margin:8px 0 24px}select{padding:5px 10px}</style>
<h1>UR5e 多航点轨迹控制算法对比</h1>
<p>三组实验使用相同模型、初始状态、参考轨迹、停止时间和记录频率。角度单位为 deg，控制输入单位为 Nm。</p>
<table><thead><tr><th>算法</th><th>整体RMSE</th><th>最大误差</th><th>最大误差关节</th><th>控制RMS</th><th>峰值力矩</th><th>∫τ²dt</th><th>饱和率</th></tr></thead><tbody>__ROWS__</tbody></table>
<label>查看关节：<select id='joint'></select></label>
<h2>参考位置（虚线）与各算法实际位置</h2><canvas id='position'></canvas>
<h2>各算法跟踪误差</h2><canvas id='error'></canvas>
<h2>各算法控制输入</h2><canvas id='control'></canvas>
<script>const R=__DATA__,COL=['#1769aa','#d1495b','#2a9d8f'];
const sel=document.getElementById('joint'),names=R[0].joint_names.length?R[0].joint_names:R[0].curves.qpos[0].map((_,i)=>`joint_${i}`);names.forEach((n,i)=>sel.add(new Option(n,i)));
function draw(id,series){const c=document.getElementById(id),d=devicePixelRatio||1,w=c.clientWidth,h=c.clientHeight;c.width=w*d;c.height=h*d;const x=c.getContext('2d');x.scale(d,d);const vals=series.flatMap(s=>s.y).filter(Number.isFinite);let lo=Math.min(...vals),hi=Math.max(...vals);if(!(hi>lo)){lo-=1;hi+=1}x.strokeStyle='#e1e6eb';for(let k=0;k<5;k++){let y=12+k*(h-28)/4;x.beginPath();x.moveTo(46,y);x.lineTo(w-10,y);x.stroke()}series.forEach((s,k)=>{x.strokeStyle=s.color;x.setLineDash(s.dash||[]);x.beginPath();s.y.forEach((v,i)=>{const xx=46+i*(w-58)/Math.max(1,s.y.length-1),yy=12+(hi-v)*(h-28)/(hi-lo);i?x.lineTo(xx,yy):x.moveTo(xx,yy)});x.stroke();x.setLineDash([]);x.fillStyle=s.color;x.fillText(s.name,52,18+16*k)});x.fillStyle='#52606d';x.fillText(hi.toFixed(3),2,16);x.fillText(lo.toFixed(3),2,h-10)}
function refresh(){const j=+sel.value,ref=R[0].curves.qref.map(a=>a[j]);draw('position',[{name:'q_ref',y:ref,color:'#555',dash:[6,4]},...R.map((r,i)=>({name:r.name,y:r.curves.qpos.map(a=>a[j]),color:COL[i]}))]);draw('error',R.map((r,i)=>({name:r.name,y:r.curves.error.map(a=>a[j]),color:COL[i]})));draw('control',R.map((r,i)=>({name:r.name,y:r.curves.ctrl.map(a=>a[j]),color:COL[i]})))}sel.onchange=refresh;refresh();</script>"""
    document = document.replace("__ROWS__", table_rows).replace(
        "__DATA__", json.dumps(chart_payload, ensure_ascii=False, allow_nan=False))
    (output / "comparison.html").write_text(document, encoding="utf-8")


def compare(names=DEFAULT_TRAJECTORY_GROUP) -> str:
    runs: list[dict] = []
    for name in names:
        directory = Path(run(name))
        metrics = json.loads((directory / "metrics.json").read_text(encoding="utf-8"))
        experiment = experiment_registry.create(name)
        runs.append({
            "key": name,
            "name": experiment.name,
            "result_directory": str(directory),
            "summary": _summary(metrics),
            "metrics": metrics,
            "curves": _read_curves(directory),
        })
    output = PACKAGE_ROOT / "输出" / "实验" / (
        "trajectory_comparison_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    output.mkdir(parents=True, exist_ok=False)
    _write_report(output, runs)
    print(f"✓ 对比报告：{output}")
    return str(output)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="运行 UR5e 多航点三控制器对比实验")
    parser.add_argument("experiments", nargs="*", default=list(DEFAULT_TRAJECTORY_GROUP))
    args = parser.parse_args(argv)
    compare(tuple(args.experiments))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
