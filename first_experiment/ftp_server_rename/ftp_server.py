#!/usr/bin/env python3
"""
Мини‑FTP сервер, реализованный только с использованием стандартных библиотек Python.

Функциональность:
- Хардкоженные учётные данные: пользователь «user», пароль «pass».
- Аутентификация (USER/PASS).
- Навигация по каталогам (CWD, PWD).
- Список файлов через LIST.
- Передача файлов RETR.
- Активный (PORT) и пассивный (PASV) режимы передачи данных.

Запуск:
    python3 ftp_server.py --root /полный/путь
"""

import os
import socket
import argparse
import socketserver
import time
from typing import Optional
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# --- Константы ответов ---------------------------------------------------
REPLY_220 = "220 (Python FTP Server) Ready.\r\n"
REPLY_331 = "331 Username OK, need password.\r\n"
REPLY_350 = "350 Requested file action pending further information.\r\n"
REPLY_250 = "250 Requested file action okay, completed.\r\n"
REPLY_503 = "503 Bad sequence of commands.\r\n"
REPLY_230 = "230 User logged in, proceed.\r\n"
REPLY_221 = "221 Service closing control connection.\r\n"
REPLY_257 = '257 "%s" is current directory.\r\n'
REPLY_354 = "354 Opening data channel.\r\n"
REPLY_425 = "425 Unable to build data connection.\r\n"
REPLY_226 = "226 Transfer complete.\r\n"
REPLY_550 = "550 Requested action not taken; file unavailable.\r\n"
REPLY_202 = "202 Command not implemented, superfluous at this site.\r\n"
REPLY_500 = "500 Syntax error, command unrecognized.\r\n"

# Команды, в логах которых нужно скрывать аргумент (пароль).
SENSITIVE_COMMANDS = {"PASS"}

# --- Учетные данные --------------------------------------------------------
USERNAME = "user"
PASSWORD = "pass"

class FTPHandler(socketserver.StreamRequestHandler):
    def __init__(self, request: socket.socket, client_address, server):
        self.pending_rename_from: Optional[str] = None
        self.logged_in: bool = False
        self.current_dir: str = os.path.abspath(server.root_dir)
        self.port_addr: Optional[tuple[str, int]] = None  # IP и порт из команды PORT
        self.pasv_socket: Optional[socket.socket] = None  # слушающий сокет для PASV
        self.transfer_type: str = "A"  # ASCII по умолчанию, меняется командой TYPE
        self.restart_pos: int = 0  # позиция для REST
        logging.info(f"Client {client_address} connected via {server.server_address}")
        super().__init__(request, client_address, server)

    def setup(self):
        super().setup()
        self.send_reply(REPLY_220)

    def handle(self):
        """Читает команды из управляющего соединения и диспетчеризирует их в do_XXX."""
        while True:
            try:
                raw_line = self.rfile.readline(4096)
            except (ConnectionResetError, TimeoutError, OSError) as e:
                logging.warning(f"Client {self.client_address}: connection error while reading: {e}")
                break

            if not raw_line:
                logging.info(f"Client {self.client_address} closed the connection")
                break

            line = raw_line.decode(errors="replace").strip("\r\n")
            if not line:
                continue

            if " " in line:
                cmd, arg = line.split(" ", 1)
            else:
                cmd, arg = line, ""
            cmd = cmd.upper()

            log_arg = "****" if cmd in SENSITIVE_COMMANDS else arg
            logging.info(f"Client {self.client_address} -> {cmd} {log_arg}".strip())

            if cmd == "QUIT":
                self.send_reply(REPLY_221)
                break

            handler = getattr(self, f"do_{cmd}", None)
            try:
                if handler is None:
                    logging.warning(f"Client {self.client_address}: unknown command {cmd}")
                    self.send_reply(REPLY_500)
                else:
                    handler(arg)
            except Exception as e:
                logging.error(f"Client {self.client_address}: error handling {cmd}: {e}")
                self.send_reply("500 Internal server error.\r\n")

    def finish(self):
        if self.pasv_socket:
            try:
                self.pasv_socket.close()
            except OSError:
                pass
            self.pasv_socket = None
        logging.info(f"Client {self.client_address} disconnected")
        super().finish()

    def send_reply(self, msg: str):
        try:
            if not msg.endswith("\r\n"):
                msg += "\r\n"
            self.wfile.write(msg.encode())
            self.wfile.flush()
        except Exception as e:
            logging.error(f"Failed to send reply: {e}")

    # ---------------------------------------------------------------------
    # Основные команды FTP
    # ---------------------------------------------------------------------
    def do_USER(self, arg: str):
        if arg == USERNAME:
            self.send_reply(REPLY_331)
        else:
            logging.warning(f"Client {self.client_address}: unknown username {arg!r}")
            self.send_reply("530 Unknown user.\r\n")

    def do_PASS(self, arg: str):
        if not self.logged_in and arg == PASSWORD:
            self.logged_in = True
            logging.info(f"Client {self.client_address} logged in")
            self.send_reply(REPLY_230)
        else:
            logging.warning(f"Client {self.client_address}: login incorrect")
            self.send_reply("530 Login incorrect.\r\n")

    def do_PORT(self, arg: str):
        """
        ARG format h1,h2,h3,h4,p1,p2 where IP = h1.h2.h3.h4 and port = p1*256 + p2.
        Stores the resulting address for subsequent data transfers.
        """
        try:
            parts = arg.split(',')
            if len(parts) != 6:
                raise ValueError
            ip_parts = parts[:4]
            port_parts = parts[4:]
            ip_addr = '.'.join(ip_parts)
            port_num = int(port_parts[0]) * 256 + int(port_parts[1])
            self._close_pasv_socket()
            self.port_addr = (ip_addr, port_num)
            logging.info(f"Client {self.client_address} switched to active mode {self.port_addr}")
            self.send_reply("200 PORT command successful.")
        except Exception:
            logging.warning(f"Client {self.client_address}: bad PORT argument {arg!r}")
            self.send_reply("501 Bad parameter in PORT command.")

    def do_PWD(self, arg: str):
        rel = os.path.relpath(self.current_dir, self.server.root_dir)
        if rel == ".":
            rel = "/"
        else:
            rel = "/" + rel.replace(os.sep, '/')
        self.send_reply(REPLY_257 % rel)

    def _resolve_path(self, arg: str) -> Optional[str]:
        """Резолвит аргумент команды в абсолютный путь внутри root_dir; None, если путь вышел за пределы."""
        if arg.startswith('/'):
            target = os.path.join(self.server.root_dir, arg.lstrip('/'))
        else:
            target = os.path.join(self.current_dir, arg)
        abs_target = os.path.abspath(target)
        root = os.path.abspath(self.server.root_dir)
        if abs_target != root and not abs_target.startswith(root + os.sep):
            return None
        return abs_target

    def do_CWD(self, arg: str):
        if not self.logged_in:
            self.send_reply(REPLY_530)
            return
        abs_target = self._resolve_path(arg)
        if not abs_target:
            self.send_reply("550 Permission denied.\r\n")
            return
        if os.path.isdir(abs_target):
            self.current_dir = abs_target
            self.do_PWD('')
        else:
            self.send_reply("550 Not a directory.\r\n")

    def do_TYPE(self, arg: str):
        arg = arg.upper().strip()
        if arg in ("A", "I") or arg.startswith("L"):
            self.transfer_type = arg
            self.send_reply(f"200 Type set to {arg}.\r\n")
        else:
            self.send_reply("504 Command not implemented for that parameter.\r\n")

    def do_STRU(self, arg: str):
        if arg.upper().strip() == "F":
            self.send_reply("200 Structure set to F.\r\n")
        else:
            self.send_reply("504 Command not implemented for that parameter.\r\n")

def do_RNFR(self, arg: str):
    """
    Сначала запоминаем путь для переименования.
    Отправляем ответ 350 при успехе или 550 если путь не существует/выходит за root_dir.
    """
    if not self.logged_in:
        self.send_reply(REPLY_530)
        return
    abs_path = self._resolve_path(arg)
    if not abs_path or not os.path.exists(abs_path):
        self.send_reply(REPLY_550)
        return
    # Убедимся, что путь внутри root_dir
    self.pending_rename_from = abs_path
    self.send_reply(REPLY_350)

def do_RNTO(self, arg: str):
    """
    Переименовываем файл из pending_rename_from в новый путь.
    Отправляем 250 при успехе или 503 если RNFR не был сделан.
    """
    if not self.logged_in:
        self.send_reply(REPLY_530)
        return
    if not getattr(self, "pending_rename_from", None):
        self.send_reply(REPLY_503)
        return
    target_abs = self._resolve_path(arg)
    if not target_abs:
        self.send_reply(REPLY_550)
        return
    dest_dir = os.path.dirname(target_abs)
    if not os.path.isdir(dest_dir):
        try:
            os.makedirs(dest_dir, exist_ok=True)
        except Exception:
            self.send_reply(REPLY_550)
            return
    try:
        os.rename(self.pending_rename_from, target_abs)
        self.pending_rename_from = None
        self.send_reply(REPLY_250)
    except OSError:
        self.send_reply(REPLY_550)


    def do_REST(self, arg: str):
        try:
            pos = int(arg)
            if pos < 0:
                raise ValueError
        except ValueError:
            self.send_reply("501 Invalid REST parameter.\r\n")
            return
        self.restart_pos = pos
        self.send_reply("350 Restart position accepted.\r\n")

    def do_FEAT(self, arg: str):
        self.send_reply("211-Features:\r\n PASV\r\n EPSV\r\n SIZE\r\n MDTM\r\n REST STREAM\r\n211 End\r\n")

    def do_SYST(self, arg: str):
        self.send_reply("215 UNIX Type: L8\r\n")

    def do_NOOP(self, arg: str):
        self.send_reply("200 NOOP command successful.\r\n")

    def do_OPTS(self, arg: str):
        self.send_reply("200 OK.\r\n")

    def do_SIZE(self, arg: str):
        if not self.logged_in:
            self.send_reply(REPLY_530)
            return
        abs_path = self._resolve_path(arg)
        if not abs_path or not os.path.isfile(abs_path):
            self.send_reply(REPLY_550)
            return
        self.send_reply(f"213 {os.path.getsize(abs_path)}\r\n")

    def do_MDTM(self, arg: str):
        if not self.logged_in:
            self.send_reply(REPLY_530)
            return
        abs_path = self._resolve_path(arg)
        if not abs_path or not os.path.isfile(abs_path):
            self.send_reply(REPLY_550)
            return
        mtime = time.gmtime(os.path.getmtime(abs_path))
        self.send_reply(f"213 {time.strftime('%Y%m%d%H%M%S', mtime)}\r\n")

    def do_RETR(self, arg: str):
        if not self.logged_in:
            self.send_reply(REPLY_530)
            return
        restart_pos = self.restart_pos
        self.restart_pos = 0
        abs_path = self._resolve_path(arg)
        if not abs_path or not os.path.isfile(abs_path):
            self.send_reply(REPLY_550)
            return
        try:
            with open(abs_path, "rb") as f:
                if restart_pos:
                    f.seek(restart_pos)
                data = f.read()
            self.send_reply("150 Opening BINARY mode data connection.")
            try:
                with self._open_data_socket() as dsock:
                    dsock.sendall(data)
            except Exception as e:
                logging.error(f"Client {self.client_address}: RETR data transfer failed: {e}")
                self.send_reply(REPLY_425)
                return
            logging.info(f"Client {self.client_address}: RETR sent {len(data)} bytes for {arg!r}")
            self.send_reply(REPLY_226)
        except OSError:
            self.send_reply(REPLY_550)

    def _enter_passive_mode(self) -> tuple[str, int]:
        """Открывает слушающий сокет для PASV/EPSV и возвращает (ip, port)."""
        self._close_pasv_socket()
        self.port_addr = None  # PASV/EPSV отменяет ранее заданный активный режим
        pasv_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        pasv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        host = self.connection.getsockname()[0]
        pasv_sock.bind((host, 0))
        pasv_sock.listen(1)
        pasv_sock.settimeout(30)
        self.pasv_socket = pasv_sock
        return pasv_sock.getsockname()

    def do_PASV(self, arg: str):
        try:
            ip, port = self._enter_passive_mode()
            p1, p2 = divmod(port, 256)
            logging.info(f"Client {self.client_address} entered passive mode on {ip}:{port}")
            self.send_reply(f"227 Entering Passive Mode ({ip.replace('.', ',')},{p1},{p2}).\r\n")
        except OSError as exc:
            logging.error(f"Client {self.client_address}: failed to set up passive mode: {exc}")
            self._close_pasv_socket()
            self.send_reply(REPLY_425)

    def do_EPSV(self, arg: str):
        try:
            ip, port = self._enter_passive_mode()
            logging.info(f"Client {self.client_address} entered extended passive mode on {ip}:{port}")
            self.send_reply(f"229 Entering Extended Passive Mode (|||{port}|).\r\n")
        except OSError as exc:
            logging.error(f"Client {self.client_address}: failed to set up EPSV: {exc}")
            self._close_pasv_socket()
            self.send_reply(REPLY_425)

    def _close_pasv_socket(self):
        if self.pasv_socket:
            try:
                self.pasv_socket.close()
            except OSError:
                pass
            self.pasv_socket = None

    def _open_data_socket(self):
        """Открывает сокет данных: accept() в пассивном режиме либо connect() в активном."""
        if self.pasv_socket:
            try:
                self.pasv_socket.settimeout(30)
                conn, addr = self.pasv_socket.accept()
                logging.info(f"Client {self.client_address}: accepted passive data connection from {addr}")
                return conn
            except Exception as exc:
                logging.error(f"Client {self.client_address}: failed to accept passive data connection: {exc}")
                raise
            finally:
                self._close_pasv_socket()

        if not self.port_addr:
            raise RuntimeError("No PORT/PASV address set for data transfer")
        try:
            return socket.create_connection(self.port_addr, timeout=10)
        except Exception as exc:
            logging.error(f"Client {self.client_address}: failed to open active data connection: {exc}")
            raise


    def _format_list_entry(self, name: str) -> str:
        """Строка в формате Unix `ls -l`, который ожидают распарсить FTP-клиенты."""
        path = os.path.join(self.current_dir, name)
        try:
            st = os.stat(path)
            size = st.st_size
            mtime = time.localtime(st.st_mtime)
        except OSError:
            size = 0
            mtime = time.localtime()
        perms = "drwxr-xr-x" if os.path.isdir(path) else "-rw-r--r--"
        date_str = time.strftime("%b %d %H:%M", mtime)
        return f"{perms} 1 owner group {size:>10} {date_str} {name}"

    def do_LIST(self, arg: str):
        self.send_reply("150 Opening ASCII mode data connection.")
        try:
            entries = os.listdir(self.current_dir)
            with self._open_data_socket() as dsock:
                for name in entries:
                    line = self._format_list_entry(name) + "\r\n"
                    dsock.sendall(line.encode())
            logging.info(f"Client {self.client_address}: LIST sent {len(entries)} entries")
            self.send_reply(REPLY_226)
        except Exception as e:
            logging.error(f"Client {self.client_address}: LIST error: {e}")
            self.send_reply(REPLY_550)

    def do_STOR(self, arg: str):
        self.send_reply(REPLY_202)

class ThreadedFTPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address, RequestHandlerClass, root_dir):
        super().__init__(server_address, RequestHandlerClass)
        self.root_dir = os.path.abspath(root_dir)


def main():
    parser = argparse.ArgumentParser(description="Мини‑FTP сервер на Python")
    parser.add_argument("--root", required=True, help="Абсолютный путь к корню файлов для FTP")
    parser.add_argument("--host", default="0.0.0.0", help="IP адрес сервера (по умолчанию 0.0.0.0)")
    parser.add_argument("--port", type=int, default=2121, help="Порт FTP")
    args = parser.parse_args()

    if not os.path.isdir(args.root):
        raise NotADirectoryError(f"Указанный путь не существует: {args.root}")

    with ThreadedFTPServer((args.host, args.port), FTPHandler, args.root) as server:
        print(f"Python FTP сервер запущен на {args.host}:{args.port}, корень = {server.root_dir}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nЗавершение работы.")

if __name__ == "__main__":
    main()
