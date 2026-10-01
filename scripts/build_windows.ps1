[CmdletBinding()]
param(
    [switch]$Console
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$EntryPoint = Join-Path $ProjectRoot "desktop.py"
$IconFile = Join-Path $ProjectRoot "youtube_ai_chatbot.ico"
$env:UV_CACHE_DIR = Join-Path $ProjectRoot ".uv-cache"
$WindowMode = if ($Console) { "--console" } else { "--windowed" }
$ReleaseDirectory = Join-Path $ProjectRoot "dist\YT Livestream Chatbot"
$StateStagingDirectory = Join-Path ([System.IO.Path]::GetTempPath()) (
    "yt-livestream-chatbot-state-" + [guid]::NewGuid().ToString("N")
)
$PreservedStateDirectories = @()

function Restore-UserState {
    if (-not (Test-Path -LiteralPath $StateStagingDirectory)) {
        return
    }

    New-Item -ItemType Directory -Force -Path $ReleaseDirectory | Out-Null
    foreach ($Name in $PreservedStateDirectories) {
        $Source = Join-Path $StateStagingDirectory $Name
        $Destination = Join-Path $ReleaseDirectory $Name
        if (Test-Path -LiteralPath $Source) {
            if (Test-Path -LiteralPath $Destination) {
                Remove-Item -LiteralPath $Destination -Recurse -Force
            }
            Move-Item -LiteralPath $Source -Destination $Destination
        }
    }
    Remove-Item -LiteralPath $StateStagingDirectory -Recurse -Force
}

Push-Location $ProjectRoot
try {
    if (-not (Test-Path -LiteralPath $IconFile)) {
        throw "Application icon is missing: $IconFile"
    }

    foreach ($Name in @("data", "models", "logs")) {
        $Source = Join-Path $ReleaseDirectory $Name
        if (Test-Path -LiteralPath $Source) {
            New-Item -ItemType Directory -Force -Path $StateStagingDirectory | Out-Null
            Move-Item -LiteralPath $Source -Destination $StateStagingDirectory
            $PreservedStateDirectories += $Name
        }
    }

    uv run --group build pyinstaller `
        --noconfirm `
        --clean `
        --onedir `
        $WindowMode `
        --name "YT Livestream Chatbot" `
        --icon $IconFile `
        --specpath build `
        --collect-all gradio `
        --collect-all groovy `
        --collect-all safehttpx `
        --collect-all huggingface_hub `
        --collect-all keyring `
        --collect-all llama_cpp `
        --collect-all pytchat `
        --collect-all webview `
        --collect-all clr_loader `
        --hidden-import uvicorn.logging `
        $EntryPoint

    $Executable = Join-Path $ProjectRoot "dist\YT Livestream Chatbot\YT Livestream Chatbot.exe"
    if (-not (Test-Path -LiteralPath $Executable)) {
        throw "PyInstaller did not create the expected executable: $Executable"
    }
    Write-Host "Desktop bundle created at: $(Split-Path -Parent $Executable)"
}
finally {
    Restore-UserState
    Pop-Location
}
