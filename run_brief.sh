#!/bin/bash
# 全球市場早報：給 Linux cron 呼叫用
cd "$(dirname "$0")"
./venv/bin/python daily_market_brief.py
