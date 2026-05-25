@echo off
title ICT Silver Bullet Bot - Institutional Guardian
echo Starting ICT Trading Bot...
:loop
python main.py
echo Bot crashed or stopped. Restarting in 10 seconds...
timeout /t 10
goto loop
