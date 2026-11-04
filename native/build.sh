#!/bin/bash
# 在 Linux 上交叉编译 rtt-capture.exe 并复制到 bin/。
# 需要：rustup target add x86_64-pc-windows-gnu；apt install mingw-w64
set -e
cd "$(dirname "$0")/rtt-capture"
cargo build --release --target x86_64-pc-windows-gnu
cp target/x86_64-pc-windows-gnu/release/rtt-capture.exe ../../bin/
