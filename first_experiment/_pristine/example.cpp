// Simple HTTP server in C++ (C++17) using cpp-httplib
// Compile with: g++ -std=c++17 -O2 -pthread example.cpp -o example

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
