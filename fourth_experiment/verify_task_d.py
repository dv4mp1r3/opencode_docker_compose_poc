#!/usr/bin/env python3
"""Functional verifier for golden-set task D: after CWD into a subdirectory,
LIST must show that subdirectory's contents, not the FTP root's."""
import ftplib
import sys

HOST = "127.0.0.1"
PORT = 2121
USER = "user"
PASS = "pass"


def main():
    ftp = ftplib.FTP()
    ftp.connect(HOST, PORT, timeout=5)
    ftp.login(USER, PASS)
    ftp.cwd("subdir")
    lines = []
    ftp.retrlines("LIST", lines.append)
    entries = [line.split()[-1] for line in lines]
    ftp.quit()

    print("LIST after CWD subdir:", entries)
    if "sub_only.txt" in entries and "root_only.txt" not in entries:
        print("PASS")
        sys.exit(0)
    else:
        print("FAIL")
        sys.exit(1)


if __name__ == "__main__":
    main()
