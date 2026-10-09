#!/bin/bash
# 双击这个文件就能打开工具箱（会弹出一个终端窗口，用的时候别关它）。
cd "$(dirname "$0")" || exit 1
clear
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1; then
  echo
  echo "  这台 Mac 还没有 Python 3。"
  echo
  echo "  如果弹出了「安装命令行开发者工具」的窗口：点「安装」，装好以后再双击一次这个文件。"
  echo "  如果没有弹窗：去 https://www.python.org/downloads/ 下载安装，装好以后再双击一次。"
  echo
  read -n 1 -s -r -p "  按任意键关闭这个窗口"
  exit 1
fi
python3 app.py
