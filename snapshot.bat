@echo off
REM Unattended line snapshot for Task Scheduler. Run every 2-4h Fri/Sat so the
REM DB holds an opener-ish and a closing-ish line for every game (CLV tracking).
cd /d %~dp0
python cfb_edge.py --snapshot --no-color >> snapshot.log 2>&1
