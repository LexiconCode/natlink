<#
.SYNOPSIS
    Build natlink 64-bit marshal DLLs.

.DESCRIPTION
    Stops Dragon and the natlink launcher, builds the 64-bit marshal
    DLLs (marshal64_{v13_v14,v15_v16}.dll) via CMake, and copies them to
    the source directory.

    Requires: CMake 3.20+, Visual Studio 2019/2022/2026 with C++ Desktop workload.

.EXAMPLE
    .\build_dll.ps1                # Release (default)
    .\build_dll.ps1 -Config Debug  # Debug
#>

param(
    [ValidateSet("Release", "Debug")]
    [string]$Config = "Release"
)

$ErrorActionPreference = "Stop"
$PkgDir = Join-Path $PSScriptRoot "src\natlink_com"

# --- Stop natlink launcher via shutdown event (clean) ---

function Stop-NatlinkLauncher {
    try {
        $event = [System.Threading.EventWaitHandle]::OpenExisting("NatlinkShutdown")
        Write-Host "Signaling natlink launcher to shut down..."
        $event.Set()
        $event.Close()
        Start-Sleep -Seconds 3
    }
    catch [System.Threading.WaitHandleCannotBeOpenedException] {
        # Event doesn't exist — no launcher running
    }

    # Fallback: force-kill if still running
    $procs = Get-CimInstance Win32_Process -Filter "Name like 'python%' and CommandLine like '%natlink_com%_launcher%'" -ErrorAction SilentlyContinue
    foreach ($proc in $procs) {
        Write-Host "Force-stopping natlink launcher (PID $($proc.ProcessId))..."
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
    }
}

# --- Stop Dragon ---

function Stop-Dragon {
    $dragon = Get-Process natspeak -ErrorAction SilentlyContinue
    if ($dragon) {
        Write-Host "Stopping Dragon NaturallySpeaking..."
        Stop-Process -Name natspeak -Force
        Start-Sleep -Seconds 2
    }
}

# --- Verify build outputs are not locked ---

$AllOutputs = @(
    "marshal64_v13_v14.dll", "marshal64_v15_v16.dll",
    "dragon_interfaces.tlb"
)

function Test-OutputsUnlocked {
    foreach ($file in $AllOutputs) {
        $path = Join-Path $PkgDir $file
        if (Test-Path $path) {
            try {
                [IO.File]::Open($path, 'Open', 'ReadWrite', 'None').Close()
            }
            catch {
                throw "$file is locked by another process. Close it and try again."
            }
        }
    }
}

# --- Detect VS generator ---

function Get-VSPreset {
    # Try each VS version; return configure + build preset names
    $vsVersions = @(
        @{ Configure = "vs2026"; Release = "Release-vs2026"; Debug = "Debug-vs2026" },
        @{ Configure = "vs2022"; Release = "Release";         Debug = "Debug" },
        @{ Configure = "vs2019"; Release = "Release-vs2019"; Debug = "Debug-vs2019" }
    )
    foreach ($vs in $vsVersions) {
        $out = cmake --preset $vs.Configure 2>&1
        if ($LASTEXITCODE -eq 0) { return $vs }
    }
    throw "No supported Visual Studio installation found"
}

# --- Main ---

try {
    Stop-NatlinkLauncher
    Stop-Dragon
    Test-OutputsUnlocked

    Write-Host "`n=== Building 64-bit marshal DLLs ($Config) ===`n"

    $preset = Get-VSPreset
    $buildPreset = $preset[$Config]

    cmake --build --preset $buildPreset
    if ($LASTEXITCODE -ne 0) { throw "CMake build failed" }

    # Show results
    Write-Host "`n=== Done ==="
    foreach ($file in $AllOutputs) {
        $path = Join-Path $PkgDir $file
        if (Test-Path $path) {
            $size = [math]::Round((Get-Item $path).Length / 1024)
            Write-Host "  $file  (${size}KB)"
        }
    }
}
catch {
    Write-Host "`nERROR: $_" -ForegroundColor Red
}
finally {
    Read-Host "`nPress Enter to exit"
}
