/**
 * 帮助视图.tsx —— 主界面只给入口，不把整本说明书重新塞回工作区。
 *
 * 这里保留首次使用真正需要的最短路径；按钮明细、参数含义、故障排查和
 * 能力边界统一维护在 `docs/使用手册.md`，避免界面文案与说明书各写一套。
 */
import { 可折叠区块 } from "../组件/可折叠区块";
import { 标签 } from "../组件/标签";
import { use取, type 文案键 } from "./文案";

const 快速步骤 = ["帮助.快速.一", "帮助.快速.二", "帮助.快速.三", "帮助.快速.四"] as const satisfies readonly 文案键[];
const 三维操作 = ["帮助.三维.旋转", "帮助.三维.平移", "帮助.三维.缩放", "帮助.三维.适配"] as const satisfies readonly 文案键[];
const 注意项 = ["帮助.注意.暂停", "帮助.注意.模拟", "帮助.注意.急停"] as const satisfies readonly 文案键[];

export function 帮助视图() {
  const t = use取();
  return (
    <div className="space-y-2">
      <可折叠区块 标题={t("帮助.快速标题")} 徽标={<标签>{t("帮助.新手")}</标签>}>
        <ol className="list-decimal space-y-1 pl-5">
          {快速步骤.map((键) => <li key={键}>{t(键)}</li>)}
        </ol>
      </可折叠区块>

      <可折叠区块 标题={t("帮助.三维标题")} 默认开={false}>
        <ul className="space-y-1">
          {三维操作.map((键) => <li key={键}>{t(键)}</li>)}
        </ul>
      </可折叠区块>

      <可折叠区块 标题={t("帮助.说明书标题")}>
        <p>{t("帮助.说明书说明")}</p>
        <div className="面板 mt-2 break-all px-2 py-1.5 等宽">docs/使用手册.md</div>
        <p className="mt-2 text-[0.85em] text-dim">{t("帮助.悬浮提示")}</p>
      </可折叠区块>

      <可折叠区块 标题={t("帮助.注意标题")} 默认开={false}>
        <ul className="space-y-1" style={{ color: "var(--warn)" }}>
          {注意项.map((键) => <li key={键}>{t(键)}</li>)}
        </ul>
      </可折叠区块>
    </div>
  );
}
