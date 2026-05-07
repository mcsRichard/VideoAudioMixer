@echo off
echo ============================================================
echo  VideoAudioMixer - Build EXE
echo ============================================================
echo.

echo [1/2] Installing / checking PyInstaller...
pip install pyinstaller --quiet
if %errorlevel% neq 0 (
    echo ERROR: pip install pyinstaller failed
    pause & exit /b 1
)

echo [2/2] Building VideoAudioMixer.exe...
pyinstaller --onefile --console --name VideoAudioMixer ^
    --hidden-import srt_to_txt ^
    --hidden-import srt_voice_gen ^
    --hidden-import speed_mp3 ^
    --hidden-import mixer ^
    pipeline_app.py

if %errorlevel% neq 0 (
    echo.
    echo ERROR: Build failed.
    pause & exit /b 1
)

echo.
echo ============================================================
echo  Build complete!
echo  EXE location: dist\VideoAudioMixer.exe
echo.
echo  Distribute the following files together:
echo    dist\VideoAudioMixer.exe
echo    ffmpeg.exe
echo    ffprobe.exe
echo    ElevenLabs.md        (fill in API key + Voice ID)
echo    resembleAI.md        (optional)
echo ============================================================
pause
