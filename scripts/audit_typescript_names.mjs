/** Parse identifiers with TypeScript so Chinese text and comments stay untouched. */
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const request = JSON.parse(fs.readFileSync(0, "utf8"));
const require = createRequire(path.join(request.root, "前端", "package.json"));
let ts;
try {
  ts = require(process.env.YUBI_TYPESCRIPT_PATH || "typescript");
} catch {
  process.stderr.write("TypeScript is required. Install frontend dependencies or set YUBI_TYPESCRIPT_PATH.\n");
  process.exit(2);
}

const findings = [];
const errors = [];
for (const relative of request.files) {
  const filename = path.join(request.root, relative);
  if (path.extname(relative) === ".json") {
    const parsed = ts.parseConfigFileTextToJson(filename, fs.readFileSync(filename, "utf8"));
    if (parsed.error) {
      errors.push(`${relative}: ${ts.flattenDiagnosticMessageText(parsed.error.messageText, " ")}`);
    } else {
      function keys(value, prefix = "") {
        if (Array.isArray(value)) {
          value.forEach(child => keys(child, `${prefix}/[]`));
        } else if (value && typeof value === "object") {
          for (const [key, child] of Object.entries(value)) {
            const pointer = `${prefix}/${key.replaceAll("~", "~0").replaceAll("/", "~1")}`;
            if (/[^\x00-\x7f]/u.test(key)) {
              findings.push({ path: relative, line: 0, category: "json_key", name: pointer });
            }
            keys(child, pointer);
          }
        }
      }
      keys(parsed.config);
    }
    continue;
  }
  const source = ts.createSourceFile(
    filename, fs.readFileSync(filename, "utf8"), ts.ScriptTarget.Latest, true,
  );
  for (const diagnostic of source.parseDiagnostics) {
    errors.push(`${relative}: ${ts.flattenDiagnosticMessageText(diagnostic.messageText, " ")}`);
  }
  function add(node, category, name) {
    if (!/[^\x00-\x7f]/u.test(name)) return;
    const { line } = source.getLineAndCharacterOfPosition(node.getStart(source));
    findings.push({ path: relative, line: line + 1, category, name });
  }
  function visit(node) {
    if (ts.isIdentifier(node) || ts.isPrivateIdentifier(node)) {
      add(node, "typescript_identifier", node.text);
    } else if (ts.isStringLiteral(node)) {
      if (node.parent.name === node || ts.isElementAccessExpression(node.parent)
          && node.parent.argumentExpression === node) add(node, "string_key", node.text);
      if ((ts.isImportDeclaration(node.parent) || ts.isExportDeclaration(node.parent))
          && node.parent.moduleSpecifier === node) {
        add(node, "import_path", node.text);
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(source);
}
process.stdout.write(JSON.stringify({ findings, errors }));
