// Boots the FastAPI backend (:8000) and the Next.js frontend (:3000) together.
//   node scripts/dev.mjs           -> next dev  (hot reload)
//   node scripts/dev.mjs --prod    -> next build (if needed) + next start
// Ctrl+C stops both. NOTE: a running trading BOT is a separate process and keeps going until
// 15:25 IST (or until you press Stop in the Bot tab) — closing this launcher does not abandon
// open positions unmanaged.
import { spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { BACKEND, FRONTEND, IS_WIN, NEXT_BIN, VENV_PY, venvExists } from "./lib.mjs";

if (!venvExists()) {
  console.error("✖ Python environment missing. Run `npm run setup` (or ./start.sh) first.");
  process.exit(1);
}
const prod = process.argv.includes("--prod");
const apiPort = process.env.API_PORT || "8000";
const webPort = process.env.WEB_PORT || "3000";

if (prod && !existsSync(path.join(FRONTEND, ".next", "BUILD_ID"))) {
  console.log("▶ Building the frontend (first production run)…");
  const b = spawnSync(process.execPath, [NEXT_BIN, "build"], { cwd: FRONTEND, stdio: "inherit" });
  if (b.status !== 0) process.exit(b.status ?? 1);
}

const COLORS = { api: "\x1b[36m", web: "\x1b[35m" };
const procs = [];
let shuttingDown = false;

function start(name, cmd, args, cwd, env = {}) {
  const p = spawn(cmd, args, { cwd, env: { ...process.env, ...env }, stdio: ["ignore", "pipe", "pipe"] });
  const tag = `${COLORS[name]}[${name}]\x1b[0m `;
  const pipe = (stream) => {
    let buf = "";
    stream.on("data", (d) => {
      buf += d.toString();
      const lines = buf.split(/\r?\n/);
      buf = lines.pop() ?? "";
      for (const l of lines) if (l.trim()) console.log(tag + l);
    });
  };
  pipe(p.stdout);
  pipe(p.stderr);
  p.on("exit", (code) => {
    if (!shuttingDown) {
      console.log(`${tag}exited (${code}) — stopping everything`);
      shutdown(code ?? 1);
    }
  });
  procs.push(p);
}

function shutdown(code = 0) {
  if (shuttingDown) return;
  shuttingDown = true;
  for (const p of procs) {
    if (p.exitCode !== null) continue;
    if (IS_WIN) spawnSync("taskkill", ["/pid", String(p.pid), "/T", "/F"], { stdio: "ignore" });
    else p.kill("SIGTERM");
  }
  setTimeout(() => process.exit(code), 400);
}
process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));

// 127.0.0.1 only: the API can place real orders, so it must not be reachable from the network.
start("api", VENV_PY, ["-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", apiPort], BACKEND);
start("web", process.execPath, [NEXT_BIN, prod ? "start" : "dev", "-p", webPort], FRONTEND);

console.log(`\n  Axiom  →  http://localhost:${webPort}   (API http://127.0.0.1:${apiPort}/docs)\n`);
