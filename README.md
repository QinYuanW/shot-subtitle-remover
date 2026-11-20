# 分镜去字幕 · Shot Subtitle Remover

先切分镜头，再给选中的片段去除硬字幕和文字水印。逐段对照原片与处理版，审核通过后按选定顺序合成。支持本地运行和 MCP 接入。

双击 **启动分镜工坊.cmd** 打开本地审核台，也可以给已接入的 Agent 发送视频绝对路径。一个任务对应一个视频。一次提交多条路径可以并行切分，去字按队列逐段运行。

## 两次审核

1. 播放编号预览，取消不需要的片段。用「前移」「后移」调整合成顺序。需要保护实景屏幕、课件或招牌时，在「去字范围与修复方式」中暂停画面，框选叠加文字。点击「确认选片，开始去字」提交。
2. 对照原片与处理版，逐段点击「通过此版本」。出现漏字或抖动时，展开修复设置，调整区域或方式，点击「提交这段返工」。程序保存修订号、审核时间及文件哈希。
3. 点击「按当前顺序合成」。成品目录新增通过的分镜和完整视频。原片、切分预览、修订历史、工作音轨及运行日志保存在各自的位置。任务页可刷新，重新启动服务后可继续。

程序默认使用 PySceneDetect AdaptiveDetector 取得分镜，FFmpeg 负责生成预览、音轨和成片。Video Subtitle Remover 使用独立 Python 环境运行。「自动识字」模式可在框内检测，也可检查整个画面。「框内整体修复」适用于位置已知的残字或固定叠加区域，请框紧目标。

本机安装使用 Paddle CPU 识字、DirectML 运行 STTN 修复。多个分镜需要返工时，可分别勾选「加入返工」、填写备注及调整范围，然后统一提交。

## 接入 Agent

本机支持 MCP stdio 的客户端可以使用 **其他Agent接入.json** 中的 `shotwork` 配置。首次调用自动启动本地审核服务。任务和审核由程序存储，客户端可通过任务编号接续。

| MCP 操作 | 参数与用途 |
| --- | --- |
| `create_video_jobs` | 必填 `sources` 是视频绝对路径列表。可传同顺序的 `titles` 和成品目录 `output_directory`。返回任务编号与浏览器审核链接。 |
| `list_video_jobs` | 列出本机任务，供其他 Agent 接手。 |
| `get_video_job` | 传入 `job_id` 查询审核进度、修订及成品路径。 |

同机各客户端使用同一份程序和数据目录。审核界面仅监听本机回环地址。移动项目后，用项目虚拟环境运行 `launch.py --mcp-config` 重新生成绝对路径配置。

## 在另一台 Windows 电脑安装

安装 Python 3.12、Git 和带 ffprobe 的 FFmpeg，将它们加入 PATH。复制项目源文件并运行 `安装.ps1`。默认安装 DirectML 运行环境，纯 CPU 安装使用 `安装.ps1 -Cpu`。若 Python 命令有别名，可用 `-Python` 指定实际解释器。安装后使用新机器生成的 Agent 配置。

可在项目根目录的 `settings.json` 设置 `output_directory`、`port`、`vsr_home` 和 `vsr_python`。省略成品目录时默认保存到项目的 `data/成品`。工作数据默认在 `data`，可用 `SHOTWORK_DATA` 指向其他工作目录。更改设置后重新启动服务。

端到端自检使用合成测试卡，覆盖两次审核、单段返工、版本校验、换序合成及已有文件保护。在项目虚拟环境运行 `python tests/smoke.py`，测试工作区独立于正式任务。

上游项目见 [PySceneDetect](https://www.scenedetect.com/) 和 [Video Subtitle Remover](https://github.com/YaoFANGUK/video-subtitle-remover/tree/1.4.0)。
