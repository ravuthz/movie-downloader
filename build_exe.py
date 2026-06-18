import os
import sys
import subprocess
import shutil

# This script is intended to be run on Windows to create a standalone executable.
# Prerequisites: 
# 1. Python installed
# 2. pip install pyinstaller playwright gradio
# 3. playwright install chromium

def build():
    print("🚀 Starting build process...")
    
    # 1. Check if pyinstaller is installed
    try:
        import PyInstaller
    except ImportError:
        print("❌ PyInstaller not found. Install it with: pip install pyinstaller")
        return

    # 2. Define names
    app_name = "Mov1Downloader"
    entry_point = "app.py"
    
    # 3. Handle Package Assets
    import gradio
    import safehttpx
    gradio_path = os.path.dirname(gradio.__file__)
    safehttpx_path = os.path.dirname(safehttpx.__file__)
    
    # 5. PyInstaller Command
    # --onefile: Create a single executable
    # --add-data: Bundle static files
    # --collect-all: Robustly collect everything for problematic packages
    cmd = [
        "pyinstaller",
        "--noconfirm",
        "--onefile",
        "--windowed", 
        "--name", app_name,
        f"--add-data={gradio_path};gradio",
        f"--add-data={safehttpx_path};safehttpx",
        "--collect-all=gradio",
        "--collect-all=safehttpx",
        "--hidden-import=uvicorn",
        "--hidden-import=playwright",
        "--hidden-import=safehttpx",
        entry_point
    ]
    
    print(f"📦 Running PyInstaller command: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)
    
    print(f"✅ Build complete! Find your EXE in the 'dist' folder.")

if __name__ == "__main__":
    build()
