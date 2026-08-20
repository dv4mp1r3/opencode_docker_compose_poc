#!/usr/bin/env python3
"""Функциональный верификатор для D' (RNFR/RNTO). Не часть агента — запускается извне для оценки."""
import ftplib
import os
import subprocess
import sys
import tempfile
import time

HOST = "127.0.0.1"
PORT = 2131
SERVER_PATH = os.path.join(os.path.dirname(__file__), "..", "ftp_server_rename", "ftp_server.py")


def start_server(root):
    proc = subprocess.Popen(
        ["python3", SERVER_PATH, "--root", root, "--host", HOST, "--port", str(PORT)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    for _ in range(50):
        try:
            ftplib.FTP().connect(HOST, PORT, timeout=1)
            return proc
        except OSError:
            time.sleep(0.2)
    proc.kill()
    out = proc.stdout.read() if proc.stdout else ""
    print("SERVER FAILED TO START\n" + out)
    sys.exit(1)


def main():
    def cmd(ftp, line):
        """sendcmd, но не кидает исключение на 4xx/5xx — возвращает код ответа строкой."""
        try:
            return ftp.sendcmd(line)
        except ftplib.error_perm as e:
            return str(e)
        except ftplib.error_temp as e:
            return str(e)

    failures = []
    with tempfile.TemporaryDirectory() as root:
        with open(os.path.join(root, "old.txt"), "w") as f:
            f.write("hello")

        proc = start_server(root)
        try:
            # --- Test 1: RNFR + RNTO успешно переименовывает файл ---
            ftp = ftplib.FTP()
            ftp.connect(HOST, PORT, timeout=5)
            ftp.login("user", "pass")
            r1 = cmd(ftp, "RNFR old.txt")
            if not r1.startswith("3"):
                failures.append(f"RNFR old.txt ожидался код 3xx, получен: {r1!r}")
            r2 = cmd(ftp, "RNTO new.txt")
            if not r2.startswith("2"):
                failures.append(f"RNTO new.txt ожидался код 2xx, получен: {r2!r}")
            if os.path.exists(os.path.join(root, "old.txt")):
                failures.append("old.txt всё ещё существует после переименования")
            if not os.path.exists(os.path.join(root, "new.txt")):
                failures.append("new.txt не создан после переименования")
            ftp.quit()

            # --- Test 2: RNTO без предварительного RNFR -> ошибка (5xx) ---
            ftp2 = ftplib.FTP()
            ftp2.connect(HOST, PORT, timeout=5)
            ftp2.login("user", "pass")
            r3 = cmd(ftp2, "RNTO orphan.txt")
            if not r3.startswith("5"):
                failures.append(f"RNTO без RNFR ожидался код 5xx, получен: {r3!r}")
            ftp2.quit()

            # --- Test 3: RNFR на несуществующий путь -> ошибка (5xx) ---
            ftp3 = ftplib.FTP()
            ftp3.connect(HOST, PORT, timeout=5)
            ftp3.login("user", "pass")
            r4 = cmd(ftp3, "RNFR does_not_exist.txt")
            if not r4.startswith("5"):
                failures.append(f"RNFR на несуществующий файл ожидался код 5xx, получен: {r4!r}")
            ftp3.quit()
        except Exception as e:
            failures.append(f"Exception during test: {e!r}")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    if failures:
        print("FAIL")
        for f in failures:
            print(" -", f)
        sys.exit(1)
    else:
        print("PASS")
        sys.exit(0)


if __name__ == "__main__":
    main()
