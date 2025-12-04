/**
 * 增强视频播放器
 * 支持多种格式、错误处理和备用方案
 */

class EnhancedVideoPlayer {
    constructor(containerId, options = {}) {
        this.containerId = containerId;
        this.container = document.getElementById(containerId);
        this.currentQuestionIndex = 1;
        
        // 配置选项
        this.options = {
            videoBasePath: '/static/video/',
            fallbackMessage: '视频暂时无法播放，请继续答题',
            showFallbackImage: true,
            autoRetry: true,
            maxRetries: 3,
            retryDelay: 1000,
            ...options
        };
        
        // 支持的视频格式
        this.videoFormats = ['mp4', 'webm', 'ogg'];
        
        // 重试计数器
        this.retryCount = 0;
        
        this.init();
    }
    
    init() {
        if (!this.container) {
            console.error('视频容器不存在:', this.containerId);
            return;
        }
        
        this.createVideoElement();
        this.loadQuestion(this.currentQuestionIndex);
    }
    
    createVideoElement() {
        this.container.innerHTML = `
            <div class="enhanced-video-player">
                <div class="video-wrapper">
                    <video id="question-video" 
                           class="w-full h-48 object-cover rounded-lg" 
                           controls 
                           autoplay
                           preload="metadata"
                           playsinline>
                        <p class="video-not-supported">您的浏览器不支持视频播放</p>
                    </video>
                    
                    <!-- 加载状态 -->
                    <div id="video-loading" class="video-loading hidden">
                        <div class="loading-spinner"></div>
                        <p>正在加载视频...</p>
                    </div>
                    
                    <!-- 错误状态 -->
                    <div id="video-error" class="video-error hidden">
                        <div class="error-icon">⚠️</div>
                        <div class="error-content">
                            <h4>视频加载失败</h4>
                            <p id="error-message">网络连接问题，请稍后重试</p>
                            <div class="error-actions">
                                <button id="retry-video" class="retry-btn">重新加载</button>
                                <button id="skip-video" class="skip-btn">跳过视频继续答题</button>
                            </div>
                        </div>
                    </div>
                    
                    <!-- 备用内容 -->
                    <div id="video-fallback" class="video-fallback hidden">
                        <div class="fallback-icon">📹</div>
                        <div class="fallback-content">
                            <h4>题目 ${this.currentQuestionIndex}</h4>
                            <p>视频内容暂时无法播放</p>
                            <p class="text-sm text-gray-600">请直接阅读下方题目内容进行答题</p>
                        </div>
                    </div>
                </div>
                
                <!-- 视频控制信息 (隐藏) -->
                <div class="video-info" style="display: none;">
                    <div class="video-status">
                        <span id="video-status-text">准备播放</span>
                        <div class="video-progress">
                            <div class="progress-bar" id="video-progress-bar"></div>
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        this.videoElement = document.getElementById('question-video');
        this.bindEvents();
    }
    
    bindEvents() {
        // 视频事件监听
        this.videoElement.addEventListener('loadstart', () => {
            this.showLoading();
            this.updateStatus('正在加载视频...');
        });
        
        this.videoElement.addEventListener('loadedmetadata', () => {
            this.hideLoading();
            this.updateStatus('视频已就绪');
        });
        
        this.videoElement.addEventListener('canplay', () => {
            this.hideLoading();
            this.hideError();
            this.updateStatus('可以播放');
            // 自动播放视频
            if (this.videoElement.paused) {
                this.videoElement.play().catch(error => {
                    console.log('自动播放失败:', error);
                });
            }
        });
        
        this.videoElement.addEventListener('error', (e) => {
            this.handleVideoError(e);
        });
        
        this.videoElement.addEventListener('timeupdate', () => {
            this.updateProgress();
        });
        
        // 重试按钮
        const retryBtn = document.getElementById('retry-video');
        if (retryBtn) {
            retryBtn.addEventListener('click', () => {
                this.retryVideo();
            });
        }
        
        // 跳过按钮
        const skipBtn = document.getElementById('skip-video');
        if (skipBtn) {
            skipBtn.addEventListener('click', () => {
                this.showFallback();
            });
        }
    }
    
    loadQuestion(questionIndex) {
        this.currentQuestionIndex = questionIndex;
        this.retryCount = 0;
        
        // 重置状态
        this.hideError();
        this.hideFallback();
        
        // 加载视频
        this.loadVideo();
    }
    
    loadVideo() {
        const videoName = `${this.currentQuestionIndex}.mp4`;
        const videoUrl = `${this.options.videoBasePath}${videoName}`;
        
        console.log('加载视频:', videoUrl);
        
        // 清除现有源
        this.videoElement.innerHTML = '';
        
        // 添加多格式支持
        this.videoFormats.forEach(format => {
            const source = document.createElement('source');
            const formatVideoName = `${this.currentQuestionIndex}.${format}`;
            source.src = `${this.options.videoBasePath}${formatVideoName}`;
            source.type = `video/${format}`;
            this.videoElement.appendChild(source);
        });
        
        // 添加不支持提示
        const notSupported = document.createElement('p');
        notSupported.textContent = '您的浏览器不支持视频播放';
        notSupported.className = 'video-not-supported';
        this.videoElement.appendChild(notSupported);
        
        // 加载视频
        this.videoElement.load();
        
        // 设置超时检测
        this.setLoadTimeout();
    }
    
    setLoadTimeout() {
        // 15秒超时
        this.loadTimeout = setTimeout(() => {
            if (this.videoElement.readyState === 0) {
                console.warn('视频加载超时');
                this.handleVideoError(new Error('视频加载超时'));
            }
        }, 15000);
    }
    
    handleVideoError(error) {
        console.error('视频播放错误:', error);
        
        // 清除超时
        if (this.loadTimeout) {
            clearTimeout(this.loadTimeout);
        }
        
        this.hideLoading();
        
        // 获取错误信息
        let errorMessage = '视频加载失败';
        
        if (this.videoElement.error) {
            switch (this.videoElement.error.code) {
                case 1:
                    errorMessage = '视频下载被中断';
                    break;
                case 2:
                    errorMessage = '网络连接错误';
                    break;
                case 3:
                    errorMessage = '视频解码失败';
                    break;
                case 4:
                    errorMessage = '不支持的视频格式';
                    break;
                default:
                    errorMessage = '未知视频错误';
            }
        }
        
        // 显示错误信息
        const errorMessageElement = document.getElementById('error-message');
        if (errorMessageElement) {
            errorMessageElement.textContent = errorMessage;
        }
        
        // 自动重试
        if (this.options.autoRetry && this.retryCount < this.options.maxRetries) {
            this.showError();
            setTimeout(() => {
                this.retryVideo();
            }, this.options.retryDelay);
        } else {
            this.showError();
        }
        
        this.updateStatus('视频加载失败');
    }
    
    retryVideo() {
        this.retryCount++;
        console.log(`重试加载视频 (${this.retryCount}/${this.options.maxRetries})`);
        
        this.hideError();
        this.loadVideo();
    }
    
    showLoading() {
        const loadingElement = document.getElementById('video-loading');
        if (loadingElement) {
            loadingElement.classList.remove('hidden');
        }
    }
    
    hideLoading() {
        const loadingElement = document.getElementById('video-loading');
        if (loadingElement) {
            loadingElement.classList.add('hidden');
        }
    }
    
    showError() {
        const errorElement = document.getElementById('video-error');
        if (errorElement) {
            errorElement.classList.remove('hidden');
        }
    }
    
    hideError() {
        const errorElement = document.getElementById('video-error');
        if (errorElement) {
            errorElement.classList.add('hidden');
        }
    }
    
    showFallback() {
        this.hideError();
        const fallbackElement = document.getElementById('video-fallback');
        if (fallbackElement) {
            fallbackElement.classList.remove('hidden');
            // 更新题目编号
            fallbackElement.querySelector('h4').textContent = `题目 ${this.currentQuestionIndex}`;
        }
    }
    
    hideFallback() {
        const fallbackElement = document.getElementById('video-fallback');
        if (fallbackElement) {
            fallbackElement.classList.add('hidden');
        }
    }
    
    updateStatus(status) {
        const statusElement = document.getElementById('video-status-text');
        if (statusElement) {
            statusElement.textContent = status;
        }
    }
    
    updateProgress() {
        if (this.videoElement.duration && this.videoElement.currentTime) {
            const progress = (this.videoElement.currentTime / this.videoElement.duration) * 100;
            const progressBar = document.getElementById('video-progress-bar');
            if (progressBar) {
                progressBar.style.width = `${progress}%`;
            }
        }
    }
    
    // 公共方法
    play() {
        if (this.videoElement && this.videoElement.readyState >= 2) {
            return this.videoElement.play();
        }
        return Promise.reject('视频未就绪');
    }
    
    pause() {
        if (this.videoElement) {
            this.videoElement.pause();
        }
    }
    
    getCurrentTime() {
        return this.videoElement ? this.videoElement.currentTime : 0;
    }
    
    getDuration() {
        return this.videoElement ? this.videoElement.duration : 0;
    }
    
    isPlaying() {
        return this.videoElement && !this.videoElement.paused && !this.videoElement.ended;
    }
}

// CSS样式
const videoPlayerCSS = `
<style>
.enhanced-video-player {
    position: relative;
    background: #f8fafc;
    border-radius: 12px;
    overflow: hidden;
}

.video-wrapper {
    position: relative;
    background: #000;
    border-radius: 8px;
    overflow: hidden;
}

.video-loading {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.8);
    color: white;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    z-index: 10;
}

.loading-spinner {
    width: 40px;
    height: 40px;
    border: 4px solid #ffffff33;
    border-top: 4px solid #ffffff;
    border-radius: 50%;
    animation: spin 1s linear infinite;
    margin-bottom: 16px;
}

@keyframes spin {
    0% { transform: rotate(0deg); }
    100% { transform: rotate(360deg); }
}

.video-error {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: #fef2f2;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 24px;
    text-align: center;
    z-index: 10;
}

.error-icon {
    font-size: 48px;
    margin-bottom: 16px;
}

.error-content h4 {
    color: #dc2626;
    font-size: 18px;
    font-weight: 600;
    margin-bottom: 8px;
}

.error-content p {
    color: #7f1d1d;
    margin-bottom: 16px;
}

.error-actions {
    display: flex;
    gap: 12px;
    flex-wrap: wrap;
    justify-content: center;
}

.retry-btn, .skip-btn {
    padding: 8px 16px;
    border: none;
    border-radius: 6px;
    font-size: 14px;
    cursor: pointer;
    transition: all 0.2s;
}

.retry-btn {
    background: #dc2626;
    color: white;
}

.retry-btn:hover {
    background: #b91c1c;
}

.skip-btn {
    background: #6b7280;
    color: white;
}

.skip-btn:hover {
    background: #4b5563;
}

.video-fallback {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 24px;
    text-align: center;
    z-index: 10;
}

.fallback-icon {
    font-size: 48px;
    margin-bottom: 16px;
}

.fallback-content h4 {
    font-size: 20px;
    font-weight: 600;
    margin-bottom: 8px;
}

.fallback-content p {
    margin-bottom: 8px;
    opacity: 0.9;
}

.video-info {
    padding: 12px 16px;
    background: white;
    border-top: 1px solid #e5e7eb;
}

.video-status {
    display: flex;
    align-items: center;
    justify-content: space-between;
    font-size: 14px;
    color: #6b7280;
}

.video-progress {
    width: 60px;
    height: 4px;
    background: #e5e7eb;
    border-radius: 2px;
    overflow: hidden;
}

.progress-bar {
    height: 100%;
    background: #3b82f6;
    width: 0%;
    transition: width 0.3s ease;
}

.hidden {
    display: none !important;
}
</style>
`;

// 注入样式
if (!document.getElementById('enhanced-video-player-styles')) {
    const styleElement = document.createElement('div');
    styleElement.id = 'enhanced-video-player-styles';
    styleElement.innerHTML = videoPlayerCSS;
    document.head.appendChild(styleElement);
}

// 全局访问
window.EnhancedVideoPlayer = EnhancedVideoPlayer;
