/**
 * 上下文条.tsx —— 侧栏标题下面的一行"我现在在哪个项目、哪台模型上"。
 *
 * 为什么把它从状态栏搬到这里：
 *   状态栏只留运行现场（物理/仿真时间/RTF/帧率/连接），项目与模型放在
 *   上下文侧栏的顶部更符合阅读顺序；切到「验证」「规划」时也仍然看得到。
 *   两个名字都截断并带完整 title，长路径不会把这一行撑成两行。
 */
import { 用仓库 } from "../数据/仓库";
import { use取 } from "../视图/文案";

export function 上下文条() {
  const t = use取();
  const 项目 = 用仓库((s) => s.项目.数据);
  const 模型 = 用仓库((s) => s.模型.数据);
  const 实验 = 用仓库((s) => s.实验.数据);

  const 项目名 = 项目?.项目 || "--";
  const 模型名 = 模型?.当前显示名 || 模型?.当前路径 || "--";

  return (
    <div className="上下文条" aria-label={t("侧栏.上下文")}>
      <span className="上下文项" title={`${t("状态栏.实验")}：${实验?.名称 || "--"}`}>
        <span className="上下文标签">{t("状态栏.实验")}</span>
        <span className="truncate">{实验?.名称 || "--"}</span>
      </span>
      <span className="上下文项" title={`${t("状态栏.项目")}：${项目名}`}>
        <span className="上下文标签">{t("状态栏.项目")}</span>
        <span className="truncate">{项目名}</span>
      </span>
      <span className="上下文项" title={`${t("状态栏.模型")}：${模型名}`}>
        <span className="上下文标签">{t("状态栏.模型")}</span>
        <span className="truncate">{模型名}</span>
      </span>
      <span className="上下文项" title={t("状态栏.提示.真机")}>
        <span className="上下文标签">{t("状态栏.真机")}</span>
        <span className="上下文未接入">{t("状态栏.真机.未接入")}</span>
      </span>
    </div>
  );
}
