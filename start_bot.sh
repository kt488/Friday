#!/bin/bash
export PYTHONPATH=$PYTHONPATH:.
while true; do
    echo "Starting Friday Telegram Bot..."
    ./venv/bin/python interface/telegram_bot.py
    echo "Bot crashed with exit code $?. Restarting in 5 seconds..."
    sleep 5
done
