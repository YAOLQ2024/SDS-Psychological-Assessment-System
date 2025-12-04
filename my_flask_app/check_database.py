#!/usr/bin/env python3
"""数据库诊断脚本 - 检查 test 表的结构和数据"""

import sqlite3
import os
import sys

# 数据库路径
DB_PATH = os.path.join(os.path.dirname(__file__), 'depression.db')

def check_database():
    print("=" * 60)
    print("数据库诊断工具")
    print("=" * 60)
    print(f"\n数据库文件路径: {DB_PATH}")
    
    if not os.path.exists(DB_PATH):
        print("✗ 错误：数据库文件不存在！")
        return
    
    print(f"✓ 数据库文件存在，大小: {os.path.getsize(DB_PATH)} 字节")
    
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # 1. 检查 test 表结构
        print("\n" + "=" * 60)
        print("1. TEST 表结构")
        print("=" * 60)
        cursor.execute("PRAGMA table_info(test)")
        columns = cursor.fetchall()
        
        if not columns:
            print("✗ 错误：test 表不存在！")
            return
        
        print("\n表字段列表:")
        required_fields = ['emotion_data', 'comprehensive_score', 'comprehensive_result']
        existing_fields = []
        
        for col in columns:
            col_id, name, type_, not_null, default, pk = col
            print(f"  {col_id:2d}. {name:25s} {type_:15s} {'NOT NULL' if not_null else ''} {'PRIMARY KEY' if pk else ''}")
            existing_fields.append(name)
        
        print("\n新字段检查:")
        for field in required_fields:
            if field in existing_fields:
                print(f"  ✓ {field} - 存在")
            else:
                print(f"  ✗ {field} - 缺失")
        
        # 2. 检查记录总数
        print("\n" + "=" * 60)
        print("2. 数据统计")
        print("=" * 60)
        
        cursor.execute("SELECT COUNT(*) FROM test")
        total_count = cursor.fetchone()[0]
        print(f"\n总记录数: {total_count}")
        
        cursor.execute("SELECT COUNT(*) FROM test WHERE status='已完成'")
        completed_count = cursor.fetchone()[0]
        print(f"已完成记录数: {completed_count}")
        
        cursor.execute("SELECT COUNT(*) FROM test WHERE status='未完成' OR status IS NULL")
        incomplete_count = cursor.fetchone()[0]
        print(f"未完成记录数: {incomplete_count}")
        
        # 3. 显示最近的记录
        print("\n" + "=" * 60)
        print("3. 最近 5 条记录")
        print("=" * 60)
        
        cursor.execute("""
            SELECT id, user_id, status, result, score, 
                   comprehensive_score, start_time, finish_time
            FROM test 
            ORDER BY id DESC 
            LIMIT 5
        """)
        
        recent_records = cursor.fetchall()
        
        if not recent_records:
            print("\n✗ 没有找到任何记录")
        else:
            print("\n")
            print(f"{'ID':<6} {'用户ID':<8} {'状态':<10} {'结果':<12} {'分数':<6} {'综合分数':<10} {'开始时间':<20} {'完成时间':<20}")
            print("-" * 120)
            for record in recent_records:
                id_, user_id, status, result, score, comp_score, start_time, finish_time = record
                print(f"{id_:<6} {user_id:<8} {status or 'NULL':<10} {result or 'NULL':<12} "
                      f"{score or 0:<6} {comp_score or 0:<10.1f} "
                      f"{str(start_time)[:19]:<20} {str(finish_time or 'NULL')[:19]:<20}")
        
        # 4. 检查所有用户
        print("\n" + "=" * 60)
        print("4. 用户测评统计")
        print("=" * 60)
        
        cursor.execute("""
            SELECT u.id, u.name, 
                   COUNT(t.id) as total_tests,
                   SUM(CASE WHEN t.status='已完成' THEN 1 ELSE 0 END) as completed_tests
            FROM userinfo u
            LEFT JOIN test t ON u.id = t.user_id
            GROUP BY u.id, u.name
        """)
        
        user_stats = cursor.fetchall()
        
        print("\n")
        print(f"{'用户ID':<10} {'用户名':<20} {'总测评数':<12} {'已完成数':<12}")
        print("-" * 60)
        for stat in user_stats:
            user_id, name, total, completed = stat
            print(f"{user_id:<10} {name:<20} {total:<12} {completed:<12}")
        
        cursor.close()
        conn.close()
        
        print("\n" + "=" * 60)
        print("诊断完成")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n✗ 错误: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    check_database()

