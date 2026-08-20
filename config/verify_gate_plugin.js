// Harness-уровневый гейт обязательной функциональной проверки.
// Контекст и обоснование дизайна: first_experiment/user_story_plugin_development.md
// (там же — журнал решений, откуда взяты все "почему" ниже; этот файл только реализация).
//
// Три точки хука:
//   1. tool.execute.after  (edit/write) — сам инициирует проверку через $, не дожидаясь
//      решения модели; результат дописывает в output (подтверждено эмпирически: мутация
//      output здесь доходит до модели, см. user_story раздел 1.4).
//   2. tool.execute.before (edit/write) — throw, если предыдущая правка не подтверждена
//      (throw здесь подтверждённо блокирует вызов, см. user_story раздел 1.2).
//   3. cap = 3 попытки на файл — после этого гейт перестаёт блокировать (не создаёт дедлок
//      headless-сессии), но состояние "не подтверждено" остаётся видимым в output.
//
// Не решает: заблокировать сам текст финального ответа модели невозможно на этом API
// (event-хуки не блокируют, см. user_story раздел 1.3) — гейт блокирует действия, не слова.

import { existsSync, readFileSync, statSync } from "node:fs";
import path from "node:path";

const CAP_ATTEMPTS = 3;

// Приоритетный список project entrypoint (Вариант 2) — поиск вверх по дереву от
// директории изменённого файла до workspace root. Порядок и обоснование — user_story
// раздел 3.4 (синтез практики pre-commit/just/task/mise).
const ENTRYPOINT_CANDIDATES = [
  { file: "Makefile", type: "make" },
  { file: "makefile", type: "make" },
  { file: "Taskfile.yml", type: "task" },
  { file: "Taskfile.yaml", type: "task" },
  { file: "justfile", type: "just" },
  { file: "Justfile", type: "just" },
  { file: "mise.toml", type: "mise" },
  { file: "package.json", type: "npm" },
];

// Вариант 3 (fallback) — только статика, по расширению правленного файла. Сознательно не
// покрывает .cpp/.h (нет единого entrypoint без знания, какой файл — main) — для них при
// отсутствии project entrypoint проверка остаётся "недоступна", см. handleNoVerification.
const STATIC_CHECKS = {
  ".go": (relFile) => `go build -o /tmp/gate_verify_out '${relFile}'`,
  ".py": (relFile) => `python3 -m py_compile '${relFile}' && python3 -m pyflakes '${relFile}'`,
  ".ts": () => "npx tsc --noEmit",
  ".tsx": () => "npx tsc --noEmit",
};

function safeStringify(obj, max) {
  try {
    const s = JSON.stringify(obj);
    return s.length > max ? s.slice(0, max) + "...<truncated>" : s;
  } catch (e) {
    return "<unserializable>";
  }
}

function extractMakeTarget(makefileText) {
  for (const target of ["verify", "test"]) {
    const re = new RegExp("^" + target + ":", "m");
    if (re.test(makefileText)) return target;
  }
  return null;
}

function extractYamlLikeTarget(text) {
  // Не полноценный YAML/TOML-парсер — намеренная эвристика (см. TODO в user_story раздел 5).
  for (const target of ["verify", "test"]) {
    const re = new RegExp("^\\s*" + target + ":", "m");
    if (re.test(text)) return target;
  }
  return null;
}

function findEntrypoint(startDir, workspaceRoot) {
  let dir = path.resolve(startDir);
  const root = path.resolve(workspaceRoot);
  for (;;) {
    for (const cand of ENTRYPOINT_CANDIDATES) {
      const p = path.join(dir, cand.file);
      if (!existsSync(p) || !statSync(p).isFile()) continue;

      if (cand.type === "make") {
        const target = extractMakeTarget(readFileSync(p, "utf8"));
        if (target) return { dir, source: cand.file, cmd: `make -C '${dir}' ${target}` };
      } else if (cand.type === "task") {
        const target = extractYamlLikeTarget(readFileSync(p, "utf8"));
        if (target) return { dir, source: cand.file, cmd: `cd '${dir}' && task ${target}` };
      } else if (cand.type === "just") {
        const target = extractYamlLikeTarget(readFileSync(p, "utf8"));
        if (target) return { dir, source: cand.file, cmd: `cd '${dir}' && just ${target}` };
      } else if (cand.type === "mise") {
        const text = readFileSync(p, "utf8");
        const m = text.match(/\[tasks\.(verify|test)\]/);
        if (m) return { dir, source: cand.file, cmd: `cd '${dir}' && mise run ${m[1]}` };
      } else if (cand.type === "npm") {
        try {
          const pkg = JSON.parse(readFileSync(p, "utf8"));
          if (pkg.scripts && pkg.scripts.test) {
            return { dir, source: cand.file, cmd: `cd '${dir}' && npm test` };
          }
        } catch (e) {
          // битый package.json — пропускаем, не считаем это entrypoint'ом
        }
      }
    }
    if (dir === root || dir === path.dirname(dir)) break;
    dir = path.dirname(dir);
  }
  return null;
}

function findStaticCheck(relFilePath) {
  const ext = path.extname(relFilePath);
  const builder = STATIC_CHECKS[ext];
  if (!builder) return null;
  return { cmd: builder(relFilePath), source: `static:${ext}` };
}

async function runCheck(cmd, cwd, $) {
  try {
    const proc = $`bash -c ${cmd}`.cwd(cwd).nothrow().quiet();
    const result = await proc;
    const stdout = result.stdout ? result.stdout.toString() : "";
    const stderr = result.stderr ? result.stderr.toString() : "";
    return { exitCode: result.exitCode, stdout, stderr };
  } catch (e) {
    return { exitCode: 1, stdout: "", stderr: "harness error running check: " + (e && e.message ? e.message : String(e)) };
  }
}

function truncate(s, max) {
  if (!s) return "";
  return s.length > max ? s.slice(0, max) + "\n...<обрезано>" : s;
}

export default async function verifyGatePlugin({ directory, $ }) {
  const workspaceRoot = directory || "/workspace";
  const sessions = new Map(); // sessionID -> state

  function getState(sessionID) {
    if (!sessions.has(sessionID)) {
      sessions.set(sessionID, {
        pendingVerification: false,
        attemptsSinceEdit: 0,
        lastFile: null,
        lastResultSummary: null,
      });
    }
    return sessions.get(sessionID);
  }

  return {
    "tool.execute.before": async (input, output) => {
      if (input.tool !== "edit" && input.tool !== "write") return;
      const state = getState(input.sessionID);
      if (!state.pendingVerification) return;
      if (state.attemptsSinceEdit >= CAP_ATTEMPTS) {
        // Cap исчерпан — не блокируем дальше (не создаём дедлок), но состояние остаётся
        // видимым через lastResultSummary в следующей инъекции.
        return;
      }
      const file = (output && output.args && (output.args.filePath || output.args.path)) || state.lastFile || "?";
      throw new Error(
        `HARNESS GATE: правка "${state.lastFile}" не подтверждена автопроверкой ` +
        `(попытка ${state.attemptsSinceEdit}/${CAP_ATTEMPTS}). ` +
        `Последний результат: ${state.lastResultSummary || "проверка ещё не запускалась"}. ` +
        `Сначала устраните ошибку в "${state.lastFile}", следующая правка (в т.ч. "${file}") невозможна, пока проверка не пройдёт.`
      );
    },

    "tool.execute.after": async (input, output) => {
      if (input.tool !== "edit" && input.tool !== "write") return;
      const args = input.args || {};
      const filePath = args.filePath || args.path;
      if (!filePath) return;

      const state = getState(input.sessionID);
      state.lastFile = filePath;

      const absFile = path.isAbsolute(filePath) ? filePath : path.join(workspaceRoot, filePath);
      const fileDir = path.dirname(absFile);

      let check = findEntrypoint(fileDir, workspaceRoot);
      let checkKind = "project-entrypoint";
      if (!check) {
        const staticCheck = findStaticCheck(filePath);
        if (staticCheck) {
          check = { dir: workspaceRoot, source: staticCheck.source, cmd: staticCheck.cmd };
          checkKind = "static-fallback";
        }
      }

      let note;
      if (!check) {
        state.pendingVerification = false; // нечем проверить — не блокируем (см. user_story TODO)
        state.attemptsSinceEdit = 0;
        state.lastResultSummary = "нет известного способа проверки для этого типа файла";
        note = `\n\n[HARNESS AUTO-VERIFY] NO METHOD AVAILABLE — для "${filePath}" не найден ни project entrypoint, ни статическая проверка. Это НЕ подтверждает корректность, только означает, что механическая проверка недоступна.`;
      } else {
        const result = await runCheck(check.cmd, check.dir, $);
        const passed = result.exitCode === 0;
        state.attemptsSinceEdit += 1;
        if (passed) {
          state.pendingVerification = false;
          state.attemptsSinceEdit = 0;
          state.lastResultSummary = `PASSED (${checkKind}: ${check.source})`;
        } else {
          state.pendingVerification = true;
          state.lastResultSummary = `FAILED (${checkKind}: ${check.source}, exit=${result.exitCode})`;
        }
        const combinedOutput = truncate((result.stdout || "") + (result.stderr ? "\n" + result.stderr : ""), 2000);
        note = `\n\n[HARNESS AUTO-VERIFY] ${passed ? "PASSED" : "FAILED"} — команда: ${check.cmd} (источник: ${checkKind}/${check.source})\n${combinedOutput}`;
      }

      if (output && typeof output === "object") {
        if (typeof output.output === "string") {
          output.output += note;
        }
        if (output.metadata && typeof output.metadata === "object") {
          output.metadata.harnessVerify = { pending: state.pendingVerification, summary: state.lastResultSummary };
        }
      }
    },
  };
}
