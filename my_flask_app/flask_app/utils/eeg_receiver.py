#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
脑电数据接收服务 - 3通道独立处理
采样率: 500Hz
波特率: 250000
"""

import serial
import struct
import time
import threading
from collections import deque
import math

def is_valid_float(value):
    """检查浮点数是否有效"""
    if value is None:
        return False
    if math.isinf(value) or math.isnan(value):
        return False
    return True

class EEGDataReceiver:
    """脑电数据接收器 - 3通道独立处理"""
    
    def __init__(self, serial_port="/dev/ttyUSB0", baud_rate=250000):
        self.serial_port = serial_port
        self.baud_rate = baud_rate
        self.ser = None
        self.running = False
        self.thread = None
        
        # 原始数据缓存（500Hz，全采样）
        self.raw_data = {
            1: deque(maxlen=500),  # 保留1秒数据（500Hz）
            2: deque(maxlen=500),
            3: deque(maxlen=500)
        }
        
        # 降采样后的数据缓存（50Hz，用于绘图）
        self.channels_data = {
            1: {'values': deque(maxlen=200), 'timestamps': deque(maxlen=200)},  # 通道1，保留4秒数据(50Hz)
            2: {'values': deque(maxlen=200), 'timestamps': deque(maxlen=200)},  # 通道2
            3: {'values': deque(maxlen=200), 'timestamps': deque(maxlen=200)}   # 通道3
        }
        
        # 特征数据（每500ms更新一次，保留历史用于绘图）
        self.features_data = {
            1: {
                'current': {'theta': 0.0, 'alpha': 0.0, 'beta': 0.0, 'timestamp': 0},
                'history': {'theta': deque(maxlen=100), 'alpha': deque(maxlen=100), 'beta': deque(maxlen=100), 'timestamps': deque(maxlen=100)}
            },
            2: {
                'current': {'theta': 0.0, 'alpha': 0.0, 'beta': 0.0, 'timestamp': 0},
                'history': {'theta': deque(maxlen=100), 'alpha': deque(maxlen=100), 'beta': deque(maxlen=100), 'timestamps': deque(maxlen=100)}
            },
            3: {
                'current': {'theta': 0.0, 'alpha': 0.0, 'beta': 0.0, 'timestamp': 0},
                'history': {'theta': deque(maxlen=100), 'alpha': deque(maxlen=100), 'beta': deque(maxlen=100), 'timestamps': deque(maxlen=100)}
            }
        }
        
        self.lock = threading.Lock()
        
        # 降采样计数器（每10个数据点保留1个，500Hz -> 50Hz）
        self.downsample_counters = {1: 0, 2: 0, 3: 0}
        self.downsample_rate = 10
        
        # 统计信息
        self.stats = {
            'total_packets': 0,
            'data_packets': 0,
            'feature_packets': 0,
            'invalid_packets': 0
        }
        
    def calculate_crc16_nrf(self, data: bytes):
        """计算CRC16校验码"""
        crc = 0xFFFF
        poly = 0x1021
        for byte in data:
            crc ^= (byte << 8)
            for _ in range(8):
                if crc & 0x8000:
                    crc = ((crc << 1) ^ poly) & 0xFFFF
                else:
                    crc = (crc << 1) & 0xFFFF
        return crc
    
    def start(self):
        """启动接收线程"""
        if self.running:
            print("[EEG] 接收器已在运行")
            return True
        
        try:
            self.ser = serial.Serial(self.serial_port, self.baud_rate, timeout=0.1)
            self.ser.reset_input_buffer()
            self.running = True
            
            self.thread = threading.Thread(target=self._receive_loop, daemon=True)
            self.thread.start()
            
            print("[EEG] 脑电接收器已启动")
            print(f"  端口: {self.serial_port}")
            print(f"  波特率: {self.baud_rate}")
            print("  采样率: 500Hz")
            print("  通道数: 3")
            return True
            
        except Exception as e:
            print(f"[EEG] 启动失败: {e}")
            return False
    
    def stop(self):
        """停止接收"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)
        if self.ser and self.ser.is_open:
            self.ser.close()
        print("[EEG] 接收器已停止")
    
    def _receive_loop(self):
        """接收数据循环"""
        print("[EEG] 接收循环已启动")
        
        while self.running:
            try:
                header = self.ser.read(1)
                if header == b'\x06':
                    next_byte = self.ser.read(1)
                    if next_byte == b'\x09':
                        type_byte = self.ser.read(1)
                        
                        if type_byte == b'\x01':
                            # 数据包（0x01）：10字节
                            remaining = self.ser.read(7)
                            full_packet = b'\x06\x09\x01' + remaining
                            
                            if len(full_packet) == 10:
                                local_crc = self.calculate_crc16_nrf(full_packet[:8])
                                recv_crc = struct.unpack('>H', full_packet[8:10])[0]
                                
                                if local_crc == recv_crc:
                                    ch = int(full_packet[3])
                                    raw_val = struct.unpack('<f', full_packet[4:8])[0]
                                    
                                    if not is_valid_float(raw_val):
                                        self.stats['invalid_packets'] += 1
                                        continue
                                    
                                    # 按通道存储数据（降采样：500Hz -> 50Hz）
                                    if ch in self.channels_data:
                                        with self.lock:
                                            # 存储到原始数据缓存
                                            self.raw_data[ch].append(raw_val)
                                            
                                            # 降采样：每10个数据点保留1个
                                            self.downsample_counters[ch] += 1
                                            if self.downsample_counters[ch] >= self.downsample_rate:
                                                self.downsample_counters[ch] = 0
                                                self.channels_data[ch]['values'].append(raw_val)
                                                self.channels_data[ch]['timestamps'].append(time.time())
                                            
                                            self.stats['data_packets'] += 1
                                            self.stats['total_packets'] += 1
                        
                        elif type_byte == b'\x02':
                            # 特征包（0x02）：18字节
                            remaining = self.ser.read(15)
                            full_packet = b'\x06\x09\x02' + remaining
                            
                            if len(full_packet) == 18:
                                local_crc = self.calculate_crc16_nrf(full_packet[:16])
                                recv_crc = struct.unpack('>H', full_packet[16:18])[0]
                                
                                if local_crc == recv_crc:
                                    ch = int(full_packet[3])
                                    theta, alpha, beta = struct.unpack('<3f', full_packet[4:16])
                                    
                                    if not (is_valid_float(theta) and is_valid_float(alpha) and is_valid_float(beta)):
                                        self.stats['invalid_packets'] += 1
                                        continue
                                    
                                    # 按通道存储特征数据（500ms更新一次）
                                    if ch in self.features_data:
                                        with self.lock:
                                            current_time = time.time()
                                            # 更新当前值
                                            self.features_data[ch]['current'] = {
                                                'theta': theta,
                                                'alpha': alpha,
                                                'beta': beta,
                                                'timestamp': current_time
                                            }
                                            # 添加到历史记录（用于绘图）
                                            self.features_data[ch]['history']['theta'].append(theta)
                                            self.features_data[ch]['history']['alpha'].append(alpha)
                                            self.features_data[ch]['history']['beta'].append(beta)
                                            self.features_data[ch]['history']['timestamps'].append(current_time)
                                            
                                            self.stats['feature_packets'] += 1
                                            self.stats['total_packets'] += 1
                
                time.sleep(0.00001)  # 极小延迟，适应500Hz采样率
                
            except Exception as e:
                if self.running:
                    print(f"[EEG] 接收错误: {e}")
                    time.sleep(0.1)
    
    def get_channel_data(self, channel):
        """获取指定通道的波形数据"""
        with self.lock:
            if channel in self.channels_data:
                return {
                    'values': list(self.channels_data[channel]['values']),
                    'timestamps': list(self.channels_data[channel]['timestamps'])
                }
            return {'values': [], 'timestamps': []}
    
    def get_channel_features(self, channel):
        """获取指定通道的特征数据（当前值+历史记录）"""
        with self.lock:
            if channel in self.features_data:
                return {
                    'current': self.features_data[channel]['current'].copy(),
                    'history': {
                        'theta': list(self.features_data[channel]['history']['theta']),
                        'alpha': list(self.features_data[channel]['history']['alpha']),
                        'beta': list(self.features_data[channel]['history']['beta']),
                        'timestamps': list(self.features_data[channel]['history']['timestamps'])
                    }
                }
            return {
                'current': {'theta': 0.0, 'alpha': 0.0, 'beta': 0.0, 'timestamp': 0},
                'history': {'theta': [], 'alpha': [], 'beta': [], 'timestamps': []}
            }
    
    def get_all_channels_data(self):
        """获取所有通道的数据（降采样后的波形 + 特征数据）"""
        with self.lock:
            return {
                'channel1': {
                    'waveform': list(self.channels_data[1]['values']),
                    'timestamps': list(self.channels_data[1]['timestamps']),
                    'features': {
                        'current': self.features_data[1]['current'].copy(),
                        'history': {
                            'theta': list(self.features_data[1]['history']['theta']),
                            'alpha': list(self.features_data[1]['history']['alpha']),
                            'beta': list(self.features_data[1]['history']['beta']),
                            'timestamps': list(self.features_data[1]['history']['timestamps'])
                        }
                    }
                },
                'channel2': {
                    'waveform': list(self.channels_data[2]['values']),
                    'timestamps': list(self.channels_data[2]['timestamps']),
                    'features': {
                        'current': self.features_data[2]['current'].copy(),
                        'history': {
                            'theta': list(self.features_data[2]['history']['theta']),
                            'alpha': list(self.features_data[2]['history']['alpha']),
                            'beta': list(self.features_data[2]['history']['beta']),
                            'timestamps': list(self.features_data[2]['history']['timestamps'])
                        }
                    }
                },
                'channel3': {
                    'waveform': list(self.channels_data[3]['values']),
                    'timestamps': list(self.channels_data[3]['timestamps']),
                    'features': {
                        'current': self.features_data[3]['current'].copy(),
                        'history': {
                            'theta': list(self.features_data[3]['history']['theta']),
                            'alpha': list(self.features_data[3]['history']['alpha']),
                            'beta': list(self.features_data[3]['history']['beta']),
                            'timestamps': list(self.features_data[3]['history']['timestamps'])
                        }
                    }
                },
                'stats': self.stats.copy()
            }
    
    def get_stats(self):
        """获取统计信息"""
        with self.lock:
            return self.stats.copy()

# 全局单例
eeg_receiver = None

def get_eeg_receiver():
    global eeg_receiver
    if eeg_receiver is None:
        eeg_receiver = EEGDataReceiver()
        try:
            eeg_receiver.start()
        except Exception as e:
            print(f"[EEG] 无法启动脑电接收器: {e}")
    return eeg_receiver

if __name__ == "__main__":
    receiver = EEGDataReceiver()
    if receiver.start():
        print("接收器已启动，按 Ctrl+C 停止...")
        try:
            while True:
                stats = receiver.get_stats()
                print(f"\n统计: 总包={stats['total_packets']}, 数据包={stats['data_packets']}, 特征包={stats['feature_packets']}, 无效={stats['invalid_packets']}")
                
                for ch in [1, 2, 3]:
                    data = receiver.get_channel_data(ch)
                    features = receiver.get_channel_features(ch)
                    print(f"  CH{ch}: 数据点={len(data['values'])}, Theta={features['theta']:.2f}, Alpha={features['alpha']:.2f}, Beta={features['beta']:.2f}")
                
                time.sleep(2)
        except KeyboardInterrupt:
            print("\n停止接收...")
            receiver.stop()
