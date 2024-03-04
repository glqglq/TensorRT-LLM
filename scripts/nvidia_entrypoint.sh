#!/bin/bash

echo "当前脚本的文件名是: $0"
echo "当前脚本的完整路径是: $BASH_SOURCE"
echo "调用当前脚本的脚本的信息:"

# 如果是通过 source 或者 . 命令调用的话，$0 会是调用脚本的文件名，$BASH_SOURCE 会是调用脚本的完整路径
echo "调用脚本的文件名: ${BASH_SOURCE[1]}"
echo "调用脚本的完整路径: $(dirname "${BASH_SOURCE[1]}")"

