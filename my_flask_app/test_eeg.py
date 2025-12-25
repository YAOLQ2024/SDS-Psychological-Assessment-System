#!/usr/bin/env python3
"""测试脑电数据接收器"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from flask_app.utils.eeg_receiver import EEGDataReceiver
import time

print("=" * 70)
print("脑电数据接收器测试")
print("=" * 70)

# 创建接收器实例
receiver = EEGDataReceiver(serial_port="/dev/ttyUSB0", baud_rate=250000)

print("\n尝试启动接收器...")
if receiver.start():
    print("✓ 接收器已启动！")
    print("\n实时数据监控（按 Ctrl+C 停止）:")
    print("-" * 70)
    
    try:
        count = 0
        while True:
            latest = receiver.get_latest_data()
            history = receiver.get_history_data(max_points=10)
            
            count += 1
            if count % 10 == 0:  # 每10次循环打印一次
                print(f"\n[{count}] 最新数据:")
                print(f"  通道: {latest['channel']}")
                print(f"  原始值: {latest['value']:.4f}")
                print(f"  Theta: {latest['theta']:.2f}")
                print(f"  Alpha: {latest['alpha']:.2f}")
                print(f"  Beta:  {latest['beta']:.2f}")
                print(f"  缓存数据点: {len(history['values'])}")
            
            time.sleep(0.1)
            
    except KeyboardInterrupt:
        print("\n\n停止接收...")
        receiver.stop()
        print("✓ 接收器已停止")
        
else:
    print("✗ 接收器启动失败！")
    print("\n可能的原因:")
    print("  1. 串口设备不存在 (/dev/ttyUSB0)")
    print("  2. 没有权限访问串口")
    print("  3. 串口被其他程序占用")
    print("\n解决方法:")
    print("  - 检查设备连接: ls -l /dev/ttyUSB*")
    print("  - 添加权限: sudo chmod 666 /dev/ttyUSB0")
    print("  - 或添加用户到dialout组: sudo usermod -a -G dialout $USER")

print("\n" + "=" * 70)

