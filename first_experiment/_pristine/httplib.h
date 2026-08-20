#ifndef HTTPLIB_H
# define HTTPLIB_H

// Minimal HTTP server implementation (TCP only, no TLS)
// Compatible with example.cpp usage of httplib::Server, ::Request, ::Response.

#include <sys/types.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <cstring>
#include <string>
#include <sstream>
#include <unordered_map>
#include <functional>
#include <iostream>
#include <map>

namespace httplib {

struct Request {
    std::string path; // request path, e.g., "/index.html"
};

struct Response {
    std::string body = "";
    std::string content_type = "text/plain";
    int status = 200;
    void set_content(const std::string &b, const std::string &ct) {
        body = b;
        content_type = ct;
    }
};

class Server {
public:
    using handler_type = std::function<void(const Request &, Response &)>;

    void Get(const std::string &path, handler_type h) {
        if (path == "/" || path.empty()) {
            default_handler_ = std::move(h);
        } else {
            handlers_[path] = std::move(h);
        }
    }

    bool listen(const std::string &host, uint16_t port) {
        int server_fd = socket(AF_INET, SOCK_STREAM, 0);
        if (server_fd == -1) return false;
        int opt = 1;
        setsockopt(server_fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

        struct sockaddr_in address;
        ::memset(&address, 0, sizeof(address));
        address.sin_family = AF_INET;
        address.sin_port = htons(port);
        if (host == "0.0.0.0") {
            address.sin_addr.s_addr = INADDR_ANY;
        } else {
            if (inet_pton(AF_INET, host.c_str(), &address.sin_addr) <= 0) {
                close(server_fd);
                return false;
            }
        }

        if (bind(server_fd, reinterpret_cast<struct sockaddr *>(&address), sizeof(address)) < 0) {
            close(server_fd);
            return false;
        }

        if (::listen(server_fd, 10) < 0) {
            close(server_fd);
            return false;
        }

        while (true) {
            struct sockaddr_in client_addr;
            socklen_t client_len = sizeof(client_addr);
            int client_fd = accept(server_fd, reinterpret_cast<struct sockaddr *>(&client_addr), &client_len);
            if (client_fd < 0) {
                continue;
            }

            std::string request;
            char buf[65536];
            ssize_t bytes = 0;
            while ((bytes = recv(client_fd, buf, sizeof(buf), 0)) > 0) {
                request.append(buf, bytes);
                if (request.find("\r\n\r\n") != std::string::npos) {
                    break;
                }
            }
            if (bytes <= 0) {
                close(client_fd);
                continue;
            }

            std::istringstream rs(request);
            std::string req_line;
            std::getline(rs, req_line);
            if (!req_line.empty() && req_line.back() == '\r') {
                req_line.pop_back();
            }
            std::istringstream line_stream(req_line);
            std::string method, path, http_version;
            line_stream >> method >> path >> http_version;

            handler_type handler = nullptr;
            auto it = handlers_.find(path);
            if (it != handlers_.end()) {
                handler = it->second;
            } else if (default_handler_) {
                handler = default_handler_;
            } else {
                std::string body = "404 Not Found";
                std::string http_resp = build_http_response(404, body, "text/plain");
                send(client_fd, http_resp.c_str(), http_resp.size(), 0);
                close(client_fd);
                continue;
            }

            Request req{path};
            Response res;
            handler(req, res);

            int status = res.status;
            std::string body = res.body;
            std::string content_type = res.content_type;

            std::string http_resp = build_http_response(status, body, content_type);
            send(client_fd, http_resp.c_str(), http_resp.size(), 0);
            close(client_fd);
        }
        close(server_fd);
        return true;
    }

private:
    handler_type default_handler_{nullptr};
    std::unordered_map<std::string, handler_type> handlers_;

    static std::string status_message(int code) {
        static std::map<int, std::string> messages = {
            {200, "OK"},
            {404, "Not Found"},
            {500, "Internal Server Error"}
        };
        auto it = messages.find(code);
        if (it != messages.end()) return it->second;
        return "OK";
    }

    static std::string build_http_response(int status, const std::string &body, const std::string &content_type) {
        std::ostringstream oss;
        oss << "HTTP/1.1 " << status << " " << status_message(status) << "\r\n";
        oss << "Content-Length: " << body.size() << "\r\n";
        oss << "Content-Type: " << content_type << "\r\n";
        oss << "Connection: close\r\n";
        oss << "\r\n";
        oss << body;
        return oss.str();
    }
};

} // namespace httplib

#endif // HTTPLIB_H
