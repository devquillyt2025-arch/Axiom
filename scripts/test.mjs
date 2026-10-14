// Runs the backend test-suite and the frontend typecheck + lint.
import { spawnSync } from "node:child_process";
import path from "node:path";
import { BACKEND, FRONTEND, NEXT_BIN, TSC_BIN, VENV_PY, venvExists } from "./lib.mjs";

if (!venvExists()) {
  console.error("✖ Run `npm run setup` first.");
  process.exit(1);
}
const steps = [
  ["backend lint (pyflakes)", VENV_PY, ["-m", "pyflakes", "core", "bot", "api", "backtest", "strategies", "main.py", "tests"], BACKEND],
  ["backend tests", VENV_PY, ["-m", "pytest", "-q"], BACKEND],
  ["frontend typecheck", process.execPath, [TSC_BIN, "--noEmit"], FRONTEND],
  ["frontend lint", process.execPath, [NEXT_BIN, "lint"], FRONTEND],
];
let failed = false;
// make sure pytest / pyflakes exist (dev dependencies)
spawnSync(VENV_PY, ["-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-r", path.join(BACKEND, "requirements-dev.txt")], { stdio: "inherit" });
for (const [name, cmd, args, cwd] of steps) {
  console.log(`\n▶ ${name}`);
  const r = spawnSync(cmd, args, { cwd, stdio: "inherit" });
  if (r.status !== 0) failed = true;
}
process.exit(failed ? 1 : 0);
