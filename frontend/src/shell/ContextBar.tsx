/**
 * ContextBar.tsx —— 侧栏标题下面的一行"我现在在哪个项目、哪台模型上"。
 *
 * 为什么把它从状态栏搬到这里：
 *   状态栏只留运行现场（物理/仿真时间/RTF/帧率/连接），项目与模型放在
 *   上下文侧栏的顶部更符合阅读顺序；切到「验证」「规划」时也仍然看得到。
 *   两个名字都截断并带完整 title，长路径不会把这一行撑成两行。
 */
import { useStore as useStore } from "../data/store";
import { useTranslation } from "../views/i18n";

export function ContextBar() {
  const t = useTranslation();
  const project = useStore((s) => s.project.data);
  const model = useStore((s) => s.model.data);
  const experiment = useStore((s) => s.experiment.data);

  const projectName = project?.project || "--";
  const modelName = model?.current_display_name || model?.current_path || "--";

  return (
    <div className="context-bar" aria-label={t("侧栏.上下文")}>
      <span className="context-item" title={`${t("状态栏.实验")}：${experiment?.name || "--"}`}>
        <span className="context-label">{t("状态栏.实验")}</span>
        <span className="truncate">{experiment?.name || "--"}</span>
      </span>
      <span className="context-item" title={`${t("状态栏.项目")}：${projectName}`}>
        <span className="context-label">{t("状态栏.项目")}</span>
        <span className="truncate">{projectName}</span>
      </span>
      <span className="context-item" title={`${t("状态栏.模型")}：${modelName}`}>
        <span className="context-label">{t("状态栏.模型")}</span>
        <span className="truncate">{modelName}</span>
      </span>
      <span className="context-item" title={t("状态栏.提示.真机")}>
        <span className="context-label">{t("状态栏.真机")}</span>
        <span className="context-unavailable">{t("状态栏.真机.未接入")}</span>
      </span>
    </div>
  );
}
