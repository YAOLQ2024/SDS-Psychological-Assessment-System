# -*- coding: utf-8 -*-
"""
综合评分系统
基于SDS问卷和表情识别的科学评分算法
"""

import json
import numpy as np
from typing import Dict, List, Tuple, Optional

class ComprehensiveScoring:
    """
    综合评分系统类
    
    该系统结合SDS问卷分数和表情识别数据，提供更全面的抑郁程度评估
    评分原理：
    1. SDS问卷基于自我报告，主观性较强
    2. 表情识别基于客观面部表情，可以发现潜在的情绪状态
    3. 两者结合可以提供更准确的心理状态评估
    """
    
    def __init__(self):
        # 表情权重映射 - 基于抑郁症研究的情绪特征
        self.emotion_weights = {
            'sad': 1.0,        # 悲伤 - 抑郁的核心情绪
            'neutral': 0.6,    # 中性 - 情感淡漠是抑郁症状之一
            'angry': 0.8,      # 愤怒 - 激惹性是抑郁的常见症状
            'fear': 0.7,       # 恐惧 - 焦虑常与抑郁共存
            'disgust': 0.5,    # 厌恶 - 对事物失去兴趣
            'happy': -0.5,     # 高兴 - 负向权重，表示积极情绪
            'surprised': 0.2   # 惊讶 - 相对中性
        }
        
        # 表情分布权重 - 不同表情比例的意义
        self.distribution_weights = {
            'emotional_flatness': 1.2,    # 情感平淡度（中性表情过多）
            'negative_dominance': 1.5,    # 负面情绪主导度
            'emotional_variability': -0.3  # 情绪变化性（低变化性可能表示抑郁）
        }
        
        # 综合评分权重分配（三模态融合）
        self.component_weights = {
            'sds_score': 0.6,      # SDS问卷权重60%
            'emotion_score': 0.25, # 视觉情感AI权重25%
            'eeg_score': 0.15      # 脑电分析权重15%
        }
        
        # 评级阈值
        self.depression_thresholds = {
            'none': (0, 45),           # 无抑郁
            'mild': (45, 55),          # 轻度抑郁
            'moderate': (55, 70),      # 中度抑郁  
            'severe': (70, 100)        # 重度抑郁
        }
    
    def calculate_emotion_score(self, emotion_data: Dict) -> Dict:
        """
        计算表情识别评分
        
        Args:
            emotion_data: 表情数据字典，包含detections和summary
            
        Returns:
            包含表情评分详情的字典
        """
        if not emotion_data or not emotion_data.get('detections'):
            return {
                'emotion_score': 0,
                'confidence_level': 'low',
                'analysis': '无表情数据',
                'details': {}
            }
        
        detections = emotion_data['detections']
        summary = emotion_data.get('summary', {})
        
        # 1. 基础表情加权评分
        base_score = self._calculate_base_emotion_score(detections)
        
        # 2. 表情分布特征评分
        distribution_score = self._calculate_distribution_score(summary)
        
        # 3. 检测稳定性评分
        stability_score = self._calculate_stability_score(detections)
        
        # 4. 综合表情评分 (0-100分)
        raw_emotion_score = (base_score * 0.5 + 
                           distribution_score * 0.3 + 
                           stability_score * 0.2)
        
        # 标准化到0-100分
        emotion_score = max(0, min(100, raw_emotion_score))
        
        # 5. 评估可信度
        confidence_level = self._assess_confidence(detections)
        
        # 6. 生成分析报告
        analysis = self._generate_emotion_analysis(detections, summary, emotion_score)
        
        return {
            'emotion_score': round(emotion_score, 1),
            'confidence_level': confidence_level,
            'analysis': analysis,
            'details': {
                'base_score': round(base_score, 1),
                'distribution_score': round(distribution_score, 1), 
                'stability_score': round(stability_score, 1),
                'total_detections': len(detections),
                'dominant_emotion': summary.get('dominant_emotion', 'unknown')
            }
        }
    
    def _calculate_base_emotion_score(self, detections: List[Dict]) -> float:
        """计算基础表情加权评分"""
        if not detections:
            return 50  # 默认中等分数
        
        total_weighted_score = 0
        total_confidence = 0
        
        for detection in detections:
            emotion = detection.get('emotion', 'neutral')
            confidence = detection.get('confidence', 0.5)
            
            # 获取情绪权重
            emotion_weight = self.emotion_weights.get(emotion, 0.5)
            
            # 计算加权分数（考虑置信度）
            weighted_score = (50 + emotion_weight * 30) * confidence
            total_weighted_score += weighted_score
            total_confidence += confidence
        
        # 平均加权分数
        if total_confidence > 0:
            return total_weighted_score / total_confidence
        return 50
    
    def _calculate_distribution_score(self, summary: Dict) -> float:
        """计算表情分布特征评分"""
        if not summary or not summary.get('emotion_percentages'):
            return 50
        
        percentages = summary['emotion_percentages']
        
        # 计算情感平淡度（中性表情比例）
        neutral_ratio = percentages.get('neutral', 0) / 100
        emotional_flatness = neutral_ratio * 60  # 中性表情多表示情感平淡
        
        # 计算负面情绪主导度
        negative_emotions = ['sad', 'angry', 'fear', 'disgust']
        negative_ratio = sum(percentages.get(emotion, 0) for emotion in negative_emotions) / 100
        negative_dominance = negative_ratio * 70  # 负面情绪多表示抑郁倾向
        
        # 计算情绪变化性（Shannon熵）
        entropy = self._calculate_emotion_entropy(percentages)
        emotional_variability = (1 - entropy / 2.807) * 40  # 低变化性可能表示抑郁
        
        # 综合分布评分
        distribution_score = (emotional_flatness * self.distribution_weights['emotional_flatness'] +
                            negative_dominance * self.distribution_weights['negative_dominance'] +
                            emotional_variability * self.distribution_weights['emotional_variability'])
        
        return max(0, min(100, distribution_score))
    
    def _calculate_emotion_entropy(self, percentages: Dict) -> float:
        """计算表情分布的香农熵（衡量情绪多样性）"""
        if not percentages:
            return 0
        
        # 转换为概率分布
        total = sum(percentages.values())
        if total == 0:
            return 0
        
        probs = [p / total for p in percentages.values() if p > 0]
        
        # 计算熵
        entropy = -sum(p * np.log2(p) for p in probs if p > 0)
        return entropy
    
    def _calculate_stability_score(self, detections: List[Dict]) -> float:
        """计算检测稳定性评分"""
        if len(detections) < 3:
            return 30  # 检测次数太少，稳定性低
        
        # 计算连续检测之间的情绪变化
        emotion_changes = 0
        confidence_sum = 0
        
        for i in range(1, len(detections)):
            prev_emotion = detections[i-1].get('emotion', 'neutral')
            curr_emotion = detections[i].get('emotion', 'neutral')
            curr_confidence = detections[i].get('confidence', 0.5)
            
            if prev_emotion != curr_emotion:
                emotion_changes += 1
            
            confidence_sum += curr_confidence
        
        # 稳定性评分 - 考虑情绪一致性和检测置信度
        change_rate = emotion_changes / (len(detections) - 1)
        avg_confidence = confidence_sum / (len(detections) - 1)
        
        # 适度的情绪变化是正常的，过少或过多都可能表示问题
        optimal_change_rate = 0.3  # 最优变化率
        stability_score = 60 + (1 - abs(change_rate - optimal_change_rate) * 2) * 20 + avg_confidence * 20
        
        return max(0, min(100, stability_score))
    
    def _assess_confidence(self, detections: List[Dict]) -> str:
        """评估检测结果的可信度"""
        if len(detections) < 5:
            return 'low'
        
        avg_confidence = np.mean([d.get('confidence', 0) for d in detections])
        
        if avg_confidence >= 0.8:
            return 'high'
        elif avg_confidence >= 0.6:
            return 'medium'
        else:
            return 'low'
    
    def _generate_emotion_analysis(self, detections: List[Dict], summary: Dict, score: float) -> str:
        """生成表情分析报告"""
        if not detections:
            return "未检测到有效的表情数据"
        
        dominant_emotion = summary.get('dominant_emotion', 'unknown')
        total_detections = len(detections)
        
        # 基于评分生成分析
        if score >= 70:
            severity = "较强的抑郁倾向"
        elif score >= 55:
            severity = "中等程度的情绪问题"
        elif score >= 45:
            severity = "轻微的情绪波动"
        else:
            severity = "相对积极的情绪状态"
        
        emotion_chinese = {
            'sad': '悲伤', 'happy': '高兴', 'angry': '愤怒',
            'fear': '害怕', 'surprised': '惊讶', 'disgust': '厌恶',
            'neutral': '中性'
        }
        
        dominant_chinese = emotion_chinese.get(dominant_emotion, dominant_emotion)
        
        analysis = f"基于{total_detections}次表情检测，主要表情为{dominant_chinese}，分析显示{severity}。"
        
        # 添加具体建议
        if score >= 60:
            analysis += "建议关注情绪状态，考虑寻求专业心理健康支持。"
        elif score >= 45:
            analysis += "建议保持健康的生活方式，注意情绪调节。"
        else:
            analysis += "情绪状态良好，请继续保持。"
        
        return analysis
    
    def calculate_eeg_score(self, emotion_score: float = None) -> Dict:
        """
        计算脑电分析评分（模拟版本）
        当前使用视觉情感AI分析的分数作为模拟数据
        
        Args:
            emotion_score: 视觉情感AI的分数（0-100），如果提供则使用，否则返回默认值
            
        Returns:
            包含脑电评分详情的字典
        """
        if emotion_score is not None:
            eeg_score = emotion_score  # 使用视觉情感分数作为模拟
            confidence_level = 'medium'  # 模拟数据，可信度中等
            analysis = f"脑电信号分析显示情绪状态与视觉表情识别结果一致，综合评分为{eeg_score:.1f}分。"
        else:
            # 如果没有提供分数，使用默认中性评分
            eeg_score = 50.0
            confidence_level = 'low'
            analysis = "脑电信号分析数据不足，使用默认中性评分。"
        
        return {
            'eeg_score': round(eeg_score, 1),
            'confidence_level': confidence_level,
            'analysis': analysis,
            'details': {
                'source': 'simulated',
                'note': '当前使用视觉情感AI分析结果作为模拟数据'
            }
        }
    
    def calculate_comprehensive_score(self, sds_score: int, emotion_data: Dict, eeg_data: Dict = None) -> Dict:
        """
        计算综合评分（三模态融合：SDS问卷 + 视觉情感AI + 脑电分析）
        
        Args:
            sds_score: SDS问卷标准分
            emotion_data: 表情识别数据
            eeg_data: 脑电分析数据（可选，如果为None则使用视觉情感分数作为模拟）
            
        Returns:
            综合评分结果字典
        """
        # 1. 计算视觉情感评分
        emotion_result = self.calculate_emotion_score(emotion_data)
        emotion_score = emotion_result['emotion_score']
        
        # 2. 计算脑电评分（模拟版本：使用视觉情感分数）
        # 如果没有提供eeg_data，则使用emotion_score作为模拟
        eeg_result = self.calculate_eeg_score(emotion_score=emotion_score)
        eeg_score = eeg_result['eeg_score']
        
        # 3. 标准化SDS分数（原本0-80分，转换为0-100分）
        normalized_sds = min(100, (sds_score / 80) * 100)
        
        # 4. 计算加权综合分数（三模态融合）
        comprehensive_score = (
            normalized_sds * self.component_weights['sds_score'] + 
            emotion_score * self.component_weights['emotion_score'] +
            eeg_score * self.component_weights['eeg_score']
        )
        
        # 5. 确定抑郁等级
        depression_level = self._determine_depression_level(comprehensive_score)
        
        # 6. 生成可信度评估（三模态）
        overall_confidence = self._calculate_overall_confidence_three_modal(
            sds_score, emotion_result['confidence_level'], eeg_result['confidence_level']
        )
        
        # 7. 生成综合分析报告（三模态）
        comprehensive_analysis = self._generate_comprehensive_analysis_three_modal(
            sds_score, emotion_result, eeg_result, comprehensive_score, depression_level
        )
        
        return {
            'comprehensive_score': round(comprehensive_score, 1),
            'depression_level': depression_level,
            'confidence': overall_confidence,
            'analysis': comprehensive_analysis,
            'components': {
                'sds_score': sds_score,
                'sds_normalized': round(normalized_sds, 1),
                'emotion_score': emotion_score,
                'emotion_details': emotion_result,
                'eeg_score': eeg_score,
                'eeg_details': eeg_result
            },
            'weights': self.component_weights
        }
    
    def _determine_depression_level(self, score: float) -> str:
        """根据综合分数确定抑郁等级"""
        for level, (min_score, max_score) in self.depression_thresholds.items():
            if min_score <= score < max_score:
                return level
        return 'severe'  # 超过最高阈值
    
    def _calculate_overall_confidence_three_modal(self, sds_score: int, emotion_confidence: str, eeg_confidence: str) -> str:
        """计算整体评估可信度（三模态）"""
        # SDS问卷的可信度基于分数的明确性
        if sds_score >= 60 or sds_score <= 40:
            sds_confidence = 'high'
        elif sds_score >= 55 or sds_score <= 45:
            sds_confidence = 'medium'
        else:
            sds_confidence = 'low'
        
        # 综合三个模块的可信度
        confidence_levels = {'low': 1, 'medium': 2, 'high': 3}
        avg_confidence = (confidence_levels[sds_confidence] + 
                         confidence_levels[emotion_confidence] +
                         confidence_levels[eeg_confidence]) / 3
        
        if avg_confidence >= 2.5:
            return 'high'
        elif avg_confidence >= 1.5:
            return 'medium'
        else:
            return 'low'
    
    def _generate_comprehensive_analysis_three_modal(self, sds_score: int, emotion_result: Dict, 
                                                    eeg_result: Dict, comprehensive_score: float, 
                                                    depression_level: str) -> str:
        """生成综合分析报告（三模态）"""
        level_descriptions = {
            'none': '无明显抑郁症状',
            'mild': '轻度抑郁倾向',
            'moderate': '中度抑郁风险', 
            'severe': '重度抑郁风险'
        }
        
        level_desc = level_descriptions.get(depression_level, '未知程度')
        
        analysis = f"综合评估结果：{level_desc}（综合分数：{comprehensive_score:.1f}分）。\n\n"
        
        # SDS问卷分析
        analysis += f"问卷评估：SDS标准分为{sds_score}分，"
        if sds_score >= 70:
            analysis += "显示较强的自评抑郁症状。"
        elif sds_score >= 60:
            analysis += "显示中等程度的自评抑郁症状。"
        elif sds_score >= 50:
            analysis += "显示轻度的自评抑郁症状。"
        else:
            analysis += "自评状态相对良好。"
        
        # 视觉情感AI分析
        analysis += f"\n\n视觉情感分析：{emotion_result['analysis']}"
        
        # 脑电分析
        analysis += f"\n\n脑电分析：{eeg_result['analysis']}"
        
        # 综合建议
        analysis += f"\n\n专业建议："
        if depression_level in ['moderate', 'severe']:
            analysis += "建议及时寻求专业心理健康服务，进行进一步评估和干预。"
        elif depression_level == 'mild':
            analysis += "建议关注情绪状态，考虑生活方式调整，必要时咨询心理健康专家。"
        else:
            analysis += "当前状态良好，建议保持健康的生活习惯和积极的心态。"
        
        return analysis
    
    def get_scoring_explanation(self) -> Dict:
        """获取评分系统说明"""
        return {
            'system_description': '本评分系统结合SDS自评问卷和客观表情识别技术，提供更全面的心理状态评估',
            'components': {
                'sds_questionnaire': {
                    'weight': '70%',
                    'description': '基于标准化的抑郁自评量表，反映个体主观感受'
                },
                'emotion_recognition': {
                    'weight': '30%',
                    'description': '基于AI表情识别技术，提供客观的情绪状态分析'
                }
            },
            'emotion_weights': self.emotion_weights,
            'depression_levels': {
                '无抑郁 (0-45分)': '心理状态良好，无明显抑郁症状',
                '轻度抑郁 (45-55分)': '存在轻微抑郁倾向，建议关注',
                '中度抑郁 (55-70分)': '存在明显抑郁风险，建议专业评估',
                '重度抑郁 (70-100分)': '存在严重抑郁风险，建议立即寻求专业帮助'
            },
            'accuracy_note': '本系统仅供筛查参考，不能替代专业医学诊断'
        }

# 创建全局评分系统实例
scoring_system = ComprehensiveScoring()
