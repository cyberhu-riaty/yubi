/**
 * 航点文件.ts —— 把用户手里的 CSV/TXT 解析成关节航点。
 *
 * ★ 为什么解析放在**前端**：
 *   浏览器有文件选择器，用户点一下就能选；若放到后端，就得让用户手打路径，
 *   而"路径"这件事在桌面 app 里还牵扯到 TCC 沙箱权限（之前踩过）。
 *   解析是纯函数，放哪都一样 —— 放前端少一层往返、也少一个权限面。
 *
 * ★ 解析规则（必须写在界面上，否则用户不知道该怎么准备文件）：
 *   · 逗号或空格分隔；每行一组关节角
 *   · **跳过**以 `#` `//` 开头的注释行与空行
 *   · 如果有表头（含字母），自动跳过第一行
 *   · 每行的列数必须一致，且 ≥2 列
 *   · 无法解析的数字 → 报出**行号**，不静默丢弃
 */

export interface WaypointParseResult {
  waypoints: number[][];
  rowCount: number;
  columnCount: number;
  skipped: number;       // 注释/空行数
  error: string;       // 空串 = 没问题
}

const NUMBER_PATTERN = /^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/;

export function parseWaypointText(text: string, expectedColumns?: number): WaypointParseResult {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const waypoints: number[][] = [];
  let skipped = 0;
  let hasHeader = false;
  let columnCount = 0;

  for (let i = 0; i < lines.length; i += 1) {
    const raw = lines[i].trim();
    if (!raw || raw.startsWith("#") || raw.startsWith("//")) {
      skipped += 1;
      continue;
    }
    // 分隔符：逗号 / 制表符 / 空白（CSV 与纯文本都吃）
    const segments = raw.split(/[,\t]+|\s+/).filter((s) => s.length > 0);
    const allNumeric = segments.every((s) => NUMBER_PATTERN.test(s));
    if (!allNumeric) {
      // 只允许**第一行**不是数字（当表头），其余必须报错并指出行号
      if (waypoints.length === 0 && !hasHeader) {
        hasHeader = true;
        skipped += 1;
        continue;
      }
      return {
        waypoints: waypoints, rowCount: waypoints.length, columnCount: columnCount || segments.length, skipped: skipped,
        error: `第 ${i + 1} 行有无法解析的内容：「${segments.slice(0, 4).join(" ")}」`,
      };
    }
    const values = segments.map(Number);
    if (!columnCount) {
      columnCount = values.length;
      if (columnCount < 2) {
        return { waypoints: waypoints, rowCount: 0, columnCount: columnCount, skipped: skipped, error: `只有 ${columnCount} 列 —— 关节航点至少 2 列` };
      }
    } else if (values.length !== columnCount) {
      return {
        waypoints: waypoints, rowCount: waypoints.length, columnCount: columnCount, skipped: skipped,
        error: `第 ${i + 1} 行有 ${values.length} 列，前面是 ${columnCount} 列（列数必须一致）`,
      };
    }
    waypoints.push(values);
  }

  if (waypoints.length < 2) {
    return { waypoints: waypoints, rowCount: waypoints.length, columnCount: columnCount, skipped: skipped, error: `只解析出 ${waypoints.length} 个航点 —— 至少需要 2 个` };
  }
  if (expectedColumns !== undefined && columnCount !== expectedColumns) {
    return {
      waypoints: waypoints, rowCount: waypoints.length, columnCount: columnCount, skipped: skipped,
      error: `文件是 ${columnCount} 列，但当前机器人是 ${expectedColumns} 个关节`,
    };
  }
  return { waypoints: waypoints, rowCount: waypoints.length, columnCount: columnCount, skipped: skipped, error: "" };
}
