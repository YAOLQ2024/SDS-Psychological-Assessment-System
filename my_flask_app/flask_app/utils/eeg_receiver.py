#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
脑电数据接收服务 - 3通道独立处理
采样率: 500Hz
波特率: 230400
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
        
        # ==========================================
        # 情绪推理相关配置（可配置阈值）
        # ==========================================
        self.emotion_thresholds = {
            'T_ASYM': 0.1,      # Alpha不对称性阈值
            'T_BT_POS': 0.7,    # beta/theta 判定积极的阈值
            'T_BT_NEG': 0.3,    # beta/theta 判定消极的阈值
            'MIN_SCORE': 0.2,   # 最小得分阈值（低于此值为neutral）
            'WINDOW_SEC': 4.0,  # 分析窗口大小（秒）
            'MIN_DATA_POINTS': 3  # 最小数据点数
        }
        
        # 情绪推理结果缓存（线程安全）
        self.emotion_result_cache = {
            'label': 'standby',
            'score': 0.0,
            'window_sec': 4.0,
            'timestamp': 0,
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
            'reason': 'initializing'
        }
        self.emotion_lock = threading.Lock()  # 保护情绪结果缓存
        
        # 情绪推理线程控制
        self.emotion_thread = None
        self.emotion_running = False
        
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
        """启动接收线程和情绪推理线程"""
        if self.running:
            print("[EEG] 接收器已在运行")
            return True
        
        try:
            self.ser = serial.Serial(self.serial_port, self.baud_rate, timeout=0.1)
            self.ser.reset_input_buffer()
            self.running = True
            
            # 启动数据接收线程
            self.thread = threading.Thread(target=self._receive_loop, daemon=True)
            self.thread.start()
            
            # 启动情绪推理线程
            self._start_emotion_inference()
            
            print("[EEG] 脑电接收器已启动")
            print(f"  端口: {self.serial_port}")
            print(f"  波特率: {self.baud_rate}")
            print("  采样率: 500Hz")
            print("  通道数: 3")
            print("[EEG] 情绪推理线程已启动（1000ms更新频率）")
            return True
            
        except Exception as e:
            print(f"[EEG] 启动失败: {e}")
            return False
    
    def stop(self):
        """停止接收和情绪推理"""
        self.running = False
        
        # 停止情绪推理线程
        self._stop_emotion_inference()
        
        # 停止数据接收线程
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
                            
                            # 统计日志：每500个数据包打印一次（减少日志量）
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
    
    # ==========================================
    # 情绪推理相关方法（独立线程，不影响数据接收）
    # ==========================================
    
    def _start_emotion_inference(self):
        """启动情绪推理线程"""
        if self.emotion_running:
            return
        
        self.emotion_running = True
        self.emotion_thread = threading.Thread(
            target=self._emotion_inference_loop,
            daemon=True,
            name="EEG-Emotion-Inference"
        )
        self.emotion_thread.start()
        print("[EEG Emotion] 推理线程已启动")
    
    def _stop_emotion_inference(self):
        """停止情绪推理线程"""
        self.emotion_running = False
        if self.emotion_thread:
            self.emotion_thread.join(timeout=2.0)
        print("[EEG Emotion] 推理线程已停止")
    
    def _emotion_inference_loop(self):
        """情绪推理循环（独立线程，1000ms更新一次）"""
        while self.emotion_running:
            try:
                # 计算情绪分类
                result = self._compute_emotion_classification()
                
                # 更新缓存（线程安全）
                with self.emotion_lock:
                    self.emotion_result_cache = result
                    
            except Exception as e:
                print(f"[EEG Emotion] 推理错误: {e}")
                import traceback
                traceback.print_exc()
                # 错误时保持缓存不变，避免返回错误数据
            
            # 等待1000ms后再次推理
            time.sleep(1.0)
    
    def _mean_recent(self, values, timestamps, window_sec):
        """计算最近window_sec秒内的平均值"""
        if not values or not timestamps:
            return None
        
        now = time.time()
        start_time = now - window_sec
        acc = []
        
        # 遍历时间戳，收集窗口内的值
        for i, ts in enumerate(timestamps):
            if ts >= start_time and i < len(values):
                val = values[i]
                if val is not None and not math.isnan(val) and not math.isinf(val):
                    acc.append(val)
        
        if len(acc) < 1:
            return None
        
        return sum(acc) / len(acc)
    
    def _compute_emotion_classification(self):
        """
        计算情绪分类（核心推理逻辑）
        基于Alpha不对称性和Beta/Theta比值
        - CH1: 左，CH2: 右
        """
        window_sec = self.emotion_thresholds['WINDOW_SEC']
        T_ASYM = self.emotion_thresholds['T_ASYM']
        T_BT_POS = self.emotion_thresholds['T_BT_POS']
        T_BT_NEG = self.emotion_thresholds['T_BT_NEG']
        MIN_SCORE = self.emotion_thresholds['MIN_SCORE']
        MIN_DATA_POINTS = self.emotion_thresholds['MIN_DATA_POINTS']
        eps = 1e-6
        
        # 只读访问特征数据（快速复制，立即释放锁）
        with self.lock:
            # 快速复制数据，不进行计算，避免长时间持有锁
            hist = {
                1: {
                    'history': {
                        'alpha': list(self.features_data[1]['history']['alpha']),
                        'beta': list(self.features_data[1]['history']['beta']),
                        'theta': list(self.features_data[1]['history']['theta']),
                        'timestamps': list(self.features_data[1]['history']['timestamps'])
                    }
                },
                2: {
                    'history': {
                        'alpha': list(self.features_data[2]['history']['alpha']),
                        'beta': list(self.features_data[2]['history']['beta']),
                        'theta': list(self.features_data[2]['history']['theta']),
                        'timestamps': list(self.features_data[2]['history']['timestamps'])
                    }
                }
            }
        
        # 在锁外进行计算，避免阻塞数据接收线程
        alpha_l = self._mean_recent(hist[1]['history']['alpha'], hist[1]['history']['timestamps'], window_sec)
        beta_l = self._mean_recent(hist[1]['history']['beta'], hist[1]['history']['timestamps'], window_sec)
        theta_l = self._mean_recent(hist[1]['history']['theta'], hist[1]['history']['timestamps'], window_sec)
        
        alpha_r = self._mean_recent(hist[2]['history']['alpha'], hist[2]['history']['timestamps'], window_sec)
        beta_r = self._mean_recent(hist[2]['history']['beta'], hist[2]['history']['timestamps'], window_sec)
        theta_r = self._mean_recent(hist[2]['history']['theta'], hist[2]['history']['timestamps'], window_sec)
        
        # 复制时间戳列表用于计数
        ts_left = hist[1]['history']['timestamps']
        ts_right = hist[2]['history']['timestamps']
        
        # 统计窗口内的数据点数
        def count_recent(ts_list):
            now = time.time()
            start = now - window_sec
            return sum(1 for t in ts_list if t >= start)
        
        left_cnt = count_recent(ts_left)
        right_cnt = count_recent(ts_right)
        
        # 数据不足，返回standby
        if left_cnt < MIN_DATA_POINTS or right_cnt < MIN_DATA_POINTS:
            return {
                'label': 'standby',
                'score': 0.0,
                'window_sec': window_sec,
                'timestamp': time.time(),
                'features': {
                    'alpha_left': alpha_l,
                    'alpha_right': alpha_r,
                    'beta_left': beta_l,
                    'beta_right': beta_r,
                    'theta_left': theta_l,
                    'theta_right': theta_r,
                    'alpha_log_left': None,
                    'alpha_log_right': None,
                    'fai': None,
                    'beta_theta_left': None,
                    'beta_theta_right': None
                },
                'reason': 'insufficient_data'
            }
        
        # 辅助函数：安全计算比值
        def safe_ratio(a, b):
            if a is None or b is None:
                return None
            # 放宽阈值，极小值也可以计算比值（只要不为0）
            if abs(b) < 1e-30:
                return None
            return a / b
        
        # 辅助函数：安全计算对数
        def safe_log(x):
            if x is None:
                return None
            if x <= 0:
                return None
            return math.log(x)
        
        # 计算Beta/Theta比值
        bt_left = safe_ratio(beta_l, theta_l)
        bt_right = safe_ratio(beta_r, theta_r)
        
        # 计算Alpha不对称性（FAI: Frontal Alpha Asymmetry）
        log_alpha_l = safe_log(alpha_l)
        log_alpha_r = safe_log(alpha_r)
        fai = None
        if log_alpha_l is not None and log_alpha_r is not None:
            fai = log_alpha_l - log_alpha_r  # 左减右
        
        # 默认值
        label = 'neutral'
        score = 0.5
        reason = 'ok'
        
        # 特征值无效
        if fai is None or bt_left is None or bt_right is None:
            return {
                'label': 'standby',
                'score': 0.0,
                'window_sec': window_sec,
                'timestamp': time.time(),
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
                'reason': 'invalid_feature'
            }
        
        # 计算积极/消极得分
        pos_score = 0.0
        neg_score = 0.0
        
        # Alpha不对称性贡献（40%权重）
        if fai > T_ASYM:
            pos_score += min(1.0, fai / T_ASYM) * 0.4
        if fai < -T_ASYM:
            neg_score += min(1.0, abs(fai) / T_ASYM) * 0.4
        
        # Beta/Theta比值贡献（60%权重）
        if bt_left > T_BT_POS and bt_right > T_BT_POS:
            pos_score += min(1.0, min(bt_left, bt_right) / T_BT_POS) * 0.6
        if bt_left < T_BT_NEG and bt_right < T_BT_NEG:
            neg_score += min(1.0, (T_BT_NEG / max(bt_left, bt_right, eps))) * 0.6
        
        # 确定最终标签
        if pos_score > neg_score and pos_score > MIN_SCORE:
            label = 'positive'
            score = min(1.0, pos_score)
        elif neg_score > pos_score and neg_score > MIN_SCORE:
            label = 'negative'
            score = min(1.0, neg_score)
        else:
            label = 'neutral'
            score = 0.5
        
        return {
            'label': label,
            'score': round(float(score), 4),
            'window_sec': window_sec,
            'timestamp': time.time(),
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
    
    def get_emotion_classification(self, window_sec=4.0):
        """
        获取情绪分类结果（立即返回缓存，无计算延迟）
        此方法不进行实际计算，只返回后台推理线程的结果
        """
        with self.emotion_lock:
            # 返回缓存的副本，避免外部修改
            result = self.emotion_result_cache.copy()
            # 如果请求的窗口大小与缓存不一致，更新窗口大小（但不重新计算）
            if window_sec != result.get('window_sec'):
                result['window_sec'] = window_sec
            return result

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
