const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { loadFrontendModule } = require("./frontend_test_loader.cjs");
const root = path.resolve(__dirname, "../..");
const ts = require(process.env.YUBI_TYPESCRIPT_PATH || path.join(root, "frontend/node_modules/typescript"));
const compile = (source) => ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;

const appPath = path.join(root, "frontend/src/shell/App.tsx");
const app = ts.createSourceFile(appPath, fs.readFileSync(appPath, "utf8"), ts.ScriptTarget.Latest, true);
const preferenceNames = new Set(["STORAGE_KEY", "DEFAULT_PREFERENCES", "SIDEBAR_LIMITS", "CONSOLE_LIMITS"]);
const declarations = app.statements.filter((node) =>
  ts.isInterfaceDeclaration(node) && node.name.text === "ShellPreferences" ||
  ts.isFunctionDeclaration(node) && ["readPreferences", "clamp"].includes(node.name?.text) ||
  ts.isVariableStatement(node) && node.declarationList.declarations.some((item) => preferenceNames.has(item.name.getText(app))),
).map((node) => node.getText(app)).join("\n");
for (const [stored, expected] of [
  [null, { sidebarWidth: 330, consoleHeight: 150, sidebarOpen: true }],
  ['{"侧栏宽":420,"控制台高":220,"侧栏开":false}', { sidebarWidth: 420, consoleHeight: 220, sidebarOpen: false }],
  ['{"sidebarWidth":430,"consoleHeight":230,"sidebarOpen":true}', { sidebarWidth: 430, consoleHeight: 230, sidebarOpen: true }],
  ['{"侧栏宽":9999,"控制台高":-10}', { sidebarWidth: 640, consoleHeight: 90, sidebarOpen: true }],
  ["invalid JSON", { sidebarWidth: 330, consoleHeight: 150, sidebarOpen: true }],
]) {
  const exportsObject = {};
  vm.runInNewContext(compile(declarations + "\nexports.read = readPreferences;"), {
    exports: exportsObject, window: { localStorage: { getItem: () => stored } },
  });
  assert.deepEqual(JSON.parse(JSON.stringify(exportsObject.read())), expected);
}

const nativeMessages = [];
const logExports = loadFrontendModule("data/logs.ts", {
  globals: { Date: { now: () => 123456 }, queueMicrotask,
    window: { webkit: { messageHandlers: { "驭臂日志": { postMessage: (message) => nativeMessages.push(message) } } } },
  },
  mocks: { react: {}, "./store": {}, "./toasts": {}, "../views/i18n": {} },
});
logExports.logInfo("console", "Test entry", "test.topic");
assert.deepEqual(JSON.parse(JSON.stringify(nativeMessages[0])), {
  "墙钟": 123456, "等级": "信息", "来源": "控制台", "文本": "Test entry",
  "细节": "", "模块": "", "插件": "", "关节": null,
});
assert.equal(logExports.getLogs().row[0].topic, "test.topic");
console.log("Frontend state regression passed: legacy/new preferences, layout bounds and native log payload.");
