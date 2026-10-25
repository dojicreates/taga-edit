# One-time setup for Windows (PowerShell). Run from the project root:  .\setup.ps1
# Creates a Python virtual environment, installs the Python and Node dependencies,
# and (optionally) downloads a portable FFmpeg into tools\ffmpeg.
$ErrorActionPreference = "Stop"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "Python 3.10+ is required (https://www.python.org)." }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw "Node.js 18+ is required (https://nodejs.org)." }

python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm install
New-Item -ItemType Directory -Force work | Out-Null

$haveFfmpeg = (Test-Path tools\ffmpeg\ffmpeg.exe) -or (Get-Command ffmpeg -ErrorAction SilentlyContinue)
if (-not $haveFfmpeg) {
    $answer = Read-Host "FFmpeg not found. Download a portable FFmpeg (about 110 MB, gyan.dev) into tools\ffmpeg? [y/N]"
    if ($answer -match '^(y|yes)$') {
        $zip = Join-Path $env:TEMP "ffmpeg-release-essentials.zip"
        Invoke-WebRequest "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" -OutFile $zip -UseBasicParsing
        $tmp = Join-Path $env:TEMP "ffmpeg-extract"
        Expand-Archive $zip -DestinationPath $tmp -Force
        New-Item -ItemType Directory -Force tools\ffmpeg | Out-Null
        Copy-Item (Join-Path (Get-ChildItem $tmp -Directory | Select-Object -First 1).FullName "bin\*") tools\ffmpeg\ -Force
        Remove-Item $zip, $tmp -Recurse -Force
    } else {
        Write-Host "Install FFmpeg 7+ yourself and make sure ffmpeg and ffprobe are on PATH."
    }
}
Write-Host "Done. Open this folder in Claude Code and call the taga-edit skill."
