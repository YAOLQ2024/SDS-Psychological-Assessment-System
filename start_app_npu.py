#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
启智AI 启动脚本
使用昇腾NPU进行AI推理加速
"""

import sys
import os
import signal
import time
import socket
import psutil
from pathlib import Path

# 添加项目路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'my_flask_app'))

def signal_handler(signum, frame):
    """信号处理器"""
    print("\n\n收到停止信号，正在关闭服务...")
    
    # 清理资源
    try:
        from my_flask_app.utils.speech_recognition_npu import npu_speech_service, AscendNPUSpeechRecognitionService
        npu_speech_service.cleanup()
        print("✓ 语音识别服务资源清理完成")
        
        from my_flask_app.utils.emotion_recognition_npu import npu_emotion_service
        if npu_emotion_service:
            npu_emotion_service.cleanup()
            print("✓ 表情识别服务资源清理完成")
        
        # 清理简化版MJPEG视频流服务
        try:
            from my_flask_app.utils import simple_mjpeg_stream
            if simple_mjpeg_stream:
                simple_mjpeg_stream.cleanup()
                print("✓ MJPEG视频流服务资源清理完成")
        except Exception as e:
            print(f"⚠ MJPEG服务清理失败: {e}")
        
    except Exception as e:
        print(f"⚠ 资源清理失败: {e}")
    
    print("服务已停止")
    sys.exit(0)

def check_npu_environment():
    """检查NPU环境"""
    print("检查NPU环境...")
    
    npu_status = {
        'cann_available': False,
        'npu_device_available': False,
        'models_available': False
    }
    
    # 检查昇腾CANN环境
    ascend_home = os.environ.get('ASCEND_HOME', '/usr/local/Ascend')
    if os.path.exists(ascend_home):
        print(f"✓ 昇腾CANN环境: {ascend_home}")
        npu_status['cann_available'] = True
    else:
        print(f"⚠ 昇腾CANN环境未找到: {ascend_home}")
    
    # 检查NPU设备
    npu_devices = ['/dev/davinci0', '/dev/accel/accel0']
    for device in npu_devices:
        if os.path.exists(device):
            print(f"✓ NPU设备: {device}")
            npu_status['npu_device_available'] = True
            break
    
    if not npu_status['npu_device_available']:
        print("⚠ 未检测到NPU设备")
    
    # 检查模型文件
    model_path = "./models/offline_encoder.om"
    if os.path.exists(model_path):
        print(f"✓ 语音模型: {model_path}")
        npu_status['models_available'] = True
    else:
        print(f"⚠ 语音模型未找到: {model_path}")
    
    emotion_model_path = "./models/48model.om"
    if os.path.exists(emotion_model_path):
        print(f"✓ 表情模型: {emotion_model_path}")
    else:
        print(f"⚠ 表情模型未找到: {emotion_model_path}")
    
    return npu_status

def get_system_info():
    """获取系统信息"""
    try:
        # CPU信息
        cpu_count = psutil.cpu_count()
        cpu_percent = psutil.cpu_percent(interval=1)
        
        # 内存信息
        memory = psutil.virtual_memory()
        
        # 网络信息
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
        except Exception:
            local_ip = "127.0.0.1"
        
        return {
            'cpu_cores': cpu_count,
            'cpu_usage': cpu_percent,
            'memory_total': memory.total / (1024**3),
            'memory_usage': memory.percent,
            'memory_available': memory.available / (1024**3),
            'local_ip': local_ip
        }
    except Exception as e:
        print(f"获取系统信息失败: {e}")
        return {}

def initialize_services():
    """初始化服务"""
    print("\n初始化AI服务...")
    
    success_count = 0
    
    # 初始化语音识别服务
    try:
        from my_flask_app.utils.speech_recognition_npu import npu_speech_service
        
        print("加载语音识别模型...")
        success = npu_speech_service.load_model()
        
        if success:
            print("✓ 语音识别服务初始化成功")
            success_count += 1
        else:
            print("⚠ 语音识别服务初始化失败，将使用备用方案")
            
    except Exception as e:
        print(f"⚠ 语音识别服务初始化异常: {e}")
    
    # 初始化表情识别服务
    try:
        from my_flask_app.utils.emotion_recognition_npu import npu_emotion_service
        
        if npu_emotion_service:
            print("加载表情识别模型...")
            success = npu_emotion_service.load_model()
            
            if success:
                print("✓ 表情识别服务初始化成功")
                success_count += 1
            else:
                print("⚠ 表情识别服务初始化失败，将使用备用方案")
        else:
            print("⚠ 表情识别服务不可用")
            
    except Exception as e:
        print(f"⚠ 表情识别服务初始化异常: {e}")
    
    # 初始化简化版MJPEG视频流服务（完全模仿face_emotion.py）
    try:
        from my_flask_app.utils import simple_mjpeg_stream
        
        if simple_mjpeg_stream:
            print("初始化简化版MJPEG视频流服务...")
            success = simple_mjpeg_stream.load_models()
            
            if success:
                print("✓ 简化版MJPEG视频流服务初始化成功（模仿face_emotion.py）")
                success_count += 1
            else:
                print("⚠ 简化版MJPEG视频流服务初始化失败")
        else:
            print("⚠ 简化版MJPEG视频流服务不可用")
            
    except Exception as e:
        print(f"⚠ 简化版MJPEG视频流服务初始化异常: {e}")
    
    return success_count

def main():
    """主启动函数"""
    print("=" * 80)
    print("抑郁症评估系统 - 启智AI板子版")
    print("=" * 80)
    
    # 注册信号处理器
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # 获取系统信息
    print("\n系统信息:")
    system_info = get_system_info()
    for key, value in system_info.items():
        print(f"  {key}: {value}")
    
    # 检查NPU环境
    print()
    npu_status = check_npu_environment()
    
    # 初始化服务
    service_count = initialize_services()
    
    try:
        # 导入Flask应用
        from app import app
        
        # 显示启动信息
        print("\n" + "=" * 80)
        print("系统启动中...")
        print("=" * 80)
        
        if service_count > 0 and any(npu_status.values()):
            print("🚀 AI加速: 昇腾NPU")
            print("⚡ 语音识别: NPU加速推理")
            print("😊 表情识别: NPU加速推理")
            print("📹 视频流: 简化版MJPEG（模仿face_emotion.py）")
        else:
            print("🔄 AI加速: CPU备用模式")
            print("📢 语音识别: CPU标准推理")
            print("😊 表情识别: CPU标准推理")
            print("📹 视频流: 基础模式")
        
        print("💾 数据库: SQLite (嵌入式优化)")
        print(f"🌐 本机访问: http://localhost:5000")
        print(f"🌐 局域网访问: http://{system_info.get('local_ip', '127.0.0.1')}:5000")
        print("👤 默认用户: 用户名=DSH, 密码=1")
        print("=" * 80)
        
        if service_count > 0:
            print("NPU优化特性:")
            print("• 昇腾AI算力加速")
            print("• 实时语音识别推理") 
            print("• 实时表情识别推理")
            print("• 昇腾CANN优化")
            print("• 低延迟高准确率")
            print("• MJPEG流：完全模仿face_emotion.py逻辑")
        else:
            print("CPU备用特性:")
            print("• 多核心并行处理")
            print("• 内存使用优化")
            print("• 轻量级AI推理")
            print("• 兼容性保证")
        
        print("=" * 80)
        print("按 Ctrl+C 停止服务")
        print("=" * 80)
        
        # 配置Flask应用
        app.config['DEBUG'] = False
        app.config['TESTING'] = False
        app.config['ENV'] = 'production'
        
        # 启动应用
        print("🎯 系统已就绪，等待连接...")
        app.run(
            host='0.0.0.0',
            port=5000,
            debug=False,
            threaded=True,
            use_reloader=False
        )
        
    except ImportError as e:
        print(f"\n❌ 导入错误: {e}")
        print("请确保已安装所需依赖")
    except Exception as e:
        print(f"\n❌ 启动错误: {e}")
        print("请检查项目文件完整性和配置")

if __name__ == "__main__":
    main()
