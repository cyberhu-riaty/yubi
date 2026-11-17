const assert = require("node:assert/strict");
const { loadFrontendModule } = require("./frontend_test_loader.cjs");
const codec = loadFrontendModule("data/wire_compatibility.ts");
const plain = (value) => JSON.parse(JSON.stringify(value));

const fixtures = {
  "指标": { "时间": 1, "墙钟": 20, "数值": { "肩关节·误差": 0.2 } },
  "系统": { "仿真时间": 2, "墙钟": 20, "RTF": 1, "内存MB": 12, extension: { name: "保留" } },
  "控制状态": { "关节名": ["j1"], "当前位置": [1], "目标": [2], "说明": "已接受" },
  "诊断": { "运行中": false, "通过": 1, "总数": 1, "项": [{ "名": "test", "通过": true, "说明": "完成", "秒": 0.1 }] },
  "插件目录": { "数量": 1, "插件": [{ "插件": "pd", "名称": "关节控制", "当前启用": true, "当前顺序": 0 }] },
  "project.state": { project: "test", algorithms: [{ "名称": "PD", "版本": "1", "接管控制": true }] },
  "设备连接": { "已连接": true, "安全状态": "使能中", "审计": [{ "时刻": 1, "类别": "停止", "内容": "test", "错误码": "E1" }] },
  "告警": { "活动": [{ "类型": "跟踪超差", "严重度": "注意", "曲线": [0, 1], "曲线t": [1, 2] }], "已检出": 1 },
  "部署": { "目录": "/tmp/test", "文件数": 1, "清单": [{ "文件": "model.xml", "字节": 23 }] },
  "辨识状态": { "状态": "完成", "结果": [{ "名称": "mass", "标称": 1, "辨识值": 1.1, "变化": 0.1 }], "拟合": { "前": 2, "后": 1 }, "日志": ["完成"] },
};
for (const [topic, original] of Object.entries(fixtures)) {
  const snapshot = JSON.stringify(original);
  const decoded = codec.decodeServerPayload(topic, original);
  assert.deepEqual(plain(codec.encodeServerPayload(topic, decoded)), original, topic);
  assert.equal(JSON.stringify(original), snapshot, `Mutated source: ${topic}`);
}
const metrics = codec.decodeServerPayload("指标", fixtures["指标"]);
assert.deepEqual(plain(metrics.values), { "肩关节·误差": 0.2 });
assert.equal(codec.decodeServerPayload("诊断", fixtures["诊断"]).items[0].passed, true);
assert.equal(codec.decodeServerPayload("设备连接", fixtures["设备连接"]).audit[0].error_code, "E1");
assert.equal(codec.decodeServerPayload("辨识状态", fixtures["辨识状态"]).fit.before, 2);
const productionResult = {
  "结果": [["mass", 1, 1.1, 10], ["second", 2, 2.2, 10, "extension"]],
  "拟合": { "标称": 2, "辨识后": 1 },
};
const decodedResult = codec.decodeServerPayload("辨识状态", productionResult);
assert.equal(decodedResult.results[0].name, "mass");
assert.equal(decodedResult.fit.nominal, 2);
assert.deepEqual(plain(codec.encodeServerPayload("辨识状态", decodedResult)), productionResult);
assert.equal(codec.encodeCommand("request-1", "命令.高亮", { joint: 2, seconds: 4 }),
  '{"请求":"request-1","主题":"命令.高亮","数据":{"关节":2,"秒":4}}');
assert.equal(codec.encodeCommand("request-1", "命令.高亮", { "关节": 2, "秒": 4 }),
  '{"请求":"request-1","主题":"命令.高亮","数据":{"关节":2,"秒":4}}');
assert.throws(() => codec.decodeServerPayload("系统", { "内存MB": 1, memory_mb: 2 }), /Duplicate/);
assert.throws(() => codec.decodeFrame(null), /topic/);
assert.deepEqual(plain(codec.decodeReceipt({ "请求": "a", "主题": "test", "通过": true, "说明": "ok" })),
  { request_id: "a", topic: "test", passed: true, description: "ok" });
console.log("Wire compatibility passed: 10 nested snapshots round-trip, unchanged command bytes and legacy exports.");
