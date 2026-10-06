@echo off
chcp 65001 >nul
title YouTube Downloader
cd /d "%~dp0"
python youtube_downloader.py %*
echo.
pause
