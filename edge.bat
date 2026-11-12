@echo off
start "" msedge.exe --remote-debugging-port=9222 --user-data-dir="%~dp0EdgeProfile"
echo Edge started with debugging port 9222.
echo Login to the assessment site in this Edge window, open the question page, then start DeepSeekZuxiaAuto.exe.
pause
