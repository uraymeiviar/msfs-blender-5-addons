<#
.SYNOPSIS
Copies the add-ons of this repository into the Blender installs listed in deploy.local.json.

.DESCRIPTION
Targets come from deploy.local.json at the repository root (git-ignored, one per machine; see
deploy.local.json.example). Two target types:
  portable  the tools\blender folder of an FSS aircraft repository: add-ons go to 5.2\scripts\addons_core, the
            artist guide (docs\user) goes to docs, and the commit line of FSS-ADDONS-VERSION.txt is updated to this
            repository's HEAD.
  user      a Blender user add-on folder, for example %APPDATA%\Blender Foundation\Blender\5.2\scripts\addons.

Safety:
  - A target file that differs from the repository and is newer than the repository's file may hold edits made in
    place; that add-on is skipped unless -Force.
  - Uncommitted changes in the repository are not deployed unless -Force (the version file would name a commit that
    does not contain them).
  - Files in a target that the repository does not have are reported, never deleted.
A running Blender keeps the add-on version it started with: restart it after deploying.

.EXAMPLE
powershell -ExecutionPolicy Bypass -File tools\deploy.ps1 -DryRun
#>
param(
    [string]$Config = (Join-Path (Split-Path $PSScriptRoot -Parent) "deploy.local.json"),
    [string[]]$Addons,
    [switch]$DryRun,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$repo = Split-Path $PSScriptRoot -Parent

function Read-Normalized([string]$path) {
    # Line endings differ between checkouts (core.autocrlf); content is compared without them
    return ([System.IO.File]::ReadAllText($path)) -replace "`r`n", "`n"
}

function Get-SourceFiles([string]$root) {
    Get-ChildItem -LiteralPath $root -Recurse -File |
        Where-Object { $_.FullName -notmatch '\\__pycache__\\' -and $_.Extension -notin '.pyc', '.pyo' }
}

if (-not (Test-Path -LiteralPath $Config)) {
    Write-Host "No deploy configuration: $Config"
    Write-Host "Copy deploy.local.json.example to deploy.local.json and list this machine's Blender installs."
    exit 1
}
$settings = Get-Content -LiteralPath $Config -Raw | ConvertFrom-Json
if (-not $Addons) { $Addons = @($settings.addons) }

$head = (git -C $repo rev-parse HEAD).Trim()
$guide = Join-Path $repo "docs\user"
$dirty = git -C $repo status --porcelain -- $Addons "docs/user"
if ($dirty -and -not $Force) {
    Write-Host "Uncommitted changes in the add-ons or the artist guide; commit them first, or deploy anyway with -Force:"
    $dirty | ForEach-Object { Write-Host "  $_" }
    exit 1
}
$toolsVersion = $null
$init = Join-Path $repo "fss_blender_tools\__init__.py"
if (Test-Path -LiteralPath $init) {
    $match = Select-String -LiteralPath $init -Pattern '"version":\s*\((\d+),\s*(\d+),\s*(\d+)\)'
    if ($match) { $toolsVersion = ($match.Matches[0].Groups[1..3] | ForEach-Object { $_.Value }) -join "." }
}
Write-Host ("Repository {0} at {1}{2}" -f $repo, $head.Substring(0, 7), $(if ($DryRun) { " (dry run)" } else { "" }))

$failures = 0
foreach ($target in $settings.targets) {
    $path = [Environment]::ExpandEnvironmentVariables($target.path)
    Write-Host ""
    Write-Host ("== {0} ({1}): {2}" -f $target.name, $target.type, $path)
    if ($target.type -eq "portable") {
        $addonRoot = Join-Path $path "5.2\scripts\addons_core"
    } elseif ($target.type -eq "user") {
        $addonRoot = $path
    } else {
        Write-Host "   unknown type '$($target.type)': use portable or user"
        $failures++
        continue
    }
    if (-not (Test-Path -LiteralPath $addonRoot)) {
        Write-Host "   not found: $addonRoot"
        $failures++
        continue
    }

    foreach ($addon in $Addons) {
        $source = Join-Path $repo $addon
        $destination = Join-Path $addonRoot $addon
        $changed = @(); $edited = @(); $extra = @()
        foreach ($file in Get-SourceFiles $source) {
            $relative = $file.FullName.Substring($source.Length + 1)
            $other = Join-Path $destination $relative
            if (-not (Test-Path -LiteralPath $other)) { $changed += $relative; continue }
            if ((Read-Normalized $file.FullName) -ne (Read-Normalized $other)) {
                $changed += $relative
                if ((Get-Item -LiteralPath $other).LastWriteTime -gt $file.LastWriteTime) { $edited += $relative }
            }
        }
        if (Test-Path -LiteralPath $destination) {
            foreach ($file in Get-SourceFiles $destination) {
                $relative = $file.FullName.Substring($destination.Length + 1)
                if (-not (Test-Path -LiteralPath (Join-Path $source $relative))) { $extra += $relative }
            }
        }
        if ($extra) { Write-Host ("   {0}: not in the repository, left in place: {1}" -f $addon, ($extra -join ", ")) }
        if (-not $changed) { Write-Host "   $($addon): up to date"; continue }
        if ($edited -and -not $Force) {
            Write-Host ("   {0}: SKIPPED, newer in the target than in the repository (edited there?): {1}" -f $addon, ($edited -join ", "))
            Write-Host "      bring those edits into the repository, or overwrite them with -Force"
            $failures++
            continue
        }
        Write-Host ("   {0}: {1} file(s) to copy: {2}" -f $addon, $changed.Count, ($changed -join ", "))
        if ($DryRun) { continue }
        foreach ($relative in $changed) {
            $other = Join-Path $destination $relative
            New-Item -ItemType Directory -Force -Path (Split-Path $other -Parent) | Out-Null
            Copy-Item -LiteralPath (Join-Path $source $relative) -Destination $other -Force
        }
        $cache = Join-Path $destination "__pycache__"
        if (Test-Path -LiteralPath $cache) { Remove-Item -LiteralPath $cache -Recurse -Force }
        foreach ($relative in $changed) {
            if ((Read-Normalized (Join-Path $source $relative)) -ne (Read-Normalized (Join-Path $destination $relative))) {
                Write-Host "   $($addon): copy check FAILED for $relative"
                $failures++
            }
        }
    }

    if ($target.type -eq "portable" -and (Test-Path -LiteralPath $guide)) {
        # The artist guide matches the deployed add-ons, so it travels with them
        $docs = Join-Path $path "docs"
        $changed = @()
        foreach ($file in Get-SourceFiles $guide) {
            $relative = $file.FullName.Substring($guide.Length + 1)
            $other = Join-Path $docs $relative
            if (-not (Test-Path -LiteralPath $other) -or (Read-Normalized $file.FullName) -ne (Read-Normalized $other)) {
                $changed += $relative
            }
        }
        if (-not $changed) {
            Write-Host "   docs (artist guide): up to date"
        } else {
            Write-Host ("   docs (artist guide): {0} file(s) to copy: {1}" -f $changed.Count, ($changed -join ", "))
            if (-not $DryRun) {
                foreach ($relative in $changed) {
                    $other = Join-Path $docs $relative
                    New-Item -ItemType Directory -Force -Path (Split-Path $other -Parent) | Out-Null
                    Copy-Item -LiteralPath (Join-Path $guide $relative) -Destination $other -Force
                }
            }
        }
    }

    if ($target.type -eq "portable") {
        $versionFile = Join-Path $path "FSS-ADDONS-VERSION.txt"
        if (-not (Test-Path -LiteralPath $versionFile)) {
            Write-Host "   FSS-ADDONS-VERSION.txt not found"
            continue
        }
        $text = [System.IO.File]::ReadAllText($versionFile)
        $updated = $text -replace 'commit [0-9a-f]{40}', "commit $head"
        if ($toolsVersion) { $updated = $updated -replace 'fss_blender_tools \d+\.\d+\.\d+', "fss_blender_tools $toolsVersion" }
        if ($updated -eq $text) {
            Write-Host "   FSS-ADDONS-VERSION.txt: up to date"
        } else {
            Write-Host "   FSS-ADDONS-VERSION.txt: commit $($head.Substring(0, 7))$(if ($toolsVersion) { ", fss_blender_tools $toolsVersion" })"
            if (-not $DryRun) { [System.IO.File]::WriteAllText($versionFile, $updated, (New-Object System.Text.UTF8Encoding $false)) }
        }
        $enable = Join-Path $path "5.2\scripts\startup\fss_enable_addons.py"
        if (Test-Path -LiteralPath $enable) {
            $enabled = Get-Content -LiteralPath $enable -Raw
            foreach ($addon in $Addons) {
                if ($addon -notlike "_*" -and $enabled -notmatch [regex]::Escape("`"$addon`"")) {
                    Write-Host "   note: $addon is not in fss_enable_addons.py ADDONS, so it is not enabled at start"
                }
            }
        }
    }
}

Write-Host ""
if ($failures) {
    Write-Host "Finished with $failures problem(s)."
    exit 1
}
Write-Host $(if ($DryRun) { "Dry run finished; nothing was changed." } else { "Deployed. Restart running Blender instances to load the new versions." })
