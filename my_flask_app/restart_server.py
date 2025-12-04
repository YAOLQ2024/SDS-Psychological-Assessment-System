#!/usr/bin/env python3
"""完整的服务器重启脚本 - 清理缓存并验证"""

import os
import sys
import shutil
import datetime

print("\n" + "=" * 70)
print("Flask 服务器完整重启工具")
print("=" * 70)

# 1. 清理 Python 缓存
print("\n【步骤 1】清理 Python 缓存文件...")

cache_dirs = []
pyc_files = []

for root, dirs, files in os.walk('.'):
    # 清理 __pycache__ 目录
    if '__pycache__' in dirs:
        cache_path = os.path.join(root, '__pycache__')
        cache_dirs.append(cache_path)
    
    # 清理 .pyc 文件
    for file in files:
        if file.endswith('.pyc'):
            pyc_path = os.path.join(root, file)
            pyc_files.append(pyc_path)

print(f"  找到 {len(cache_dirs)} 个 __pycache__ 目录")
print(f"  找到 {len(pyc_files)} 个 .pyc 文件")

if cache_dirs or pyc_files:
    confirm = input("  确认删除这些缓存？(Y/n): ").strip().lower()
    if confirm in ['', 'y', 'yes']:
        for cache_dir in cache_dirs:
            try:
                shutil.rmtree(cache_dir)
                print(f"    ✓ 删除: {cache_dir}")
            except Exception as e:
                print(f"    ✗ 错误: {cache_dir} - {e}")
        
        for pyc_file in pyc_files:
            try:
                os.remove(pyc_file)
                print(f"    ✓ 删除: {pyc_file}")
            except Exception as e:
                print(f"    ✗ 错误: {pyc_file} - {e}")
        
        print(f"\n  ✓ 缓存清理完成！")
    else:
        print("  跳过缓存清理")
else:
    print("  ✓ 没有缓存需要清理")

# 2. 验证时间函数
print("\n【步骤 2】验证时间函数...")
current_time = datetime.datetime.now()
print(f"  当前系统时间: {current_time}")
print(f"  这应该是您当前的北京时间")

# 3. 提示如何启动服务器
print("\n【步骤 3】重启服务器")
print("  请按照以下步骤操作:")
print("  1. 确保旧的服务器进程已经停止（Ctrl+C）")
print("  2. 运行: python app.py")
print("  3. 等待服务器启动完成")
print("  4. 查看终端输出，应该看到:")
print("     '✓✓✓ test.py 模块已重新加载 - get_beijing_time() 函数已更新！✓✓✓'")
print(f"     '当前系统时间: {current_time.strftime('%Y-%m-%d %H:%M')}'")

print("\n【步骤 4】测试验证")
print("  1. 访问测评页面并完成一次测评")
print("  2. 查看终端输出，应该看到:")
print("     '!!! GET_BEIJING_TIME 被调用 !!!'")
print(f"     '返回时间: {current_time.strftime('%Y-%m-%d %H:%M')}'")
print("  3. 如果时间仍然错误，说明存在其他问题，请截图终端输出")

print("\n" + "=" * 70)
print("准备就绪！现在请启动服务器：python app.py")
print("=" * 70 + "\n")

