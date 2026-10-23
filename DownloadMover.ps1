# 下载整理助手：列出最新下载，手动多选移动；开启"自动存放"后新下载完成的文件自动移到目标文件夹
param([switch]$Tray, [string]$Config)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -Namespace DM -Name Native -MemberDefinition '[DllImport("psapi.dll")] public static extern bool EmptyWorkingSet(IntPtr h);'

# 只允许运行一个
$mutex = New-Object System.Threading.Mutex($false, 'Local\DownloadMover_Single')
if (-not $mutex.WaitOne(0)) {
    [Windows.Forms.MessageBox]::Show('下载整理助手已经在运行了，请看屏幕右下角托盘图标。', '下载整理助手') | Out-Null
    exit
}

if (-not $Config) { $Config = Join-Path $PSScriptRoot 'config.json' }
# 浏览器下载中的临时文件，不处理
$TempExt = @('.crdownload', '.part', '.partial', '.tmp', '.download', '.opdownload', '.!ut', '.bc!', '.td', '.xltd')
$StartupLink = Join-Path ([Environment]::GetFolderPath('Startup')) '下载整理助手.lnk'

function Get-DownloadsDir {
    try {
        $p = (Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders').'{374DE290-123F-4565-9164-39C4925E467B}'
        if ($p) { return [Environment]::ExpandEnvironmentVariables($p) }
    } catch {}
    Join-Path $env:USERPROFILE 'Downloads'
}

$cfg = [ordered]@{ DownloadDir = (Get-DownloadsDir); TargetDir = ''; Auto = $false; ShowCount = 50 }
if (Test-Path -LiteralPath $Config) {
    try {
        $j = Get-Content -LiteralPath $Config -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($k in @($cfg.Keys)) { if ($null -ne $j.$k) { $cfg[$k] = $j.$k } }
    } catch {}
}
function Save-Config { $cfg | ConvertTo-Json | Set-Content -LiteralPath $Config -Encoding UTF8 }

function Format-Size([long]$n) {
    if ($n -ge 1GB) { '{0:N2} GB' -f ($n / 1GB) }
    elseif ($n -ge 1MB) { '{0:N1} MB' -f ($n / 1MB) }
    elseif ($n -ge 1KB) { '{0:N0} KB' -f ($n / 1KB) }
    else { "$n B" }
}

# 文件到达下载文件夹的时间：创建时间和修改时间取较晚的
function Get-Time($f) { if ($f.CreationTime -gt $f.LastWriteTime) { $f.CreationTime } else { $f.LastWriteTime } }

function Test-Skip($f) {
    ($f.Attributes -band 6) -or ($TempExt -contains $f.Extension.ToLower())   # 6 = 隐藏 + 系统
}

function Test-Ready([string]$p) {
    try { $fs = [IO.File]::Open($p, 'Open', 'ReadWrite', 'None'); $fs.Close(); $true } catch { $false }
}

# 移动单个文件，重名时自动加 (1)(2)…
function Move-Unique([string]$src, [string]$dir) {
    $name = [IO.Path]::GetFileNameWithoutExtension($src)
    $ext = [IO.Path]::GetExtension($src)
    $dest = Join-Path $dir ($name + $ext)
    $i = 1
    while ([IO.File]::Exists($dest) -or [IO.Directory]::Exists($dest)) {
        $dest = Join-Path $dir "$name ($i)$ext"; $i++
    }
    [IO.File]::Move($src, $dest)
    $dest
}

# 移到目标文件夹并记一条"已完成"
function Move-One([string]$src, [string]$mode) {
    $dest = Move-Unique $src $cfg.TargetDir
    $history.Insert(0, [pscustomobject]@{ Name = [IO.Path]::GetFileName($dest); Src = $src; Dest = $dest; Mode = $mode; Time = [DateTime]::Now.ToString('MM-dd HH:mm') })
    while ($history.Count -gt 200) { $history.RemoveAt(200) }
    Save-History
    if ($form.Visible) { Refresh-History }
    $dest
}

# ---------------- 已完成记录 ----------------
$HistoryPath = Join-Path (Split-Path $Config) 'history.json'
$history = New-Object Collections.ArrayList
if (Test-Path -LiteralPath $HistoryPath) {
    try { foreach ($r in (Get-Content -LiteralPath $HistoryPath -Raw -Encoding UTF8 | ConvertFrom-Json)) { [void]$history.Add($r) } } catch {}
}
function Save-History { ConvertTo-Json -InputObject @($history) | Set-Content -LiteralPath $HistoryPath -Encoding UTF8 }

# 撤销移回下载文件夹的文件，短时间内不让自动存放再把它搬走
$undone = @{}

function Undo-Records($recs) {
    $ok = 0; $fail = @()
    foreach ($r in $recs) {
        if (-not [IO.File]::Exists($r.Dest)) {
            $fail += "$($r.Name)（目标文件夹里已经找不到它）"
            $history.Remove($r); continue
        }
        try {
            $dir = Split-Path $r.Src
            [void][IO.Directory]::CreateDirectory($dir)
            $back = Move-Unique $r.Dest $dir
            $undone[$back] = [DateTime]::Now
            $history.Remove($r); $ok++
        } catch { $fail += "$($r.Name)（$($_.Exception.Message)）" }
    }
    Save-History; Refresh-History; Refresh-List
    $status.Text = "已撤销 $ok 个" + $(if ($fail.Count) { "，$($fail.Count) 个失败" } else { '' })
    if ($fail.Count) { [Windows.Forms.MessageBox]::Show("以下文件撤销失败：`n" + ($fail -join "`n"), '下载整理助手') | Out-Null }
}

function Trim-Memory {
    [GC]::Collect()
    [void][DM.Native]::EmptyWorkingSet([Diagnostics.Process]::GetCurrentProcess().Handle)
}

# ---------------- 界面 ----------------
[Windows.Forms.Application]::EnableVisualStyles()
$font = New-Object Drawing.Font('Microsoft YaHei UI', 9)

$form = New-Object Windows.Forms.Form
$form.Text = '下载整理助手'
$form.ClientSize = New-Object Drawing.Size(1080, 460)
$form.MinimumSize = New-Object Drawing.Size(900, 360)
$form.StartPosition = 'CenterScreen'
$form.Font = $font
$form.Icon = [Drawing.Icon]::ExtractAssociatedIcon("$env:SystemRoot\explorer.exe")

# 左边：下载列表；右边：已完成记录（拉宽窗口时左边变宽）
$split = New-Object Windows.Forms.SplitContainer
$split.Dock = 'Fill'
$split.FixedPanel = 'Panel2'
$form.Controls.Add($split)
$split.SplitterDistance = 690

function New-Ctl($type, $text, $x, $y, $w, $h, $anchor) {
    $c = New-Object "Windows.Forms.$type"
    $c.Text = $text
    $c.Location = New-Object Drawing.Point($x, $y)
    $c.Size = New-Object Drawing.Size($w, $h)
    $c.Anchor = $anchor
    $parentPanel.Controls.Add($c)
    $c
}

$parentPanel = $split.Panel1

$lblDl     = New-Ctl Label  '' 10 14 450 20 'Top,Left,Right'
$btnDlOpen = New-Ctl Button '打开' 470 9 90 28 'Top,Right'
$btnDl     = New-Ctl Button '更改' 570 9 100 28 'Top,Right'
$lblTg     = New-Ctl Label  '' 10 48 450 20 'Top,Left,Right'
$btnTgOpen = New-Ctl Button '打开' 470 43 90 28 'Top,Right'
$btnTg     = New-Ctl Button '更改' 570 43 100 28 'Top,Right'
$chkAuto   = New-Ctl CheckBox '自动存放（开启后，新下载完成的文件会自动移到目标文件夹）' 10 80 660 24 'Top,Left,Right'
$list      = New-Ctl ListView '' 10 110 660 300 'Top,Bottom,Left,Right'
$btnRef    = New-Ctl Button '刷新' 10 420 80 30 'Bottom,Left'
$btnAll    = New-Ctl Button '全选' 96 420 80 30 'Bottom,Left'
$btnNone   = New-Ctl Button '全不选' 182 420 80 30 'Bottom,Left'
$status    = New-Ctl Label  '' 270 426 260 20 'Bottom,Left,Right'
$btnMove   = New-Ctl Button '移动勾选的文件' 540 420 130 30 'Bottom,Right'
$lblDl.AutoEllipsis = $true; $lblTg.AutoEllipsis = $true; $status.AutoEllipsis = $true

$list.View = 'Details'
$list.CheckBoxes = $true
$list.FullRowSelect = $true
[void]$list.Columns.Add('名称', 360)
[void]$list.Columns.Add('大小', 90)
[void]$list.Columns.Add('下载时间', 140)

$parentPanel = $split.Panel2
$lblHist   = New-Ctl Label  '已完成（勾选后点"撤销"可移回下载文件夹）' 6 14 370 20 'Top,Left,Right'
$histList  = New-Ctl ListView '' 6 43 370 367 'Top,Bottom,Left,Right'
$btnUndo   = New-Ctl Button '撤销勾选的' 6 420 110 30 'Bottom,Left'
$btnLoc    = New-Ctl Button '打开所在位置' 122 420 110 30 'Bottom,Left'
$btnClear  = New-Ctl Button '清空记录' 238 420 90 30 'Bottom,Left'
$histList.View = 'Details'
$histList.CheckBoxes = $true
$histList.FullRowSelect = $true
$histList.ShowItemToolTips = $true
[void]$histList.Columns.Add('名称', 190)
[void]$histList.Columns.Add('方式', 50)
[void]$histList.Columns.Add('时间', 100)

function Refresh-History {
    $histList.BeginUpdate()
    $histList.Items.Clear()
    foreach ($r in $history) {
        $it = New-Object Windows.Forms.ListViewItem($r.Name)
        [void]$it.SubItems.Add($r.Mode)
        [void]$it.SubItems.Add($r.Time)
        $it.Tag = $r
        $it.ToolTipText = "从：$($r.Src)`n到：$($r.Dest)"
        [void]$histList.Items.Add($it)
    }
    $histList.EndUpdate()
}

function Update-Labels {
    $lblDl.Text = '下载文件夹：' + $cfg.DownloadDir
    $lblTg.Text = '目标文件夹：' + $(if ($cfg.TargetDir) { $cfg.TargetDir } else { '（还没选）' })
}

function Refresh-List {
    $checked = @{}
    foreach ($it in $list.CheckedItems) { $checked[$it.Tag] = $true }
    $list.BeginUpdate()
    $list.Items.Clear()
    if ([IO.Directory]::Exists($cfg.DownloadDir)) {
        $files = (New-Object IO.DirectoryInfo $cfg.DownloadDir).GetFiles() |
            Where-Object { -not (Test-Skip $_) } |
            Sort-Object { Get-Time $_ } -Descending |
            Select-Object -First $cfg.ShowCount
        foreach ($f in $files) {
            $it = New-Object Windows.Forms.ListViewItem($f.Name)
            [void]$it.SubItems.Add((Format-Size $f.Length))
            [void]$it.SubItems.Add((Get-Time $f).ToString('yyyy-MM-dd HH:mm'))
            $it.Tag = $f.FullName
            $it.Checked = $checked.ContainsKey($f.FullName)
            [void]$list.Items.Add($it)
        }
    }
    $list.EndUpdate()
}

function Pick-Folder([string]$desc, [string]$start) {
    $dlg = New-Object Windows.Forms.FolderBrowserDialog
    $dlg.Description = $desc
    if ($start -and [IO.Directory]::Exists($start)) { $dlg.SelectedPath = $start }
    if ($dlg.ShowDialog() -eq 'OK') { $dlg.SelectedPath } else { $null }
}

function Test-SameDir($a, $b) { $a.TrimEnd('\') -ieq $b.TrimEnd('\') }

function Pick-Target {
    $p = Pick-Folder '选择要把下载文件放到哪个文件夹' $cfg.TargetDir
    if (-not $p) { return $false }
    if (Test-SameDir $p $cfg.DownloadDir) {
        [Windows.Forms.MessageBox]::Show('目标文件夹不能和下载文件夹是同一个。', '下载整理助手') | Out-Null
        return $false
    }
    $cfg.TargetDir = $p; Save-Config; Update-Labels
    $true
}

function Ensure-Target {
    if ($cfg.TargetDir -and [IO.Directory]::Exists($cfg.TargetDir)) { return $true }
    Pick-Target
}

# ---------------- 托盘 ----------------
$icon = New-Object Windows.Forms.NotifyIcon
$icon.Icon = $form.Icon
$menu = New-Object Windows.Forms.ContextMenuStrip
$menu.Font = $font
$miOpen = $menu.Items.Add('打开主界面')
$miAuto = New-Object Windows.Forms.ToolStripMenuItem('自动存放')
$miAuto.CheckOnClick = $true
[void]$menu.Items.Add($miAuto)
$miBoot = New-Object Windows.Forms.ToolStripMenuItem('开机自动启动')
$miBoot.CheckOnClick = $true
$miBoot.Checked = Test-Path -LiteralPath $StartupLink
[void]$menu.Items.Add($miBoot)
[void]$menu.Items.Add('-')
$miExit = $menu.Items.Add('退出')
$icon.ContextMenuStrip = $menu
$icon.Visible = $true

function Show-Main {
    Refresh-List
    Refresh-History
    $form.Show()
    $form.WindowState = 'Normal'
    $form.Activate()
}

$script:syncing = $false
function Set-Auto([bool]$on) {
    if ($script:syncing) { return }
    if ($on -and -not (Ensure-Target)) { $on = $false }
    $script:syncing = $true
    $chkAuto.Checked = $on
    $miAuto.Checked = $on
    $script:syncing = $false
    $cfg.Auto = $on; Save-Config
    $icon.Text = '下载整理助手（自动存放：' + $(if ($on) { '开' } else { '关' }) + '）'
    $status.Text = if ($on) { '自动存放已开启' } else { '自动存放已关闭' }
}

# ---------------- 自动存放 ----------------
# 新文件先进等待队列，确认下载完（大小 2 秒不变、没被占用）才移动
$pending = @{}
$timer = New-Object Windows.Forms.Timer
$timer.Interval = 1500

function Add-Pending([string]$p) {
    if (-not $cfg.Auto -or -not [IO.File]::Exists($p)) { return }
    if (Test-Skip (New-Object IO.FileInfo $p)) { return }
    if ($undone.ContainsKey($p) -and ([DateTime]::Now - $undone[$p]).TotalSeconds -lt 30) { return }   # 刚撤销回来的
    $pending[$p] = @{ Size = -1; Since = [DateTime]::Now; Added = [DateTime]::Now }
    $timer.Start()
}

$timer.add_Tick({
    foreach ($p in @($pending.Keys)) {
        $info = $pending[$p]
        if (-not $cfg.Auto -or -not [IO.File]::Exists($p)) { $pending.Remove($p); continue }
        $len = (New-Object IO.FileInfo $p).Length
        if ($len -ne $info.Size) { $info.Size = $len; $info.Since = [DateTime]::Now; continue }
        if ($len -eq 0) {
            # 0 字节可能是浏览器占位文件，等 10 分钟还是空的就不管了
            if (([DateTime]::Now - $info.Added).TotalMinutes -gt 10) { $pending.Remove($p) }
            continue
        }
        if (([DateTime]::Now - $info.Since).TotalSeconds -lt 2 -or -not (Test-Ready $p)) { continue }
        $pending.Remove($p)
        try {
            $d = Move-One $p '自动'
            $icon.ShowBalloonTip(2000, '已自动存放', [IO.Path]::GetFileName($d), 'Info')
        } catch {
            $icon.ShowBalloonTip(3000, '自动存放失败', [IO.Path]::GetFileName($p) + "`n" + $_.Exception.Message, 'Warning')
        }
    }
    if ($pending.Count -eq 0) { $timer.Stop() }
    if ($form.Visible) { Refresh-List }
})

$watcher = New-Object IO.FileSystemWatcher
$watcher.IncludeSubdirectories = $false
$watcher.NotifyFilter = 'FileName'
$watcher.SynchronizingObject = $form   # 事件回到界面线程处理
$onChange = {
    param($s, $e)
    Add-Pending $e.FullPath
    if ($form.Visible) { Refresh-List }
}
$watcher.add_Created($onChange)
$watcher.add_Renamed($onChange)
$watcher.add_Deleted({ if ($form.Visible) { Refresh-List } })

function Start-Watch {
    $watcher.EnableRaisingEvents = $false
    if ([IO.Directory]::Exists($cfg.DownloadDir)) {
        $watcher.Path = $cfg.DownloadDir
        $watcher.EnableRaisingEvents = $true
    }
}

# ---------------- 事件 ----------------
$btnRef.add_Click({ Refresh-List; $status.Text = '已刷新' })
$btnAll.add_Click({ foreach ($it in $list.Items) { $it.Checked = $true } })
$btnNone.add_Click({ foreach ($it in $list.Items) { $it.Checked = $false } })
$btnDlOpen.add_Click({ Start-Process explorer.exe $cfg.DownloadDir })
$btnTgOpen.add_Click({ if (Ensure-Target) { Start-Process explorer.exe $cfg.TargetDir } })
$btnTg.add_Click({ [void](Pick-Target) })
$btnDl.add_Click({
    $p = Pick-Folder '选择浏览器的下载文件夹' $cfg.DownloadDir
    if ($p) {
        if ($cfg.TargetDir -and (Test-SameDir $p $cfg.TargetDir)) {
            [Windows.Forms.MessageBox]::Show('下载文件夹不能和目标文件夹是同一个。', '下载整理助手') | Out-Null
            return
        }
        $cfg.DownloadDir = $p; Save-Config; Update-Labels; Start-Watch; Refresh-List
    }
})

$btnMove.add_Click({
    $items = @($list.CheckedItems)
    if ($items.Count -eq 0) { $status.Text = '先勾选要移动的文件'; return }
    if (-not (Ensure-Target)) { return }
    $ok = 0; $fail = @()
    foreach ($it in $items) {
        try { [void](Move-One $it.Tag '手动'); $ok++ } catch { $fail += $it.Text }
    }
    Refresh-List
    $status.Text = "已移动 $ok 个" + $(if ($fail.Count) { "，$($fail.Count) 个失败（可能正在被使用）" } else { '' })
})

$btnUndo.add_Click({
    $recs = @($histList.CheckedItems | ForEach-Object { $_.Tag })
    if ($recs.Count -eq 0) { $status.Text = '先在右边勾选要撤销的文件'; return }
    Undo-Records $recs
})
$btnLoc.add_Click({
    $it = if ($histList.SelectedItems.Count) { $histList.SelectedItems[0] } elseif ($histList.CheckedItems.Count) { $histList.CheckedItems[0] } else { $null }
    if (-not $it) { $status.Text = '先在右边点选一个文件'; return }
    if ([IO.File]::Exists($it.Tag.Dest)) { Start-Process explorer.exe "/select,`"$($it.Tag.Dest)`"" }
    else { $status.Text = '这个文件已经不在目标文件夹里了' }
})
$btnClear.add_Click({
    if ([Windows.Forms.MessageBox]::Show('清空后就不能再撤销这些记录了（文件本身不会动）。确定清空？', '下载整理助手', 'YesNo') -eq 'Yes') {
        $history.Clear(); Save-History; Refresh-History
    }
})

$chkAuto.add_CheckedChanged({ Set-Auto $chkAuto.Checked })
$miAuto.add_CheckedChanged({ Set-Auto $miAuto.Checked })

$miBoot.add_CheckedChanged({
    if ($miBoot.Checked) {
        $sc = (New-Object -ComObject WScript.Shell).CreateShortcut($StartupLink)
        $sc.TargetPath = "$env:SystemRoot\System32\wscript.exe"
        $sc.Arguments = '"' + (Join-Path $PSScriptRoot '启动下载整理.vbs') + '" tray'
        $sc.WorkingDirectory = $PSScriptRoot
        $sc.IconLocation = "$env:SystemRoot\explorer.exe,0"
        $sc.Save()
    } else {
        Remove-Item -LiteralPath $StartupLink -ErrorAction SilentlyContinue
    }
})

$icon.add_DoubleClick({ Show-Main })
$miOpen.add_Click({ Show-Main })
$miExit.add_Click({
    $script:exiting = $true
    $watcher.Dispose()
    $icon.Visible = $false
    $icon.Dispose()
    [Windows.Forms.Application]::Exit()
})

# 点右上角 X 只是缩到托盘，不退出
$form.add_FormClosing({
    param($s, $e)
    if (-not $script:exiting) {
        $e.Cancel = $true
        $form.Hide()
        $icon.ShowBalloonTip(1500, '下载整理助手', '已缩到托盘继续运行，右键托盘图标可退出', 'Info')
        Trim-Memory
    }
})

# ---------------- 启动 ----------------
$null = $form.Handle   # 先建好窗口句柄，后台监听要用
Update-Labels
Start-Watch
Set-Auto ([bool]$cfg.Auto)
if ($Tray) { Trim-Memory } else { Show-Main }
[Windows.Forms.Application]::Run()
