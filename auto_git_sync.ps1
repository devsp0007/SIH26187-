# IBVAP Real-time Auto-Sync to GitHub
# Watches the project directory and automatically commits & pushes changes

$RepoPath = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RepoPath

Write-Host "=====================================================" -ForegroundColor Cyan
Write-Host "  IBVAP Live Auto-Sync to GitHub" -ForegroundColor Green
Write-Host "  Repository: https://github.com/kunalvish08/IBVAP" -ForegroundColor Yellow
Write-Host "  Target Branch: main" -ForegroundColor Yellow
Write-Host "  Watching: $RepoPath" -ForegroundColor Cyan
Write-Host "  Press Ctrl + C to stop auto-sync." -ForegroundColor Gray
Write-Host "=====================================================" -ForegroundColor Cyan

# Ensure git remote is configured
$remote = git remote get-url origin 2>$null
if (-not $remote) {
    Write-Host "[ERROR] Git origin remote is not configured!" -ForegroundColor Red
    exit 1
}

$debounceSeconds = 6
$lastChangeTime = [DateTime]::MinValue
$pendingChanges = $false
$changedFiles = [System.Collections.Generic.HashSet[string]]::new()

# Setup FileSystemWatcher
$watcher = New-Object System.IO.FileSystemWatcher
$watcher.Path = $RepoPath
$watcher.IncludeSubdirectories = $true
$watcher.EnableRaisingEvents = $true
$watcher.NotifyFilter = [System.IO.NotifyFilters]'FileName, LastWrite, DirectoryName'

$action = {
    $path = $Event.SourceEventArgs.FullPath
    # Ignore internal git, cache, build, and virtualenv paths
    if ($path -match "\\\.git" -or
        $path -match "\\node_modules" -or
        $path -match "\\__pycache__" -or
        $path -match "\\\.venv" -or
        $path -match "\\dist" -or
        $path -match "\\snapshots" -or
        $path -match "\.db(-wal|-shm)?$" -or
        $path -match "\.log$") {
        return
    }

    $relative = $path.Replace($RepoPath, "").TrimStart("\/")
    $script:changedFiles.Add($relative) | Out-Null
    $script:lastChangeTime = [DateTime]::Now
    $script:pendingChanges = $true
    Write-Host "[Change Detected] $relative" -ForegroundColor DarkGray
}

Register-ObjectEvent $watcher 'Changed' -Action $action | Out-Null
Register-ObjectEvent $watcher 'Created' -Action $action | Out-Null
Register-ObjectEvent $watcher 'Deleted' -Action $action | Out-Null
Register-ObjectEvent $watcher 'Renamed' -Action $action | Out-Null

Write-Host "[Watcher Active] Listening for local changes..." -ForegroundColor Green

try {
    while ($true) {
        Start-Sleep -Seconds 1
        if ($script:pendingChanges) {
            $elapsed = ([DateTime]::Now - $script:lastChangeTime).TotalSeconds
            if ($elapsed -ge $debounceSeconds) {
                $script:pendingChanges = $false
                $fileList = ($script:changedFiles | Select-Object -First 3) -join ", "
                if ($script:changedFiles.Count -gt 3) {
                    $fileList += " (+$($script:changedFiles.Count - 3) more)"
                }
                $script:changedFiles.Clear()

                # Check if there are actual git status changes
                $status = (git status --porcelain 2>$null)
                if (-not [string]::IsNullOrWhiteSpace($status)) {
                    $timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
                    $commitMsg = "Live auto-sync: $timestamp [$fileList]"
                    
                    Write-Host "`n[$timestamp] Staging & Committing changes..." -ForegroundColor Yellow
                    git add .
                    git commit -m $commitMsg | Out-Null
                    
                    Write-Host "[$timestamp] Pushing to GitHub (main)..." -ForegroundColor Cyan
                    $pushOutput = git push origin main 2>&1
                    if ($LASTEXITCODE -eq 0) {
                        Write-Host "[$timestamp] Successfully synced to GitHub!" -ForegroundColor Green
                    } else {
                        Write-Host "[$timestamp] Push warning: $pushOutput" -ForegroundColor Red
                    }
                    Write-Host "Waiting for next changes..." -ForegroundColor DarkGray
                }
            }
        }
    }
}
finally {
    $watcher.EnableRaisingEvents = $false
    $watcher.Dispose()
    Get-EventSubscriber | Unregister-Event
    Write-Host "`nAuto-sync stopped." -ForegroundColor Yellow
}
