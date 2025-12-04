#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
启智AI板子语音识别服务
使用WeNet ASR模型进行语音识别
"""

import os
import sys
import tempfile
import logging
import re
import time
import numpy as np
from pathlib import Path
from typing import Optional, Dict, Any

# 添加项目路径
# 计算项目根目录：从 utils/ 向上三级到 yiyuzhen_project/
current_file = os.path.abspath(__file__)
project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_file)))
sys.path.insert(0, project_root)

# 导入WeNet ASR
try:
    import torchaudio
    import torchaudio.compliance.kaldi as kaldi
    from ais_bench.infer.interface import InferSession
    NPU_AVAILABLE = True
    print("昇腾NPU环境可用 - 语音识别")
except ImportError as e:
    NPU_AVAILABLE = False
    print(f"昇腾NPU环境不可用: {e}")
    InferSession = None

# 音频处理库
try:
    import soundfile as sf
    AUDIO_LIBS_AVAILABLE = True
except ImportError:
    AUDIO_LIBS_AVAILABLE = False
    print("音频处理库不可用，将使用基础音频处理")


class WeNetASR:
    """WeNet语音识别模型封装"""
    
    def __init__(self, model_path, vocab_path):
        """初始化模型，加载词表"""
        self.vocabulary = self._load_vocab(vocab_path)
        if NPU_AVAILABLE:
            self.model = InferSession(0, model_path)
            # 获取模型输入特征的最大长度
            self.max_len = self.model.get_inputs()[0].shape[1]
        else:
            self.model = None
            self.max_len = 1478  # 默认值

    def _load_vocab(self, txt_path):
        """加载词表"""
        vocabulary = []
        LEN_OF_VALID_FORMAT = 2
        with open(txt_path, 'r', encoding='utf-8') as fin:
            for line in fin:
                arr = line.strip().split()
                # 词表格式：token id
                if len(arr) != LEN_OF_VALID_FORMAT:
                    continue
                vocabulary.append(arr[0])
        return np.array(vocabulary)

    def _remove_duplicates_and_blank(self, token_idx_list):
        """去除重复字符和空白字符"""
        res = []
        cur = 0
        BLANK_ID = 0
        while cur < len(token_idx_list):
            if token_idx_list[cur] != BLANK_ID:
                res.append(token_idx_list[cur])
            prev = cur
            while cur < len(token_idx_list) and token_idx_list[cur] == token_idx_list[prev]:
                cur += 1
        return res

    def _pad_sequence(self, seq_feature, batch_first=True, padding_value=0, max_len=None):
        """对输入特征进行padding，使符合模型输入尺寸"""
        if max_len is None:
            max_len = self.max_len
            
        feature_shape = seq_feature.shape
        feat_len = feature_shape[0]
        if feat_len > max_len:
            # 如果输入特征长度大于模型输入尺寸，则截断
            seq_feature = seq_feature[:max_len].unsqueeze(0)
            return seq_feature

        batch_size = 1
        trailing_dims = feature_shape[1:]
        if batch_first:
            out_dims = (batch_size, max_len) + trailing_dims
        else:
            out_dims = (max_len, batch_size) + trailing_dims

        out_tensor = seq_feature.data.new(*out_dims).fill_(padding_value)
        if batch_first:
            out_tensor[0, :feat_len, ...] = seq_feature
        else:
            out_tensor[:feat_len, 0, ...] = seq_feature
        return out_tensor

    def _resample(self, waveform, sample_rate, resample_rate=16000):
        """音频重采样"""
        waveform = torchaudio.transforms.Resample(
            orig_freq=sample_rate, new_freq=resample_rate)(waveform)
        return waveform, resample_rate

    def _compute_fbank(self, waveform, sample_rate, num_mel_bins=80, 
                       frame_length=25, frame_shift=10, dither=0.0):
        """提取filter bank音频特征"""
        AMPLIFY_FACTOR = 1 << 15
        waveform = waveform * AMPLIFY_FACTOR
        mat = kaldi.fbank(
            waveform,
            num_mel_bins=num_mel_bins,
            frame_length=frame_length,
            frame_shift=frame_shift,
            dither=dither,
            energy_floor=0.0,
            sample_frequency=sample_rate
        )
        return mat

    def preprocess(self, wav_file):
        """数据预处理"""
        waveform, sample_rate = torchaudio.load(wav_file)
        # 音频重采样，采样率16000
        waveform, sample_rate = self._resample(waveform, sample_rate, resample_rate=16000)
        # 计算fbank特征
        feature = self._compute_fbank(waveform, sample_rate)
        feats_lengths = np.array([feature.shape[0]]).astype(np.int32)
        # 对输入特征进行padding，使符合模型输入尺寸
        feats_pad = self._pad_sequence(
            feature,
            batch_first=True,
            padding_value=0,
            max_len=self.max_len
        )
        feats_pad = feats_pad.numpy().astype(np.float32)
        return feats_pad, feats_lengths

    def post_process(self, output):
        """对模型推理结果进行后处理"""
        encoder_out_lens, probs_idx = output[1], output[4]
        token_idx_list = probs_idx[0, :, 0][:encoder_out_lens[0]]
        token_idx_list = self._remove_duplicates_and_blank(token_idx_list)
        text = ''.join(self.vocabulary[token_idx_list])
        return text

    def transcribe(self, wav_file):
        """执行模型推理，将录音文件转为文本"""
        if not NPU_AVAILABLE or self.model is None:
            return ""
        feats_pad, feats_lengths = self.preprocess(wav_file)
        output = self.model.infer([feats_pad, feats_lengths])
        txt = self.post_process(output)
        return txt


class AscendNPUSpeechRecognitionService:
    """
    启智AI板子语音识别服务
    使用WeNet ASR模型进行语音识别
    """
    
    def __init__(self):
        # 模型路径配置
        self.model_path = os.path.join(project_root, "models", "offline_encoder.om")
        self.vocab_path = os.path.join(project_root, "models", "vocab.txt")
        
        # 音频处理配置
        self.sample_rate = 16000
        
        # 模型实例
        self.asr_model = None
        
        # 设置日志
        self._setup_logging()
        
    def _setup_logging(self):
        """设置日志"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)

    def load_model(self):
        """加载语音识别模型"""
        try:
            self.logger.info("开始加载WeNet ASR模型...")
            
            # 检查模型文件
            if not os.path.exists(self.model_path):
                self.logger.error(f"模型文件不存在: {self.model_path}")
                return False
                
            if not os.path.exists(self.vocab_path):
                self.logger.error(f"词表文件不存在: {self.vocab_path}")
                return False
            
            # 初始化模型
            if NPU_AVAILABLE:
                self.asr_model = WeNetASR(self.model_path, self.vocab_path)
                self.logger.info("WeNet ASR模型加载成功")
                return True
            else:
                self.logger.warning("NPU环境不可用，模型无法加载")
                return False
                
        except Exception as e:
            self.logger.error(f"加载模型失败: {e}")
            return False

    def transcribe_audio(self, audio_data_or_path) -> str:
        """
        语音转文字
        :param audio_data_or_path: 音频文件路径或音频字节数据
        :return: 识别的文本
        """
        try:
            self.logger.info("开始语音识别...")
            
            # 确保模型已加载
            if self.asr_model is None:
                if not self.load_model():
                    return ""
            
            # 处理音频数据
            wav_file = None
            if isinstance(audio_data_or_path, (bytes, bytearray)):
                # 如果是字节数据，先保存为临时文件
                with tempfile.NamedTemporaryFile(delete=False, suffix='.wav') as tmp_file:
                    tmp_file.write(audio_data_or_path)
                    wav_file = tmp_file.name
            elif isinstance(audio_data_or_path, str):
                # 如果是文件路径
                wav_file = audio_data_or_path
            else:
                self.logger.error("不支持的音频数据格式")
                return ""
            
            # 执行识别
            text = self.asr_model.transcribe(wav_file)
            
            # 清理临时文件
            if isinstance(audio_data_or_path, (bytes, bytearray)) and wav_file:
                try:
                    os.unlink(wav_file)
                except:
                    pass
            
            self.logger.info(f"语音识别结果: {text}")
            return text
            
        except Exception as e:
            self.logger.error(f"语音识别失败: {e}")
            return ""

    def extract_answer_from_text(self, text: str) -> Optional[str]:
        """
        从识别的文本中提取SDS量表的答案选项
        """
        if not text:
            return None

        text = text.lower().strip()
        
        # 答案匹配规则
        answer_patterns = {
            'A': [
                'a', 'A', '选a', '选择a', 'a选项', '第一项', '第一选项',
                '1', '一', '第一', '第一个', '1选项', '选1', '第1', '壹',
                '没有', '极少', '没有时间', '极少时间', '一点都没有',
                '完全没有', '几乎没有', '从来没有', '从不', '不会',
                '不是', '没感觉', '完全不', '最少', '最轻', '基本没有',
                '无', '零'
            ],
            'B': [
                'b', 'B', '选b', '选择b', 'b选项', '第二项', '第二选项',
                '2', '二', '第二', '第二个', '2选项', '选2', '第2', '贰',
                '少部分', '少部分时间', '少量', '有时', '偶尔',
                '小部分', '有时候', '偶尔有', '不多', '一点点',
                '较少', '轻微', '稍微', '一些', '少许'
            ],
            'C': [
                'c', 'C', '选c', '选择c', 'c选项', '第三项', '第三选项',
                '3', '三', '第三', '第三个', '3选项', '选3', '第3', '叁',
                '相当多', '相当多时间', '很多', '经常', '大部分',
                '较多', '经常有', '常常', '大多数', '大部分时间',
                '比较多', '中等', '明显', '较重', '频繁'
            ],
            'D': [
                'd', 'D', '选d', '选择d', 'd选项', '第四项', '第四选项',
                '4', '四', '第四', '第四个', '4选项', '选4', '第4', '肆',
                '全部', '全部时间', '所有', '总是', '完全',
                '绝大部分', '绝大部分时间', '一直', '始终',
                '每天', '全天', '最多', '最重', '严重', '非常',
                '持续', '不断'
            ]
        }

        # 计算匹配得分
        scores = {}
        for option, patterns in answer_patterns.items():
            scores[option] = 0
            for pattern in patterns:
                if pattern in text:
                    if text == pattern:
                        scores[option] += 10
                    elif pattern.startswith('选') or pattern.endswith('选项'):
                        scores[option] += 8
                    elif pattern.isdigit() or pattern in ['一', '二', '三', '四', '壹', '贰', '叁', '肆']:
                        scores[option] += 6
                    elif len(pattern) >= 3:
                        scores[option] += 4
                    elif len(pattern) == 2:
                        scores[option] += 2
                    else:
                        scores[option] += 1

        # 找到最高得分
        max_score = max(scores.values()) if scores.values() else 0
        if max_score == 0:
            return None

        # 返回最高得分的选项
        best_options = [option for option, score in scores.items() if score == max_score]
        return sorted(best_options)[0] if best_options else None

    def process_speech_for_sds(self, audio_data_or_path) -> Dict[str, Any]:
        """
        处理SDS量表的语音输入
        """
        try:
            start_time = time.time()
            
            # 语音转文字
            text = self.transcribe_audio(audio_data_or_path)
            
            if not text:
                return {
                    'answer': None,
                    'confidence': 0,
                    'text': '',
                    'message': '未识别到有效语音内容，请重试',
                    'processing_time': time.time() - start_time,
                    'npu_used': NPU_AVAILABLE and self.asr_model is not None
                }

            # 提取答案选项
            answer = self.extract_answer_from_text(text)

            # 计算置信度
            base_confidence = 0.9 if (NPU_AVAILABLE and self.asr_model is not None) else 0.7
            confidence = base_confidence if answer else 0.2

            processing_time = time.time() - start_time

            return {
                'answer': answer,
                'confidence': confidence,
                'text': text,
                'message': f'识别到选项: {answer}' if answer else '无法确定选项，请尝试更清楚地表达',
                'processing_time': processing_time,
                'npu_used': NPU_AVAILABLE and self.asr_model is not None,
                'suggestions': [
                    '请尝试说："选择A"、"选B"、"我选C"等',
                    '或直接说数字："1"、"二"、"第三个"等',
                    '或说出对应含义："没有"、"偶尔"、"经常"、"总是"等'
                ] if not answer else None
            }

        except Exception as e:
            self.logger.error(f"处理语音输入失败: {e}")
            return {
                'answer': None,
                'confidence': 0,
                'text': '',
                'message': f'语音识别失败: {str(e)}',
                'processing_time': 0,
                'npu_used': False
            }

    def get_system_info(self) -> Dict[str, Any]:
        """获取系统信息"""
        return {
            'model_loaded': self.asr_model is not None,
            'npu_available': NPU_AVAILABLE,
            'model_path': self.model_path,
            'vocab_path': self.vocab_path
        }

    def cleanup(self):
        """清理资源"""
        try:
            if self.asr_model:
                # 清理模型资源
                self.asr_model = None
            self.logger.info("资源清理完成")
        except Exception as e:
            self.logger.error(f"资源清理失败: {e}")

    @classmethod
    def finalize_acl(cls):
        """最终化ACL（兼容接口）"""
        pass


# 创建全局服务实例
npu_speech_service = AscendNPUSpeechRecognitionService()
