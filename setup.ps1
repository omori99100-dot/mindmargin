# MindMargin Setup Script (Windows PowerShell)
param(
    [switch]$InstallComfyUI,
    [switch]$InstallPiper,
    [switch]$InstallWhisper
)

Write-Host "=== MindMargin Setup ===" -ForegroundColor Cyan

# 1. Create virtual environment
if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..." -ForegroundColor Yellow
    python -m venv .venv
}

# 2. Activate and install dependencies
$pip = Join-Path (Get-Item ".venv").FullName "Scripts\pip.exe"
Write-Host "Installing Python dependencies..." -ForegroundColor Yellow
& $pip install --upgrade pip
& $pip install -r requirements.txt

# 3. Create output directories
$dirs = @("output\temp", "output\videos", "output\thumbnails", "output\audio", "output\captions", "output\checkpoints")
foreach ($d in $dirs) {
    New-Item -ItemType Directory -Path $d -Force | Out-Null
}

# 4. Copy .env.example if .env doesn't exist
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example — edit it with your keys" -ForegroundColor Green
}

# 5. Copy config defaults if they don't exist
$configDir = "config"
if (-not (Test-Path "$configDir\settings.yaml")) {
    Write-Host "Config files already exist in config/" -ForegroundColor Green
}

# 6. Optional: Install ComfyUI
if ($InstallComfyUI) {
    Write-Host "Cloning ComfyUI..." -ForegroundColor Yellow
    git clone https://github.com/comfyanonymous/ComfyUI.git comfyui
    Push-Location comfyui
    & $pip install -r requirements.txt
    Pop-Location
    Write-Host "ComfyUI installed. Download SDXL models separately." -ForegroundColor Green
}

# 7. Optional: Install Piper TTS
if ($InstallPiper) {
    Write-Host "Download Piper TTS binaries..." -ForegroundColor Yellow
    $piperUrl = "https://github.com/rhasspy/piper/releases/latest/download/piper_windows_amd64.zip"
    $piperZip = "piper_windows_amd64.zip"
    Invoke-WebRequest -Uri $piperUrl -OutFile $piperZip
    Expand-Archive -Path $piperZip -DestinationPath "piper" -Force
    Remove-Item $piperZip
    Write-Host "Piper installed. Download voice models from https://huggingface.co/rhasspy/piper-voices" -ForegroundColor Green
}

# 8. Optional: Install Whisper
if ($InstallWhisper) {
    Write-Host "Installing Whisper..." -ForegroundColor Yellow
    & $pip install openai-whisper
    Write-Host "Whisper installed. Model will download on first use." -ForegroundColor Green
}

Write-Host "`n=== Setup complete ===" -ForegroundColor Cyan
Write-Host "Activate: .venv\Scripts\Activate" -ForegroundColor Green
Write-Host "Run: python -m mindmargin.main --topic 'Enron'" -ForegroundColor Green
Write-Host "API: python -m mindmargin.main --api" -ForegroundColor Green
