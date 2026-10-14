// Эталонное решение задачи E (раунд 4) — рукописное, ДВЕ роли:
// 1. валидация верификатора гейта (verify_gate.py --verify-only должен дать
//    PASS на этом файле) — без этого FAIL-результаты пилота неотличимы от
//    сломанного верификатора;
// 2. документация корректного подхода для разбора пилотных прогонов.
//
// Ключевое знание (находка раунда 3): диспетчеризация минимальной httplib
// матчит ПОЛНЫЙ путь с query (handlers_.find(path), где path = "/hello?name=…"),
// поэтому отдельный svr.Get("/hello") — «мёртвый» хендлер; запрос попадает в
// дефолтный "/". Решение — ветвление по req.path внутри "/"-хендлера.
// req.params НЕ существует в минимальной фикстуре (галлюцинация прогона 3-retry:
// в настоящем cpp-httplib поле есть, здесь Request — только std::string path),
// query парсится вручную.

#include <iostream>
#include <filesystem>
#include <fstream>
#include <string>

#include "httplib.h" // single‑file header, can be included from third‑party libs or embedded

int main(int argc, char* argv[]) {
    int port = 3000;
    std::string root = "";

    // Basic argument parsing
    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--port" && i + 1 < argc) {
            port = std::stoi(argv[++i]);
        } else if (arg == "--dir" && i + 1 < argc) {
            root = argv[++i];
        }
    }

    httplib::Server svr;

    svr.Get("/", [&](const httplib::Request& req, httplib::Response& res) {
        // Task E: greet endpoint. Dispatch matches the full path including
        // the query string, so /hello?name=... lands here, in the default
        // handler — it must be handled before the file-serving logic.
        if (req.path == "/hello" || req.path.rfind("/hello?", 0) == 0) {
            std::string name;
            std::string query = req.path.substr(req.path.find('?') + 1);
            size_t pos = 0;
            while (pos < query.size()) {
                size_t amp = query.find('&', pos);
                std::string pair = query.substr(
                    pos, amp == std::string::npos ? std::string::npos : amp - pos);
                if (pair.rfind("name=", 0) == 0) {
                    name = pair.substr(5);
                    break;
                }
                if (amp == std::string::npos) break;
                pos = amp + 1;
            }
            res.set_content("Hello, " + name + "!", "text/plain");
            res.status = 200;
            return;
        }

        // Resolve file path relative to root directory
        std::filesystem::path p = root.empty() ? std::filesystem::current_path() : std::filesystem::path(root);
        std::string sub = req.path.substr(1); // remove leading '/'
        if (sub.empty()) sub = "index.html";
        p /= sub;

        if (std::filesystem::exists(p) && std::filesystem::is_regular_file(p)) {
            std::ifstream file(p, std::ios::binary | std::ios::ate);
            if (file) {
                std::streamsize size = file.tellg();
                file.seekg(0, std::ios::beg);
                std::string buffer(size, '\0');
                file.read(&buffer[0], size);
                res.set_content(buffer, "text/plain");
                res.status = 200;
            } else {
                res.status = 500;
                res.set_content("Cannot read file", "text/plain");
            }
        } else {
            // Directory listing if target is not a file
            std::string dirs;
            for (const auto &entry : std::filesystem::directory_iterator(p.parent_path())) {
                dirs += entry.path().filename().string() + "\n";
            }
            res.set_content("<html><body><h1>Directory listing</h1>\n<pre>" + dirs + "</pre></body></html>", "text/html");
        }

    });

    std::cout << "Serving at http://localhost:" << port << "/\n";
    svr.listen("0.0.0.0", port);

    return 0;
}
