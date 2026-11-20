param([string]$Python = "python", [switch]$Cpu)
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
function Invoke-Checked([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program 执行失败，退出码 $LASTEXITCODE" }
}
foreach ($program in @("ffmpeg","ffprobe","git")) {
    Get-Command $program -ErrorAction Stop | Out-Null
}
Invoke-Checked $Python @("-c","import sys; assert sys.version_info[:2] == (3,12), 'Requires Python 3.12'")
Invoke-Checked $Python @("-m","venv",".venv")
Invoke-Checked $Python @("-m","venv",".vsr-env")
Invoke-Checked ".\.venv\Scripts\python.exe" @("-m","pip","install","-r","requirements.txt")
if (-not (Test-Path -LiteralPath "engines\vsr\backend\main.py")) {
    Invoke-Checked "git" @("clone","--depth","1","--branch","1.4.0","https://github.com/YaoFANGUK/video-subtitle-remover.git","engines\vsr")
}
$packages=@("-m","pip","install","-r","engines\vsr\requirements.txt","paddlepaddle==3.0.0")
if ($Cpu) {
    $packages+=@("torch==2.7.0","torchvision==0.22.0")
} else {
    $packages+=@("torch-directml==0.2.5.dev240914","onnxruntime-directml==1.20.1")
}
Invoke-Checked ".\.vsr-env\Scripts\python.exe" $packages
Invoke-Checked ".\.venv\Scripts\python.exe" @("-X","utf8","configure_vsr.py")
& ".\.venv\Scripts\python.exe" -X utf8 launch.py --mcp-config | Out-File -Encoding utf8 "其他Agent接入.json"
Write-Output "安装完成。双击启动分镜工坊，或在 Agent 中导入其他Agent接入.json。"
