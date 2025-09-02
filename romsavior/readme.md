# Myrient ROM Manager

A portable GUI to browse and manage ROMs from [Myrient](https://myrient.erista.me/files/).

Features:
- Tree-based browser for Myrient directories
- File table with sizes and dates
- Download queue with progress bars, speed, ETA
- Auto-extraction of `.zip` archives
- Conversion of `.bin/.cue` or `.iso` → `.chd` (using `chdman`)
- Automatic cleanup of temp files
- Profiles that save user options (downloader, output dirs, etc.)
- Profiles also remember the **folder you saved them in**

---

## Requirements

The app depends on a few external tools:

- [aria2c](https://aria2.github.io/) (preferred downloader)
- [wget](https://eternallybored.org/misc/wget/) (fallback downloader)
- [7-Zip](https://www.7-zip.org/) (`7z.exe`) or `unzip` (for extracting `.zip`)
- [MAME tools](https://www.mamedev.org/release.html) (`chdman.exe` for CHD conversion)

> On Linux/WSL: install via your package manager  
> On Windows: download the `.exe`s above and put them on your `PATH`, or drop them into the same folder as `MyrientROMManager.exe`.

---

## Windows 11 (native)

1. Make sure [Python 3.11+](https://www.python.org/downloads/windows/) is installed and on PATH.
2. Clone or copy this project into a folder (e.g., `C:\ROMManager`).
3. Double-click `setup_windows.bat`:
   - Creates a venv
   - Installs dependencies
   - Creates `run_rom_manager.bat`
   - Places a **Desktop shortcut** (“Myrient ROM Manager”)
   - Warns if required external tools are missing
4. Use the shortcut (or `run_rom_manager.bat`) to launch the app.

### Build a standalone `.exe` (optional)
Inside your venv:
powershell
pyinstaller --noconsole --name "MyrientROMManager" main.py
The binary will appear in dist\MyrientROMManager\.

Windows 11 (via WSL2 + WSLg)
If you prefer running the Linux version inside WSL2:

bash
Copy code
wsl --install -d Ubuntu   # run once to install
sudo apt update
sudo apt install -y python3-venv python3-pip aria2 wget unzip p7zip-full mame-tools
Clone/copy the project into WSL:

bash
Copy code
cd ~/rom-manager
python3 -m venv venv
source venv/bin/activate
pip install PySide6 requests beautifulsoup4
python main.py
The GUI will show up on your Windows desktop (via WSLg).

Linux (native)
On Ubuntu/Debian:

bash
Copy code
sudo apt update
sudo apt install -y python3-venv python3-pip aria2 wget unzip p7zip-full mame-tools
Then:

bash
Copy code
cd ~/rom-manager
python3 -m venv venv
source venv/bin/activate
pip install PySide6 requests beautifulsoup4
python main.py
Usage
Browse the Myrient file tree (left pane). Double-click folders in the center table to enter.

Select files (one or more) in the center table.

Click Add to Queue to send them to the download queue.

Click Start in the Queue tab. The queue auto-advances:

Download → Extraction → Conversion → Cleanup

Profiles tab lets you:

Pick temp/output dirs

Choose downloader

Toggle extraction/conversion/cleanup options

Set simultaneous downloads & speed cap

Save multiple named profiles

Each profile remembers the folder you were browsing when you saved it

Notes
Profiles do not auto-update while you browse.
You must Save the profile to record the current folder.
When you reload that profile later, the app opens directly in that folder.

All threads shut down cleanly on exit; no more QThread destroyed errors.

Dark theme enabled by default.

License
MIT
