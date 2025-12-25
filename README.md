# 抑郁症评估与情感交互系统（NPU 版）

面向启智/昇腾 NPU 的多模态抑郁症筛查系统。前端基于 Flask，集成 **SDS 自评量表**、**语音识别（NPU 加速）**、**表情识别（NPU 加速）**、**脑电采集（可选串口设备）** 与 MJPEG 视频流，提供实时交互与结果存储。

## 功能特性
- SDS 量表：20 题问卷，自动计算原始分与标准分，并给出抑郁程度。
- 语音答题：上传音频或直接语音输入，由 `speech_recognition_npu` 提取选项并自动回填。
- 表情识别：基于 `yolov8s.om` + `48model.om` 的人脸检测与表情分类，支持 NPU/CPU 双模式。
- 脑电接收：`EEGDataReceiver` 支持 3 通道 500Hz 采样（串口 230400 波特率），实时波形与特征统计。
- 数据存储：SQLite `depression.db`，默认账号 `DSH/1` 自动写入。
- 日志与监控：`logs/` 下输出表情识别、摄像头与情绪历史日志。

## 目录结构
- `start_app_npu.py`：主启动脚本，检测 NPU/CANN、加载模型并启动 Flask。
- `requirements_npu_py39.txt`：Python 3.9 依赖清单（兼容已安装版本）。
- `models/`：NPU/CPU 运行所需模型（语音、表情、人脸检测、词表等）。
- `my_flask_app/`
  - `app.py`：应用入口，初始化数据库、注册蓝图、启动脑电接收器。
  - `flask_app/`：Flask 代码（蓝图、模板、静态资源、MJPEG 服务、EEG 工具等）。
  - `utils/`：数据库初始化迁移、情感/语音识别、打分、视频流等工具。
  - `depression.db`：默认 SQLite 数据库。
- `logs/`：运行日志与历史记录。

## 环境要求
- 操作系统：Linux/Windows；如需 NPU 加速需安装昇腾 CANN（默认路径 `/usr/local/Ascend`）。
- Python：推荐 3.9.x。
- 硬件：可选昇腾 NPU；无 NPU 时自动回退 CPU 模式。脑电功能需串口设备（默认 `/dev/ttyUSB0`, 230400）。

## 下载安装
```bash
# 替换为实际仓库地址
git clone https://github.com/YAOLQ2024/SDS-Psychological-Assessment-System.git
cd yiyuzhen_project

# 建议创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate   # Windows 使用 .venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

## 模型与数据
- 模型文件已放在 `models/`：`offline_encoder.om`（语音）、`yolov8s.om`（检测）、`48model.om`（表情）、`vocab.txt` 等。
- 若自定义模型，请保持同名文件或修改 `my_flask_app/utils/*.py` 中的路径。
- 数据库 `depression.db` 首次运行自动创建并写入默认用户。

## 启动方式
```bash
# 推荐：启用 NPU 检测与服务初始化
python start_app_npu.py

# 仅运行 Flask（不显式检查 NPU）
python my_flask_app/app.py
```
- 默认端口：`5000`，本机 `http://localhost:5000`，局域网参考启动日志中的 IP。
- 退出：Ctrl+C，脚本会尝试释放语音/表情/MJPEG 资源。

## 使用流程
1) 访问 `/login`，使用默认账号 `DSH` / `1` 登录或注册新用户。  
2) 进入 `/SDS` 开始量表；语音作答可上传音频或直接麦克风输入。  
3) 表情检测在摄像头流中实时运行；脑电设备接入后自动采集并在前端展示波形/特征。  
4) 提交后在历史/详情页查看得分、情绪统计和综合结果。

## 常用脚本
- `check_database.py` / `clean_database.py`：数据库检查与清理。
- `diagnose_time.py`：诊断耗时统计。
- `utils/db_migration_emotion.py`：表情字段迁移工具。
- `restart_server.py`：简易重启。

## 运行提示
- 确认环境变量 `ASCEND_HOME` 指向 CANN 安装目录，确保 NPU 设备节点存在（如 `/dev/davinci0`）。
- Windows 环境下如无串口或摄像头，将自动忽略相关功能；NPU 不可用时回退 CPU。
- 日志位于 `logs/`，常见文件：`emotion_recognition.log`（表情）、`camera_fix.log` 等；遇到问题可结合终端启动输出定位。

