// Shared helpers for the launcher scripts (cross-platform: Windows / macOS / Linux).
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const BACKEND = path.join(ROOT, "backend");
export const FRONTEND = path.join(ROOT, "frontend");
export const IS_WIN = process.platform === "win32";

export const VENV_PY = IS_WIN
  ? path.join(BACKEND, ".venv", "Scripts", "python.exe")
  : path.join(BACKEND, ".venv", "bin", "python");

export const venvExists = () => existsSync(VENV_PY);

/** Frontend CLIs are launched through `node` directly — no shell, no npm wrapper, no Windows quirks. */
export const NEXT_BIN = path.join(FRONTEND, "node_modules", "next", "dist", "bin", "next");
export const TSC_BIN = path.join(FRONTEND, "node_modules", "typescript", "bin", "tsc");

/** Find a system Python 3.10+ to create the venv with. */
export function systemPython(spawnSync) {
  for (const cmd of IS_WIN ? ["py", "python", "python3"] : ["python3", "python"]) {
    const r = spawnSync(cmd, ["-c", "import sys; print(sys.version_info >= (3, 10))"], { encoding: "utf8" });
    if (r.status === 0 && r.stdout.trim() === "True") return cmd;
  }
  return null;
}
