const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "../..");
const ts = require(process.env.YUBI_TYPESCRIPT_PATH || path.join(root, "前端/node_modules/typescript"));
const source = fs.readFileSync(path.join(root, "前端/src/数据/connection.ts"), "utf8");
const sockets = [];
const timers = new Map();
let nextTimer = 1;

class FakeSocket {
  static OPEN = 1;
  constructor(url) {
    this.url = url;
    this.readyState = FakeSocket.OPEN;
    this.sent = [];
    sockets.push(this);
  }
  send(message) { this.sent.push(message); }
  close() { this.readyState = 3; this.onclose?.(); }
}

const exportsObject = {};
const schedule = (callback, milliseconds) => {
  const id = nextTimer++;
  timers.set(id, { callback, milliseconds });
  return id;
};
const javascript = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
vm.runInNewContext(javascript, {
  exports: exportsObject,
  require: () => ({ "协议版本": 21 }),
  WebSocket: FakeSocket,
  window: {
    setTimeout: schedule, setInterval: schedule,
    clearTimeout: (id) => timers.delete(id), clearInterval: (id) => timers.delete(id),
  },
  Date: { now: () => 100000 },
  console,
});

async function main() {
  const connection = new exportsObject.BackendConnection("ws://localhost/");
  const events = [];
  connection.subscribe((event) => events.push(event));
  connection.connect();
  const socket = sockets[0];
  socket.onopen();
  const first = connection.sendCommand("command.simulation", { action: "run" });
  const second = connection.sendCommand("command.simulation", { action: "pause" });
  assert.equal(socket.sent[0], '{"请求":"255s-1","主题":"command.simulation","数据":{"action":"run"}}');
  assert.equal(socket.sent[1], '{"请求":"255s-2","主题":"command.simulation","数据":{"action":"pause"}}');

  const emit = (topic, data, sequence) => socket.onmessage({
    data: JSON.stringify({ "协议": 21, "主题": topic, "数据": data, "序号": sequence }),
  });
  const receipt = (id, description) => ({ "请求": id, "主题": "command.simulation", "通过": true, "说明": description });
  emit("__回执__", receipt("255s-2", "pause"));
  emit("__回执__", receipt("255s-1", "run"));
  const results = await Promise.all([first, second]);
  assert.equal(results[0]["说明"], "run");
  assert.equal(results[1]["说明"], "pause");

  emit("__问候__", { "可用主题": ["metrics"], "广播间隔": 0.05 });
  assert.equal(events.at(-1).handshake["广播间隔"], 0.05);
  emit("metrics", { value: 1 }, 7);
  assert.equal(connection.counts.metrics, 1);
  assert.equal(connection.latestSequence, 7);
  socket.onmessage({ data: '{"协议":999,"主题":"metrics","数据":{}}' });
  assert.match(events.at(-1).error, /999/);
  assert.equal(connection.counts.metrics, 1);

  const pending = connection.sendCommand("command.simulation", { action: "reset" });
  connection.close();
  assert.equal((await pending)["通过"], false);
  assert.equal(timers.size, 0);
  console.log("Connection regression passed: v21 wire bytes, receipt order, handshake, protocol guard and cleanup.");
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
