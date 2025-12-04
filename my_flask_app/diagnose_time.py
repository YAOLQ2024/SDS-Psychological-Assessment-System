#!/usr/bin/env python3
"""诊断时间问题 - 详细检查所有时间源"""

import datetime
from datetime import timedelta, timezone
import time
import os

print("=" * 70)
print("系统时间诊断工具")
print("=" * 70)

# 1. 系统时间
print("\n【1. 系统时间信息】")
local_time = datetime.datetime.now()
print(f"datetime.now():           {local_time}")

utc_time = datetime.datetime.utcnow()
print(f"datetime.utcnow():        {utc_time}")

# 使用 timezone-aware 的方式获取UTC时间
utc_aware = datetime.datetime.now(timezone.utc)
print(f"datetime.now(timezone.utc): {utc_aware}")

# 2. 时间戳
print("\n【2. Unix时间戳】")
timestamp = time.time()
print(f"time.time():              {timestamp}")
print(f"转换为datetime:          {datetime.datetime.fromtimestamp(timestamp)}")
print(f"转换为UTC datetime:      {datetime.datetime.utcfromtimestamp(timestamp)}")

# 3. 系统时区信息
print("\n【3. 系统环境变量】")
print(f"TZ环境变量:               {os.environ.get('TZ', '未设置')}")

# 4. 计算北京时间（多种方法）
print("\n【4. 北京时间计算（多种方法）】")

# 方法1: 基于 utcnow()
method1 = datetime.datetime.utcnow() + timedelta(hours=8)
print(f"方法1 (utcnow + 8h):     {method1}")

# 方法2: 基于 now(timezone.utc)
method2 = datetime.datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=8)
print(f"方法2 (now(utc) + 8h):   {method2}")

# 方法3: 直接使用北京时区
beijing_tz = timezone(timedelta(hours=8))
method3 = datetime.datetime.now(beijing_tz).replace(tzinfo=None)
print(f"方法3 (now(beijing_tz)): {method3}")

# 方法4: 基于时间戳
beijing_from_timestamp = datetime.datetime.fromtimestamp(timestamp) + timedelta(hours=8) - (datetime.datetime.now() - datetime.datetime.utcnow())
print(f"方法4 (timestamp修正):   {beijing_from_timestamp}")

# 5. 时差分析
print("\n【5. 时差分析】")
diff_local_utc = (local_time - utc_time).total_seconds() / 3600
print(f"本地时间 - UTC时间:      {diff_local_utc:.2f} 小时")

if abs(diff_local_utc - 8) < 0.1:
    print(f"  ✓ 您的系统本地时间已经是北京时间（UTC+8）")
    print(f"  → 可以直接使用 datetime.now()")
elif abs(diff_local_utc) < 0.1:
    print(f"  ✓ 您的系统本地时间是UTC时间")
    print(f"  → 需要使用 datetime.utcnow() + 8小时")
else:
    print(f"  ⚠ 您的系统本地时间是 UTC{diff_local_utc:+.1f}")
    print(f"  → 需要手动调整时差")

# 6. 推荐方案
print("\n【6. 推荐使用的时间函数】")
if abs(diff_local_utc - 8) < 0.1:
    print("def get_beijing_time():")
    print("    return datetime.datetime.now()  # 系统已经是北京时间")
    recommended = datetime.datetime.now()
else:
    print("def get_beijing_time():")
    print("    return datetime.datetime.utcnow() + timedelta(hours=8)")
    recommended = datetime.datetime.utcnow() + timedelta(hours=8)

print(f"\n推荐函数返回: {recommended}")

# 7. 当前真实时间确认
print("\n" + "=" * 70)
print("请确认以下哪个时间与您的真实北京时间一致：")
print("=" * 70)
print(f"A. datetime.now():        {datetime.datetime.now()}")
print(f"B. utcnow() + 8小时:      {datetime.datetime.utcnow() + timedelta(hours=8)}")
print(f"C. now(beijing_tz):       {datetime.datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None)}")
print("=" * 70)
print("如果都不对，请手动输入当前正确的北京时间（格式：2025-12-06 20:54）")
print("=" * 70)

