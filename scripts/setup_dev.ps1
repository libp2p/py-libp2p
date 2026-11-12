#Requires -Version 5.1
<#
.SYNOPSIS
  Set up a py-libp2p development environment on Windows (native PowerShell).

.DESCRIPTION
  Checks cmake and uv (>= 0.13.4, required unless -Pip), selects a supported
  Python from pyproject.toml (classifiers intersect requires-python), installs a
  missing interpreter via ``uv python install`` when needed (including with
  -Python), then installs the dev dependency group. With -Pip, floors pip at
  >= 26.2.2 (eMudhra/emSign CA). GMP is not required on Windows (fastecdsa is
  skipped on win32). Dot-source the script to also activate .venv.

.PARAMETER Help
  Show help and exit.

.PARAMETER Python
  Force a Python version (e.g. 3.12). Must be in the supported set. If missing,
  installs it with ``uv python install`` (unless -Pip).

.PARAMETER Pip
  Force the pip install path even if uv is available (skips the uv requirement).

.PARAMETER SkipPreCommit
  Do not run pre-commit install.

.EXAMPLE
  pwsh -File scripts\setup_dev.ps1

.EXAMPLE
  .\scripts\setup_dev.ps1 -Python 3.12

.EXAMPLE
  # Dot-source to also activate .venv in the current session:
  . .\scripts\setup_dev.ps1
#>
[CmdletBinding()]
param(
    [Alias("h", "?")]
    [switch]$Help,

    [string]$Python = "",

    [switch]$Pip,

    [switch]$SkipPreCommit
)

$ErrorActionPreference = "Stop"

$MinUvVersion = [version]"0.13.4"
$MinPipVersion = [version]"26.2.2"

function Show-Help {
    @"
Usage:
  .\scripts\setup_dev.ps1 [-Help] [-Python VERSION] [-Pip] [-SkipPreCommit]
  . .\scripts\setup_dev.ps1 [...]   # also activates .venv in this session

Set up a py-libp2p development environment on Windows.

Options:
  -Help / -h / -?     Show this help and exit
  -Python VERSION     Force Python version (e.g. 3.12); must be supported.
                      If missing and uv is available, installs via
                      ``uv python install``.
  -Pip                Force pip even if uv is available (skips uv requirement)
  -SkipPreCommit      Do not run pre-commit install

Activation:
  Running the script as a program cannot change your current session. Dot-source
  it to create the env and activate it in one step:
    . .\scripts\setup_dev.ps1
  Otherwise activate afterwards with: .\.venv\Scripts\Activate.ps1

Python selection (default):
  Parse requires-python and Programming Language :: Python :: 3.X classifiers
  from pyproject.toml. Use the intersection (today 3.10-3.13). Pick the newest
  installed interpreter in that set. If a needed version is missing and uv is
  available (including with -Python), install it via ``uv python install``.

Prerequisites (checked before install):
  - CMake on PATH (winget install --id Kitware.CMake -e)
  - uv >= 0.13.4 unless -Pip (auto-tries winget install astral-sh.uv;
    no system Python required - uv downloads CPython)
  - Git recommended (winget install --id Git.Git -e)
  - With -Pip: a supported system Python on PATH and pip >= 26.2.2
    (eMudhra/emSign CA incident; Discussion #1570)
  - GMP is not required on Windows (fastecdsa is skipped on win32)

If script execution is blocked (common on Windows 11 Restricted policy):
  One-shot (no policy change):
    .\scripts\setup_dev.cmd
    # or: pwsh -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup_dev.ps1
  Permanent for your user (then .\scripts\setup_dev.ps1 and dot-source work):
    Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

Linux/macOS: use scripts/setup_dev.sh instead.
"@
}

function Get-VersionOrZero([string]$text) {
    if ([string]::IsNullOrWhiteSpace($text)) { return [version]"0.0.0" }
    $m = [regex]::Match($text, "(\d+\.\d+\.\d+|\d+\.\d+)")
    if (-not $m.Success) { return [version]"0.0.0" }
    $parts = $m.Groups[1].Value.Split(".")
    while ($parts.Count -lt 3) { $parts += "0" }
    return [version]::Parse(($parts[0..2] -join "."))
}

function Get-SupportedPythonMinors {
    $pyproject = Join-Path $PSScriptRoot "..\pyproject.toml" | Resolve-Path
    # Force UTF-8: Windows PowerShell defaults can misread pyproject.toml.
    $text = Get-Content -Raw -Path $pyproject -Encoding UTF8
    $minors = [System.Collections.Generic.List[string]]::new()

    foreach ($m in [regex]::Matches($text, 'Programming Language :: Python :: (3\.\d+)')) {
        $minors.Add($m.Groups[1].Value) | Out-Null
    }

    $req = [regex]::Match($text, 'requires-python\s*=\s*"([^"]+)"')
    $minMinor = 10
    # Exclusive upper bound on the 3.X minor (default: allow through 3.13).
    $maxExclusiveMinor = 14
    if ($req.Success) {
        $spec = $req.Groups[1].Value.Replace(" ", "")
        foreach ($part in $spec.Split(",")) {
            if ($part.StartsWith(">=")) {
                $bits = $part.Substring(2).Split(".")
                if ($bits.Length -ge 2 -and [int]$bits[0] -eq 3) {
                    $minMinor = [int]$bits[1]
                }
            }
            elseif ($part.StartsWith("<=") ) {
                $bits = $part.Substring(2).Split(".")
                if ($bits.Length -ge 2 -and [int]$bits[0] -eq 3) {
                    $maxExclusiveMinor = [int]$bits[1] + 1
                }
            }
            elseif ($part.StartsWith("<")) {
                # e.g. <4.0 means all 3.x are allowed - do NOT use bits[1] (0).
                $bits = $part.Substring(1).Split(".")
                $maj = [int]$bits[0]
                if ($maj -gt 3) {
                    $maxExclusiveMinor = 99
                }
                elseif ($maj -eq 3 -and $bits.Length -ge 2) {
                    $maxExclusiveMinor = [int]$bits[1]
                }
                elseif ($maj -eq 3) {
                    $maxExclusiveMinor = 0
                }
            }
        }
    }

    if ($minors.Count -eq 0) {
        for ($i = $minMinor; $i -lt $maxExclusiveMinor; $i++) {
            $minors.Add("3.$i") | Out-Null
        }
    }

    $filtered = @(
        $minors | Sort-Object -Unique | Where-Object {
            $mm = [int]($_ -split "\.")[1]
            ($mm -ge $minMinor) -and ($mm -lt $maxExclusiveMinor)
        }
    )
    if ($filtered.Count -eq 0) {
        # Last-resort defaults matching current classifiers.
        $filtered = @("3.10", "3.11", "3.12", "3.13")
    }
    return $filtered
}

function Update-SessionPath {
    # Pick up tools installed earlier in this session (winget / uv installer).
    $machine = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $extra = @(
        (Join-Path $env:USERPROFILE ".local\bin"),
        (Join-Path $env:USERPROFILE ".cargo\bin"),
        (Join-Path $env:LOCALAPPDATA "Programs\uv")
    ) | Where-Object { $_ -and (Test-Path $_) }
    $env:Path = (@($machine, $user) + $extra) -join ";"
}

function Test-RealPythonPath([string]$path) {
    if (-not $path) { return $false }
    # Windows Store "python" / "python3" stubs open the Store and are not usable.
    if ($path -match '\\WindowsApps\\') { return $false }
    return (Test-Path $path)
}

function Find-PythonBin([string]$majorMinor) {
    $cmd = Get-Command "python$majorMinor" -ErrorAction SilentlyContinue
    if ($cmd -and (Test-RealPythonPath $cmd.Source)) { return $cmd.Source }

    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        try {
            $out = & py "-$majorMinor" -c "import sys; print(sys.executable)" 2>&1 |
                Where-Object { $_ -is [string] -or $_.GetType().Name -eq "String" } |
                Out-String
            $path = ($out -split "`r?`n" | Where-Object { $_ -and ($_ -notmatch "^(py:|Python )") } | Select-Object -First 1)
            if ($path -and (Test-RealPythonPath $path.Trim())) { return $path.Trim() }
        } catch { }
    }

    Update-SessionPath
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        try {
            $prevEap = $ErrorActionPreference
            $ErrorActionPreference = "Continue"
            $found = & uv python find $majorMinor 2>&1 | Out-String
            $ErrorActionPreference = $prevEap
            $path = ($found -split "`r?`n" | Where-Object { $_ -match "python(\.exe)?$" -or $_ -match "cpython" -or $_ -match "\\python\.exe$" } | Select-Object -First 1)
            if (-not $path) {
                $path = ($found -split "`r?`n" | Where-Object { $_.Trim() -ne "" -and $_ -notmatch "error|warning|INFO" } | Select-Object -First 1)
            }
            if ($path -and (Test-RealPythonPath $path.Trim())) { return $path.Trim() }
            # uv may print a valid path that Test-Path accepts
            if ($path -and (Test-Path $path.Trim())) { return $path.Trim() }
        } catch { }
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python -and (Test-RealPythonPath $python.Source)) {
        try {
            $ver = & python -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')" 2>&1 | Out-String
            if ($ver -and $ver.Trim() -eq $majorMinor) { return $python.Source }
        } catch { }
    }
    return $null
}

function Install-UvViaWinget {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) { return $false }
    Write-Host "  uv: attempting winget install (astral-sh.uv)..." -ForegroundColor Yellow
    & winget install --id=astral-sh.uv -e --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne -1978335189) {
        # -1978335189 = already installed (winget)
        return $false
    }
    Update-SessionPath
    return [bool](Get-Command uv -ErrorAction SilentlyContinue)
}

function Ensure-PythonVersion([string]$ver, [string]$viaLabel) {
    $bin = Find-PythonBin $ver
    if ($bin) {
        $msg = "Selected Python $ver ($bin)"
        if ($viaLabel) { $msg += " via $viaLabel" }
        Write-Host $msg -ForegroundColor Green
        return @{ Version = $ver; Bin = $bin }
    }
    if (-not $Pip -and (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Host "Python $ver not on PATH; installing via uv..." -ForegroundColor Yellow
        Write-Host "(No system Python required - uv will download CPython $ver.)" -ForegroundColor Yellow
        & uv python install $ver
        if ($LASTEXITCODE -ne 0) { throw "uv python install $ver failed" }
        Update-SessionPath
        $bin = Find-PythonBin $ver
        if ($bin) {
            $msg = "Selected Python $ver ($bin) via uv python install"
            if ($viaLabel) { $msg += " ($viaLabel)" }
            Write-Host $msg -ForegroundColor Green
            return @{ Version = $ver; Bin = $bin }
        }
        # uv sync --python <ver> can resolve the interpreter even if find is flaky
        Write-Host "Selected Python $ver (managed by uv; will use: uv sync --python $ver)" -ForegroundColor Green
        return @{ Version = $ver; Bin = $null }
    }
    $hint = "Python $ver not found on PATH / uv."
    if (-not $Pip) {
        $hint += " Install uv (winget install --id=astral-sh.uv) then re-run; uv will download Python."
    }
    else {
        $hint += " Install Python $ver from https://www.python.org/downloads/windows/ (enable 'Add to PATH')."
    }
    throw $hint
}

function Resolve-Python([string[]]$supported, [string]$override) {
    if ($override) {
        $mm = ($override -split "\.")[0..1] -join "."
        if ($supported -notcontains $mm) {
            throw "Python $override is outside supported set: $($supported -join ', ')"
        }
        return Ensure-PythonVersion $mm "-Python"
    }

    for ($i = $supported.Count - 1; $i -ge 0; $i--) {
        $s = $supported[$i]
        $bin = Find-PythonBin $s
        if ($bin) {
            Write-Host "Selected Python $s ($bin)" -ForegroundColor Green
            return @{ Version = $s; Bin = $bin }
        }
    }
    $newest = $supported[$supported.Count - 1]
    return Ensure-PythonVersion $newest ""
}

function Test-SystemPrereqs {
    Write-Host "Checking system prerequisites..."
    Update-SessionPath
    $missing = $false
    $cmake = Get-Command cmake -ErrorAction SilentlyContinue
    if (-not $cmake) {
        Write-Host "  cmake: MISSING" -ForegroundColor Red
        $missing = $true
    }
    else {
        Write-Host "  cmake: OK ($($cmake.Source))" -ForegroundColor Green
    }

    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $uv -and -not $Pip) {
        Write-Host "  uv: MISSING" -ForegroundColor Red
        if (Install-UvViaWinget) {
            $uv = Get-Command uv -ErrorAction SilentlyContinue
        }
    }
    if ($uv) {
        $raw = (& uv --version) | Out-String
        $ver = Get-VersionOrZero $raw
        if ($ver -ge $MinUvVersion) {
            Write-Host "  uv: OK ($($uv.Source), $ver)" -ForegroundColor Green
        }
        else {
            Write-Host "  uv: TOO OLD ($ver < $MinUvVersion)" -ForegroundColor Red
            if (-not $Pip) { $missing = $true }
            else { Write-Host "       (-Pip: continuing without upgrading uv)" -ForegroundColor Yellow }
        }
    }
    else {
        Write-Host "  uv: MISSING" -ForegroundColor Red
        if (-not $Pip) { $missing = $true }
        else { Write-Host "       (-Pip: continuing without uv; need a system Python)" -ForegroundColor Yellow }
    }

    if ($missing) {
        if (-not $cmake) {
            Write-Host "Install cmake with: winget install --id Kitware.CMake -e"
        }
        if (-not $Pip -and -not (Get-Command uv -ErrorAction SilentlyContinue)) {
            Write-Host "Install uv with: winget install --id=astral-sh.uv"
            Write-Host "Then re-run; uv will download Python - no system Python install needed."
            Write-Host "Or re-run with -Pip if you already have a supported system Python."
        }
        Write-Host "See docs/contributing.rst (Windows Development Setup)."
        exit 1
    }
}

function Ensure-Uv {
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $uv) { return $false }
    $raw = (& uv --version) | Out-String
    $ver = Get-VersionOrZero $raw
    if ($ver -lt $MinUvVersion) {
        Write-Host "uv $ver is below $MinUvVersion; run: UV_SYSTEM_CERTS=true uv self update" -ForegroundColor Yellow
        Write-Host "Or reinstall: winget install --id=astral-sh.uv" -ForegroundColor Yellow
        exit 1
    }
    return $true
}

# --- main ---
if ($Help) {
    Show-Help
    exit 0
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

Write-Host "Setting up py-libp2p development environment (Windows)..." -ForegroundColor Green

$supported = Get-SupportedPythonMinors
if (-not $supported -or $supported.Count -eq 0) {
    throw "Could not parse supported Python versions from pyproject.toml"
}

Test-SystemPrereqs
$resolved = Resolve-Python -supported $supported -override $Python
$pyVer = $resolved.Version
$pyBin = $resolved.Bin

if (-not $Pip) {
    if (-not (Ensure-Uv)) {
        Write-Host "uv is required (or pass -Pip)." -ForegroundColor Red
        Write-Host "Install with: winget install --id=astral-sh.uv"
        exit 1
    }
    Write-Host "Using uv for installation (recommended)..." -ForegroundColor Green
    & uv sync --python $pyVer --group dev
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    if (-not $SkipPreCommit) {
        Write-Host "Installing pre-commit hooks..." -ForegroundColor Green
        & uv run pre-commit install
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
}
else {
    if (-not $pyBin) {
        Write-Host "The -Pip path requires a system Python $pyVer on PATH." -ForegroundColor Red
        Write-Host "Install from https://www.python.org/downloads/windows/ (enable Add to PATH),"
        Write-Host "or re-run without -Pip so uv can download Python for you."
        exit 1
    }
    $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        Write-Host "Creating virtual environment with $pyBin..." -ForegroundColor Yellow
        & $pyBin -m venv .venv
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    $pipVerRaw = & $venvPython -m pip --version | Out-String
    $pipVer = Get-VersionOrZero $pipVerRaw
    if ($pipVer -lt $MinPipVersion) {
        Write-Host "pip $pipVer is below $MinPipVersion; upgrading..." -ForegroundColor Yellow
        & $venvPython -m pip install --upgrade "pip>=$MinPipVersion"
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    Write-Host "Using pip for installation..." -ForegroundColor Green
    & $venvPython -m pip install --group dev -e .
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    if (-not $SkipPreCommit) {
        Write-Host "Installing pre-commit hooks..." -ForegroundColor Green
        & $venvPython -m pre_commit install
        if ($LASTEXITCODE -ne 0) {
            & (Join-Path $repoRoot ".venv\Scripts\pre-commit.exe") install
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        }
    }
}

Write-Host "Setup complete! Run 'make pr' (Git Bash) or pytest via the venv." -ForegroundColor Green

# Dot-sourcing can activate in this session; running as a program cannot.
$dotSourced = $MyInvocation.InvocationName -eq '.'
$activatePs1 = Join-Path $repoRoot ".venv\Scripts\Activate.ps1"
$activateBat = Join-Path $repoRoot ".venv\Scripts\activate.bat"
if ($dotSourced -and (Test-Path $activatePs1)) {
    # Restricted policy still blocks Activate.ps1 even when we were launched via .cmd Bypass.
    try {
        . $activatePs1
        Write-Host "Activated .venv in the current session ($((Get-Command python).Source))" -ForegroundColor Green
    } catch {
        Write-Host "Could not activate (execution policy). For this session run:" -ForegroundColor Yellow
        Write-Host "  Set-ExecutionPolicy -Scope Process Bypass" -ForegroundColor Yellow
        Write-Host "  . .\.venv\Scripts\Activate.ps1" -ForegroundColor Yellow
        Write-Host "Or use cmd: .\.venv\Scripts\activate.bat" -ForegroundColor Yellow
        Write-Host "Permanent: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned" -ForegroundColor Yellow
    }
}
else {
    Write-Host "Activate (pick one):" -ForegroundColor Yellow
    Write-Host "  Set-ExecutionPolicy -Scope Process Bypass; . .\.venv\Scripts\Activate.ps1" -ForegroundColor Yellow
    Write-Host "  .\.venv\Scripts\activate.bat          # works under Restricted policy" -ForegroundColor Yellow
    Write-Host "Permanent unlock: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned" -ForegroundColor Yellow
    Write-Host "Then next time: . .\scripts\setup_dev.ps1  (auto-activates)" -ForegroundColor Yellow
    if (Test-Path $activateBat) {
        # no-op: path documented above
    }
}
