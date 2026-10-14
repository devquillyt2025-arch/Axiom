// One-time (idempotent) setup: .env, Python venv + deps, frontend deps.
import { spawnSync } from "node:child_process";
import { copyFileSync, existsSync } from "node:fs";
import path from "node:path";
import { BACKEND, FRONTEND, ROOT, VENV_PY, systemPython, venvExists } from "./lib.mjs";

const run = (cmd, args, opts = {}) => {
  const r = spawnSync(cmd, args, { stdio: "inherit", ...opts });
  if (r.status !== 0) {
    console.error(`\n✖ Command failed: ${cmd} ${args.join(" ")}`);
    process.exit(r.status ?? 1);
  }
};

if (!existsSync(path.join(ROOT, ".env"))) {
  copyFileSync(path.join(ROOT, ".env.example"), path.join(ROOT, ".env"));
  console.log("✔ Created .env from .env.example — fill in your keys later (the app runs on demo data without them).");
}

if (!venvExists()) {
  const py = systemPython(spawnSync);
  if (!py) {
    console.error("✖ Python 3.10+ not found. Install it from https://www.python.org/downloads/ and re-run.");
    process.exit(1);
  }
  console.log(`▶ Creating Python virtualenv (${py})…`);
  run(py, ["-m", "venv", path.join(BACKEND, ".venv")]);
}

// pip is fast when everything is already installed, so just always run it.
console.log("▶ Installing backend dependencies…");
run(VENV_PY, ["-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-r", path.join(BACKEND, "requirements.txt")]);

if (!existsSync(path.join(FRONTEND, "node_modules"))) {
  console.log("▶ Installing frontend dependencies…");
  // npm is a .cmd shim on Windows, so it needs a shell; a single fixed command string is safe.
  const r = spawnSync("npm install --no-audit --no-fund", { cwd: FRONTEND, stdio: "inherit", shell: true });
  if (r.status !== 0) process.exit(r.status ?? 1);
}
console.log("✔ Setup complete.");
