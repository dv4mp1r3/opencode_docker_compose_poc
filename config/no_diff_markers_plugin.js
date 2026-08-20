// Harness-уровневая защита от бага: модель иногда вставляет в edit/write содержимое
// в виде unified-diff (строки, начинающиеся с "+"/"-"), а не чистый код файла.
// Обнаружено 2026-08-10 на задачах D' (RNFR/RNTO) и E (query-параметр) — не связано
// с длиной сессии (в E — всего 11 шагов), похоже на самостоятельный сбой формата.
//
// Хук tool.execute.before вызывается ДО применения edit/write с мутируемым объектом
// output.args. ВАЖНО (эмпирически проверено 2026-08-10): throw внутри хука здесь НЕ
// блокирует выполнение — opencode перехватывает и глушит исключения из "tool.execute.before"
// на уровне своего trigger-механизма, вызов инструмента всё равно проходит. Единственный
// рабочий рычаг — мутация output.args на месте (тот же паттерн, что использовался в архивном
// delegation.ts для "tool.definition"). Поэтому вместо отклонения вызова — молча чистим
// diff-маркеры из содержимого перед тем, как оно попадёт в execute().

// Расширения файлов, где "+"/"-" в начале строки — легитимный синтаксис
// (маркеры списков в Markdown, YAML), а не признак diff-разметки.
const SKIP_EXTENSIONS = /\.(md|markdown|yaml|yml)$/i;

// "+"/"-" в самом начале строки, затем НОЛЬ ИЛИ БОЛЬШЕ пробелов, затем буква/#/подчёркивание —
// так выглядит unified-diff маркер перед реальным кодом: "+    def foo():", "+        if (x) {",
// "+fmt.Println(1)" (без пробела). Не совпадает с легитимными "+=", "++", "+1", "-1" — сразу
// после маркера там не буква/подчёркивание, а цифра или ещё один операторный символ.
const DIFF_MARKER_LINE = /^([+-])(\s*)([A-Za-z_#].*)$/;

function stripDiffMarkers(content) {
  let changed = 0;
  const lines = content.split("\n").map((line) => {
    const m = line.match(DIFF_MARKER_LINE);
    if (!m) return line;
    changed++;
    // "+    def foo():" -> "    def foo():", "+fmt.Println(1)" -> "fmt.Println(1)" —
    // убираем сам маркер, сохраняя остаток строки как есть (включая исходный отступ, если он был)
    return m[2] + m[3];
  });
  return { content: lines.join("\n"), changed };
}

export default async function noDiffMarkersPlugin() {
  return {
    "tool.execute.before": async (input, output) => {
      if (input.tool !== "edit" && input.tool !== "write") return;

      const args = output.args;
      if (!args || typeof args !== "object") return;

      const filePath = args.filePath || args.path || "";
      if (SKIP_EXTENSIONS.test(filePath)) return;

      const field = typeof args.newString === "string" ? "newString" : "content";
      const content = args[field];
      if (typeof content !== "string") return;

      const { content: cleaned, changed } = stripDiffMarkers(content);
      if (changed > 0) {
        console.error(
          `[no_diff_markers_plugin] removed ${changed} diff-marker line(s) from ${field} in ${filePath}`
        );
        args[field] = cleaned;
      }
    },
  };
}
