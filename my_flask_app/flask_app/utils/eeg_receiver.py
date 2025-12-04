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
    
    def __init__(self, serial_port="/dev/ttyUSB0", baud_rate=230400):
        self.serial_port = serial_port
        self.baud_rate = baud_rate
        self.ser = None
        self.running = False
        self.thread = None
        
        # 原始数据缓存（全采样，不降采样）
        # 这里直接保存最近的 2000 个采样点（约4秒 @500Hz），用于前端绘图
        self.channels_data = {
            1: {'values': deque(maxlen=2000), 'timestamps': deque(maxlen=2000)},
            2: {'values': deque(maxlen=2000), 'timestamps': deque(maxlen=2000)},
            3: {'values': deque(maxlen=2000), 'timestamps': deque(maxlen=2000)}
        }
        
        # 特征数据（每500ms更新一次，保留历史用于绘图）
        # 初始化时使用None而不是0.0，以便区分"未接收数据"和"值为0"
        self.features_data = {
            1: {
                'current': {'theta': None, 'alpha': None, 'beta': None, 'timestamp': 0},
                'history': {'theta': deque(maxlen=100), 'alpha': deque(maxlen=100), 'beta': deque(maxlen=100), 'timestamps': deque(maxlen=100)}
            },
            2: {
                'current': {'theta': None, 'alpha': None, 'beta': None, 'timestamp': 0},
                'history': {'theta': deque(maxlen=100), 'alpha': deque(maxlen=100), 'beta': deque(maxlen=100), 'timestamps': deque(maxlen=100)}
            },
            3: {
                'current': {'theta': None, 'alpha': None, 'beta': None, 'timestamp': 0},
                'history': {'theta': deque(maxlen=100), 'alpha': deque(maxlen=100), 'beta': deque(maxlen=100), 'timestamps': deque(maxlen=100)}
            }
        }
        
        self.lock = threading.Lock()
        
        # 统计信息
        self.stats = {
            'total_packets': 0,
            'data_packets': 0,
            'feature_packets': 0,
            'invalid_packets': 0
        }
        
        # 错误计数器（用于检测连续错误）
        self.consecutive_errors = 0
        # 不再清空串口缓冲区，避免误删正常数据
        self.max_consecutive_errors = 1000000
        
        # 初始化CRC表
        self._init_crc_table()
        
    def _init_crc_table(self):
        """初始化CRC16查表"""
        self._crc_table = [0] * 256
        poly = 0x1021
        for i in range(256):
            crc = i << 8
            for _ in range(8):
                if crc & 0x8000:
                    crc = (crc << 1) ^ poly
                else:
                    crc <<= 1
            self._crc_table[i] = crc & 0xFFFF
    
    def calculate_crc16_nrf(self, data: bytes):
        """
        计算CRC16校验码 (CRC-16/CCITT-FALSE)
        使用查表法，与NRF52代码完全一致
        """
        # 计算CRC
        crc = 0xFFFF  # 初始值
        for byte in data:
            idx = ((crc >> 8) ^ byte) & 0xFF
            crc = ((crc << 8) ^ self._crc_table[idx]) & 0xFFFF
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
        """接收数据循环 - 实时处理数据包"""
        print("[EEG] 接收循环已启动")
        
        buffer = b''
        while self.running:
            try:
                # 1. 读取数据
                if self.ser.in_waiting:
                    buffer += self.ser.read(self.ser.in_waiting)
                
                # 2. 循环解析 (至少需要 Header(2) + Type(1) = 3 字节)
                while len(buffer) >= 3:
                    
                    # --- A. 校验包头 0x06 0x09 ---
                    if buffer[0] != 0x06 or buffer[1] != 0x09:
                        # 如果头不对，丢弃第一个字节，继续找
                        buffer = buffer[1:]
                        continue
                    
                    # --- B. 获取包类型 ---
                    pkt_type = buffer[2]
                    target_len = 0
                    
                    if pkt_type == 0x01:    # 波形包
                        # Header(2) + Type(1) + ID(1) + Data(4) + CRC(2) = 10
                        target_len = 10
                    elif pkt_type == 0x02:  # 特征包
                        # Header(2) + Type(1) + ID(1) + Theta(4) + Alpha(4) + Beta(4) + CRC(2) = 18
                        target_len = 18
                    else:
                        # 未知类型，跳过头（可能是假头）
                        buffer = buffer[2:]
                        continue
                    
                    # --- C. 检查长度是否足够 ---
                    if len(buffer) < target_len:
                        break  # 数据不够，退出循环等待更多数据
                    
                    # --- D. 提取完整一帧 ---
                    frame = buffer[:target_len]
                    
                    # --- E. CRC 校验 ---
                    # 参与校验的数据是除了最后2字节CRC之外的所有数据
                    data_to_check = frame[:-2]
                    calc_crc = self.calculate_crc16_nrf(data_to_check)
                    
                    # 提取接收到的CRC (大端序: 高字节在前)
                    recv_crc = (frame[-2] << 8) | frame[-1]
                    
                    if calc_crc != recv_crc:
                        # CRC校验失败，可能是假头，丢弃1字节重试
                        self.stats['invalid_packets'] += 1
                        # 仅在首次或每100次错误时打印，避免刷屏
                        if self.stats['invalid_packets'] <= 3 or self.stats['invalid_packets'] % 100 == 0:
                            print(f"[EEG] CRC错误: 计算={calc_crc:04X}, 接收={recv_crc:04X}, 包类型={pkt_type}, 帧前4字节={frame[:4].hex()}")
                        buffer = buffer[1:]
                        continue
                    
                    # === CRC校验通过，开始解析 ===
                    # 移除已处理的一帧
                    buffer = buffer[target_len:]
                    
                    # 解析通道号 (frame[3]位置)
                    ch_id = int(frame[3])
                    if ch_id < 1 or ch_id > 3:
                        self.stats['invalid_packets'] += 1
                        continue
                    
                    if pkt_type == 0x01:
                        # === 波形包 (Type 0x01) ===
                        # [4:8] Data (float, little-endian)
                        raw_val = struct.unpack('<f', frame[4:8])[0]
                        if not is_valid_float(raw_val):
                            self.stats['invalid_packets'] += 1
                            continue
                        
                        with self.lock:
                            self.channels_data[ch_id]['values'].append(raw_val)
                            self.channels_data[ch_id]['timestamps'].append(time.time())
                            self.stats['data_packets'] += 1
                            self.stats['total_packets'] += 1
                            if self.stats['data_packets'] % 500 == 0:
                                print(f"[EEG] 数据包统计 - 通道1: {len(self.channels_data[1]['values'])}, 通道2: {len(self.channels_data[2]['values'])}, 通道3: {len(self.channels_data[3]['values'])}")
                    
                    elif pkt_type == 0x02:
                        # === 特征包 (Type 0x02) ===
                        # [4:8]   Theta (float, little-endian)
                        # [8:12]  Alpha (float, little-endian)
                        # [12:16] Beta  (float, little-endian)
                        theta = struct.unpack('<f', frame[4:8])[0]
                        alpha = struct.unpack('<f', frame[8:12])[0]
                        beta  = struct.unpack('<f', frame[12:16])[0]
                        
                        # 调试：打印原始字节和解析值
                        if self.stats['feature_packets'] < 3:
                            print(f"[EEG DEBUG] 特征包原始字节 - Theta: {frame[4:8].hex()}, Alpha: {frame[8:12].hex()}, Beta: {frame[12:16].hex()}")
                            print(f"[EEG DEBUG] 特征包解析值 - Theta: {theta}, Alpha: {alpha}, Beta: {beta}")
                        
                        if not (is_valid_float(theta) and is_valid_float(alpha) and is_valid_float(beta)):
                            self.stats['invalid_packets'] += 1
                            continue
                        
                        with self.lock:
                            current_time = time.time()
                            self.features_data[ch_id]['current'] = {
                                'theta': theta,
                                'alpha': alpha,
                                'beta': beta,
                                'timestamp': current_time
                            }
                            self.features_data[ch_id]['history']['theta'].append(theta)
                            self.features_data[ch_id]['history']['alpha'].append(alpha)
                            self.features_data[ch_id]['history']['beta'].append(beta)
                            self.features_data[ch_id]['history']['timestamps'].append(current_time)
                            self.stats['feature_packets'] += 1
                            self.stats['total_packets'] += 1
                            if self.stats['feature_packets'] % 10 == 0:
                                print(f"[EEG] 特征包 - 通道{ch_id}: Theta={theta:.6f}, Alpha={alpha:.6f}, Beta={beta:.6f}")
                    
                    # 继续处理下一个数据包（while循环内）
                
            except Exception as e:
                if self.running:
                    print(f"[EEG] 接收错误: {e}")
                    time.sleep(0.05)
            
            # 如果没有数据可读，短暂休眠避免CPU空转
            if not self.ser.in_waiting and len(buffer) < 3:
                time.sleep(0.001)
    
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
            result = {
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
            
            return result
    
    def get_emotion_classification(self, window_sec=4.0):
        """情绪标签识别已禁用，保留接口返回待机状态"""
        return {
            'label': 'standby',
            'score': 0.0,
            'window_sec': window_sec,
            'features': {
                'alpha_left': None,
                'alpha_right': None,
                'beta_left': None,
                'beta_right': None,
                'theta_left': None,
                'theta_right': None,
                'alpha_log_left': None,
                'alpha_log_right': None,
                'fai': None,
                'beta_theta_left': None,
                'beta_theta_right': None
            },
            'reason': 'disabled'
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
