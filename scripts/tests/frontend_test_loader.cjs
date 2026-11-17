const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const root = path.resolve(__dirname, "../../frontend/src");
const ts = require(process.env.YUBI_TYPESCRIPT_PATH || path.resolve(root, "../node_modules/typescript"));

function loadFrontendModule(relative, { globals = {}, mocks = {} } = {}) {
  const cache = new Map();
  function load(filename) {
    if (!path.extname(filename)) filename += ".ts";
    if (cache.has(filename)) return cache.get(filename).exports;
    const module = { exports: {} };
    cache.set(filename, module);
    const javascript = ts.transpileModule(fs.readFileSync(filename, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    }).outputText;
    const requireModule = (specifier) => {
      if (Object.hasOwn(mocks, specifier)) return mocks[specifier];
      if (specifier.startsWith("@generated/")) return load(path.join(root, "generated", specifier.slice(11)));
      if (specifier.startsWith(".")) return load(path.resolve(path.dirname(filename), specifier));
      throw new Error(`Missing test dependency: ${specifier}`);
    };
    vm.runInNewContext(javascript, {
      module, exports: module.exports, require: requireModule, console, ...globals,
    }, { filename });
    return module.exports;
  }
  return load(path.resolve(root, relative));
}

module.exports = { loadFrontendModule };
