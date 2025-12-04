from flask_app import create_app
from flask import send_from_directory, redirect
from utils.db import init_database, migrate_database
import os

# 初始化数据库
init_database()

# 执行数据库迁移
migrate_database()

# 初始化脑电接收器（如果设备存在）
try:
    from flask_app.utils.eeg_receiver import get_eeg_receiver
    eeg_receiver = get_eeg_receiver()
    if eeg_receiver and eeg_receiver.running:
        print("[EEG] ✓ 脑电接收器已启动并运行中")
        # 等待1秒后检查数据接收情况
        import time
        time.sleep(1)
        stats = eeg_receiver.get_stats()
        print(f"[EEG] 初始统计: 总包={stats['total_packets']}, 数据包={stats['data_packets']}, 特征包={stats['feature_packets']}")
    else:
        print("[EEG] ⚠ 脑电接收器未运行（设备可能未连接）")
except Exception as e:
    print(f"[EEG] ✗ 脑电接收器初始化失败: {e}")
    import traceback
    traceback.print_exc()

app = create_app()

@app.route('/')
def index():
    return redirect('/login')

@app.route('/static/picture/<path:filename>')
def get_picture(filename):
    static_folder = os.path.join(os.path.dirname(__file__), 'flask_app', 'static', 'picture')
    return send_from_directory(static_folder, filename)

@app.route('/static/video/<path:filename>')
def get_video(filename):
    static_folder = os.path.join(os.path.dirname(__file__), 'flask_app', 'static', 'video')
    return send_from_directory(static_folder, filename)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)