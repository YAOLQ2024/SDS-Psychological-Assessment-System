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
        
        buffer = b''
        while self.running:
            try:
                # 读取串口可用数据
                if self.ser.in_waiting:
                    buffer += self.ser.read(self.ser.in_waiting)
                
                # 至少需要头+类型3字节
                if len(buffer) < 3:
                    time.sleep(0.001)
                    continue
                
                # 校验包头 0x06 0x09
                if buffer[0] != 0x06 or buffer[1] != 0x09:
                    buffer = buffer[1:]
                    continue
                
                pkt_type = buffer[2]
                if pkt_type == 0x01:
                    target_len = 10
                elif pkt_type == 0x02:
                    target_len = 18
                else:
                    # 未知类型，跳过头部
                    buffer = buffer[2:]
                    continue
                
                # 长度不足，等待更多数据
                if len(buffer) < target_len:
                    time.sleep(0.001)
                    continue
                
                frame = buffer[:target_len]
                buffer = buffer[target_len:]
                
                # CRC 校验（最后2字节为大端 CRC）
                data_to_check = frame[:-2]
                local_crc = self.calculate_crc16_nrf(data_to_check)
                recv_crc = struct.unpack('>H', frame[-2:])[0]
                
                if local_crc != recv_crc:
                    self.stats['invalid_packets'] += 1
                    self.consecutive_errors += 1
                    # CRC 错，丢弃一个字节尝试重新同步
                    buffer = frame[1:] + buffer
                    continue
                
                # 解析通道号
                ch = int(frame[3])
                if ch < 1 or ch > 3:
                    self.stats['invalid_packets'] += 1
                    continue
                
                if pkt_type == 0x01:
                    raw_val = struct.unpack('<f', frame[4:8])[0]
                    if not is_valid_float(raw_val):
                        self.stats['invalid_packets'] += 1
                        continue
                    
                    with self.lock:
                        self.channels_data[ch]['values'].append(raw_val)
                        self.channels_data[ch]['timestamps'].append(time.time())
                        self.stats['data_packets'] += 1
                        self.stats['total_packets'] += 1
                        if self.stats['data_packets'] % 500 == 0:
                            print(f"[EEG] 数据包统计 - 通道1: {len(self.channels_data[1]['values'])}, 通道2: {len(self.channels_data[2]['values'])}, 通道3: {len(self.channels_data[3]['values'])}")
                
                elif pkt_type == 0x02:
                    theta, alpha, beta = struct.unpack('<3f', frame[4:16])
                    if not (is_valid_float(theta) and is_valid_float(alpha) and is_valid_float(beta)):
                        self.stats['invalid_packets'] += 1
                        continue
                    
                    with self.lock:
                        current_time = time.time()
                        self.features_data[ch]['current'] = {
                            'theta': theta,
                            'alpha': alpha,
                            'beta': beta,
                            'timestamp': current_time
                        }
                        self.features_data[ch]['history']['theta'].append(theta)
                        self.features_data[ch]['history']['alpha'].append(alpha)
                        self.features_data[ch]['history']['beta'].append(beta)
                        self.features_data[ch]['history']['timestamps'].append(current_time)
                        self.stats['feature_packets'] += 1
                        self.stats['total_packets'] += 1
                        if self.stats['feature_packets'] % 10 == 0:
                            print(f"[EEG] 特征包 - 通道{ch}: Theta={theta:.2f}, Alpha={alpha:.2f}, Beta={beta:.2f}")
                
                # 小睡避免CPU空转
                time.sleep(0.0005)
            
            except Exception as e:
                if self.running:
                    print(f"[EEG] 接收错误: {e}")
                    time.sleep(0.05)
    
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
            
            # 调试：打印返回的特征值
            for ch in [1, 2, 3]:
                ch_key = f'channel{ch}'
                current = result[ch_key]['features']['current']
                print(f"[EEG DEBUG] 返回通道{ch}特征值: Theta={current.get('theta')}, Alpha={current.get('alpha')}, Beta={current.get('beta')}")
            
            return result
    
    def _mean_recent(self, values, timestamps, window_sec):
        """计算最近 window_sec 内的均值，若不足返回 None"""
        if not values or not timestamps:
            return None
        now = time.time()
        start = now - window_sec
        acc = [v for v, t in zip(values, timestamps) if t >= start]
        if len(acc) < 1:
            return None
        return sum(acc) / len(acc)

    def get_emotion_classification(self, window_sec=4.0):
        """
        规则版情绪分类（占位，无需训练）
        - CH1: 左，CH2: 右
        - 窗口：最近 window_sec 秒，默认 4s
        - 阈值含义：
          T_ASYM: 阿尔法不对称性阈值（log(alpha_L) - log(alpha_R)）
          T_BT_POS: beta/theta 判定积极的阈值
          T_BT_NEG: beta/theta 判定消极的阈值
        """
        # 放宽中性区间：更清晰的积极/消极分界
        T_ASYM = 0.1   # 不对称性阈值
        T_BT_POS = 0.7  # beta/theta 判定积极阈值
        T_BT_NEG = 0.3  # beta/theta 判定消极阈值
        eps = 1e-6

        with self.lock:
            hist = self.features_data
            alpha_l = self._mean_recent(hist[1]['history']['alpha'], hist[1]['history']['timestamps'], window_sec)
            beta_l = self._mean_recent(hist[1]['history']['beta'], hist[1]['history']['timestamps'], window_sec)
            theta_l = self._mean_recent(hist[1]['history']['theta'], hist[1]['history']['timestamps'], window_sec)

            alpha_r = self._mean_recent(hist[2]['history']['alpha'], hist[2]['history']['timestamps'], window_sec)
            beta_r = self._mean_recent(hist[2]['history']['beta'], hist[2]['history']['timestamps'], window_sec)
            theta_r = self._mean_recent(hist[2]['history']['theta'], hist[2]['history']['timestamps'], window_sec)

            # 记录时间戳列表长度
            ts_left = list(hist[1]['history']['timestamps'])
            ts_right = list(hist[2]['history']['timestamps'])

        def count_recent(ts_list):
            now = time.time()
            start = now - window_sec
            return sum(1 for t in ts_list if t >= start)

        left_cnt = count_recent(ts_left)
        right_cnt = count_recent(ts_right)
        if left_cnt < 3 or right_cnt < 3:
            return {
                'label': 'standby',
                'score': 0.0,
                'window_sec': window_sec,
                'features': {
                    'alpha_left': alpha_l,
                    'alpha_right': alpha_r,
                    'beta_left': beta_l,
                    'beta_right': beta_r,
                    'theta_left': theta_l,
                    'theta_right': theta_r,
                },
                'reason': 'insufficient_data'
            }

        def safe_ratio(a, b):
            if a is None or b is None:
                return None
            if abs(b) < eps:
                return None
            return a / b

        def safe_log(x):
            if x is None or x <= 0:
                return None
            return math.log(x)

        bt_left = safe_ratio(beta_l, theta_l)
        bt_right = safe_ratio(beta_r, theta_r)
        fai = None
        log_alpha_l = safe_log(alpha_l)
        log_alpha_r = safe_log(alpha_r)
        if log_alpha_l is not None and log_alpha_r is not None:
            fai = log_alpha_l - log_alpha_r

        label = 'neutral'
        score = 0.5
        reason = 'ok'

        if fai is None or bt_left is None or bt_right is None:
            label = 'standby'
            score = 0.0
            reason = 'invalid_feature'
        else:
            # 计算积极/消极得分，取最大
            pos_score = 0.0
            neg_score = 0.0
            # 不对称性贡献
            if fai > T_ASYM:
                pos_score += min(1.0, fai / T_ASYM) * 0.4
            if fai < -T_ASYM:
                neg_score += min(1.0, abs(fai) / T_ASYM) * 0.4
            # beta/theta 贡献
            if bt_left > T_BT_POS and bt_right > T_BT_POS:
                pos_score += min(1.0, min(bt_left, bt_right) / T_BT_POS) * 0.6
            if bt_left < T_BT_NEG and bt_right < T_BT_NEG:
                # 防止除零，使用比值反向
                neg_score += min(1.0, (T_BT_NEG / max(bt_left, bt_right, eps))) * 0.6

            if pos_score > neg_score and pos_score > 0.2:
                label = 'positive'
                score = min(1.0, pos_score)
            elif neg_score > pos_score and neg_score > 0.2:
                label = 'negative'
                score = min(1.0, neg_score)
            else:
                label = 'neutral'
                score = 0.5

        return {
            'label': label,
            'score': round(float(score), 4),
            'window_sec': window_sec,
            'features': {
                'alpha_left': alpha_l,
                'alpha_right': alpha_r,
                'beta_left': beta_l,
                'beta_right': beta_r,
                'theta_left': theta_l,
                'theta_right': theta_r,
                'alpha_log_left': log_alpha_l,
                'alpha_log_right': log_alpha_r,
                'fai': fai,
                'beta_theta_left': bt_left,
                'beta_theta_right': bt_right
            },
            'reason': reason
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
