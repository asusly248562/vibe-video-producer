# 项目状态与交付验收

新项目由create_project.py创建project.json。旧项目可保留现有文件，在本地补充topic、preferences、music与artifacts字段后导入登记，不要移动或覆盖原成片。scripts/project_state.py不会推断预览是否已经被用户批准；用户授权以当前对话为准。

## 登记与续做

```text
python scripts/project_state.py record --project <项目目录> --kind sources --path sources.md
python scripts/project_state.py record --project <项目目录> --kind storyboard --path storyboard.json
python scripts/project_state.py record --project <项目目录> --kind beat-map --path beat-map.json
python scripts/project_state.py record --project <项目目录> --kind score --path assets/score.m4a
python scripts/project_state.py record --project <项目目录> --kind video --path final/video.mp4
python scripts/project_state.py record --project <项目目录> --kind render-audit --path verification/render-audit.json
python scripts/project_state.py record --project <项目目录> --kind visual-review --path verification/visual-review.json
python scripts/project_state.py record --project <项目目录> --kind cover-4x3 --path covers/horizontal.png
python scripts/project_state.py record --project <项目目录> --kind cover-3x4 --path covers/vertical.png
python scripts/project_state.py record --project <项目目录> --kind publish --path publish.md
python scripts/project_state.py status --project <项目目录> --scope full --require-ready
```

音乐输入由初始化脚本登记为music-source；旧项目需按相同方法登记该项。支持PNG/JPEG封面，其他格式先通过图片工具导出合适版本。record只登记明确指定的项目内文件，不接受目录外路径或指向外部文件的符号链接。

status是只读操作，不修改项目、删除文件或启动渲染。它报告missing与invalid；`--require-ready`在未完成时返回非零。full包含成片、双封面和发布素材；video包含视频及知识/时序证据；covers只检查两张封面；copy只检查发布文案是否已登记且未改变。视觉、文案和知识质量仍由代理检查。

用户只要一张封面时，用cover-4x3或cover-3x4范围，不为通过完整验收而额外制作未请求的素材。

record更新project.json前保留project.previous.json，兼容不允许重命名替换文件的Windows沙箱。若中断导致project.json不完整，先验证previous文件是合法JSON，再恢复；不要删除仍需保留的工程文件。

修改字幕、字号、镜头或素材后，应重做受影响的渲染和复核；状态检查不遍历所有CSS/JS文件，不能把其结果当作所有源码均未改变的保证。只替换封面不必重渲染视频。

## 渲染报告绑定

新版audit_render.py会输出videoSha256、planSha256，以及有配乐时的scoreSha256。带配乐项目必须用最终score执行同步核对，再登记score与report；只跑ffprobe不算音画同步验证。修改MP4、时序或配乐后须重新审计，不能复制旧报告或手改其中的哈希来宣称通过。

## 视觉复核证据

完成实际逐帧和手机可读性检查后，保存UTF-8 JSON：

```json
{
  "passed": true,
  "videoSha256": "当前MP4的SHA-256",
  "planSha256": "当前beat-map.json的SHA-256",
  "sourcesSha256": "当前sources.md的SHA-256",
  "storyboardSha256": "当前storyboard.json的SHA-256",
  "fontsChecked": true,
  "knowledgeChecked": true,
  "checkedFrames": [0, 64, 159],
  "notes": "填写实际看过的画面、切点前后帧和修复情况"
}
```

上面的帧号仅为格式示例，实际checkedFrames必须包含当前cues中全部事件的帧号。应同时查看这些事件前一帧/当帧/后一帧，记录在notes或独立截图中；不能照抄示例作为通过证据。未通过的报告可以登记，status会明确阻止完整交付。

## 发布到GitHub

只上传技能源码、默认配置、参考文档和可复用测试。不要把用户项目、音乐、视频、聊天、真实路径、检查中的个人数据或本机二进制写入公开仓库。发布前核对用户账号、目标仓库与可见性；沿用用户已给的授权。

仓库创建成功不等于发布完成。逐项核对远端文件与预期内容，确认相对路径、UTF-8编码和脚本缩进正确。连接器返回403时，不要反复写入或自行扩大账号权限；使用用户已授权且可行的正常发布方式。遇到配额或自动审批失败，应如实报告已上传项、未上传项和恢复条件，不能声称全部完成，也不能绕过审批。
