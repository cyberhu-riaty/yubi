"""与 GUI 无关的通用实验结果记录器。"""
from __future__ import annotations

import csv
from datetime import datetime
import json
from pathlib import Path
import threading

import numpy as np

from experiment_registry import Experiment, PACKAGE_ROOT


class ExperimentResultRecorder:
    """从仿真状态快照生成 CSV、指标 JSON 和离线曲线 HTML。"""

    def __init__(self, experiment: Experiment, frequency_hz: float = 100.0) -> None:
        self.experiment = experiment
        self.period = 1.0 / max(float(frequency_hz), 1e-6)
        self._lock = threading.Lock()
        self._next_time = 0.0
        self._samples: list[dict] = []

    def observe(self, snapshot) -> None:
        time_value = float(getattr(snapshot, "time", 0.0))
        with self._lock:
            if self._samples and time_value + 1e-12 < self._next_time:
                return
            self._samples.append({
                "time": time_value,
                "qpos": np.asarray(getattr(snapshot, "qpos", []), dtype=float).copy(),
                "qvel": np.asarray(getattr(snapshot, "qvel", []), dtype=float).copy(),
                "ctrl": np.asarray(getattr(snapshot, "ctrl", []), dtype=float).copy(),
            })
            self._next_time = time_value + self.period

    @property
    def latest_time(self) -> float:
        with self._lock:
            return float(self._samples[-1]["time"]) if self._samples else 0.0

    def export(self) -> Path:
        with self._lock:
            samples = list(self._samples)
        if not samples:
            raise RuntimeError("实验没有采集到状态，不能导出结果")
        relative = str(self.experiment.result.get("directory") or "输出/实验")
        base = Path(relative)
        if not base.is_absolute():
            base = PACKAGE_ROOT / base
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = base / f"{self.experiment.key}_{stamp}"
        output.mkdir(parents=True, exist_ok=False)
        self._write_csv(output / "states.csv", samples)
        metrics = self._metrics(samples)
        (output / "metrics.json").write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
        self._write_curves(output / "curves.html", samples)
        (output / "experiment.json").write_text(
            json.dumps({
                "key": self.experiment.key,
                "name": self.experiment.name,
                "model": self.experiment.model,
                "project": self.experiment.project,
                "controllers": self.experiment.controllers,
                "plugins": self.experiment.plugins,
                "trajectory": self.experiment.trajectory,
                "initial_state": self.experiment.initial_state,
                "stop_condition": self.experiment.stop_condition,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        return output

    @staticmethod
    def _write_csv(path: Path, samples: list[dict]) -> None:
        nq = len(samples[0]["qpos"])
        nv = len(samples[0]["qvel"])
        nu = len(samples[0]["ctrl"])
        header = (["time_s"] + [f"qpos_{i}" for i in range(nq)]
                  + [f"qvel_{i}" for i in range(nv)] + [f"ctrl_{i}" for i in range(nu)])
        with path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            for sample in samples:
                writer.writerow([sample["time"], *sample["qpos"], *sample["qvel"], *sample["ctrl"]])

    def _metrics(self, samples: list[dict]) -> dict:
        qpos = np.asarray([s["qpos"] for s in samples], dtype=float)
        qvel = np.asarray([s["qvel"] for s in samples], dtype=float)
        ctrl = np.asarray([s["ctrl"] for s in samples], dtype=float)
        final = samples[-1]
        metrics = {
            "experiment": self.experiment.key,
            "controllers": list(self.experiment.controllers),
            "sample_count": len(samples),
            "duration_s": float(final["time"]),
            "peak_abs_qvel": np.max(np.abs(qvel), axis=0).tolist() if qvel.size else [],
            "peak_abs_ctrl": np.max(np.abs(ctrl), axis=0).tolist() if ctrl.size else [],
            "final_qpos": final["qpos"].tolist(),
            "final_qvel": final["qvel"].tolist(),
            "final_ctrl": final["ctrl"].tolist(),
        }
        # 固定关节目标实验可直接得到通用跟踪误差，不需要知道机器人型号
        # 或控制器类型；没有 target_qpos 的实验则只保留上面的基础指标。
        target = np.asarray(
            self.experiment.trajectory.get("target_qpos", []), dtype=float
        ).reshape(-1)
        if target.size and qpos.ndim == 2 and qpos.shape[1] == target.size:
            error = qpos - target.reshape(1, -1)
            metrics["target_qpos"] = target.tolist()
            metrics["joint_rmse_rad"] = np.sqrt(np.mean(error**2, axis=0)).tolist()
            metrics["joint_max_abs_error_rad"] = np.max(np.abs(error), axis=0).tolist()
            metrics["final_abs_error_rad"] = np.abs(error[-1]).tolist()
            metrics["overall_rmse_rad"] = float(np.sqrt(np.mean(error**2)))
            metrics["overall_max_abs_error_rad"] = float(np.max(np.abs(error)))
        return metrics

    @staticmethod
    def _write_curves(path: Path, samples: list[dict]) -> None:
        payload = {
            "time": [float(s["time"]) for s in samples],
            "qpos": [s["qpos"].tolist() for s in samples],
            "ctrl": [s["ctrl"].tolist() for s in samples],
        }
        # 零外部依赖的离线曲线：浏览器直接打开即可，不需要网络或 Plotly。
        html = """<!doctype html><meta charset='utf-8'><title>Experiment curves</title>
<style>body{font:14px system-ui;margin:24px;color:#17212b}canvas{width:100%;height:320px;border:1px solid #ccd4dc;margin-bottom:24px}</style>
<h1>实验曲线</h1><p id='info'></p><h2>qpos</h2><canvas id='q'></canvas><h2>ctrl</h2><canvas id='u'></canvas>
<script>const D=__DATA__, C=['#1769aa','#d1495b','#2a9d8f','#f4a261','#7b2cbf','#4d908e','#bc6c25','#577590'];
function draw(id,rows){const c=document.getElementById(id),r=devicePixelRatio||1,w=c.clientWidth,h=c.clientHeight;c.width=w*r;c.height=h*r;const x=c.getContext('2d');x.scale(r,r);x.clearRect(0,0,w,h);if(!rows.length)return;const n=Math.max(...rows.map(a=>a.length)),vals=rows.flat();let lo=Math.min(...vals),hi=Math.max(...vals);if(!(hi>lo)){lo-=1;hi+=1}x.strokeStyle='#dfe5ea';for(let k=0;k<5;k++){let y=10+k*(h-20)/4;x.beginPath();x.moveTo(38,y);x.lineTo(w-8,y);x.stroke()}for(let j=0;j<n;j++){x.strokeStyle=C[j%C.length];x.beginPath();for(let i=0;i<rows.length;i++){const xx=38+i*(w-48)/Math.max(1,rows.length-1),v=rows[i][j]??0,yy=10+(hi-v)*(h-20)/(hi-lo);i?x.lineTo(xx,yy):x.moveTo(xx,yy)}x.stroke()}x.fillStyle='#52606d';x.fillText(hi.toFixed(3),2,14);x.fillText(lo.toFixed(3),2,h-8)}
document.getElementById('info').textContent=`${D.time.length} samples · ${D.time.at(-1).toFixed(3)} s`;draw('q',D.qpos);draw('u',D.ctrl);</script>"""
        path.write_text(html.replace("__DATA__", json.dumps(payload, ensure_ascii=False)), encoding="utf-8")
