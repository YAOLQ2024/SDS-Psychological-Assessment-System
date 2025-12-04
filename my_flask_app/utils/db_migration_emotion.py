# -*- coding: utf-8 -*-
"""
数据库迁移脚本 - 添加表情识别相关字段
"""

import sqlite3
import os
import sys

def migrate_database():
    """为数据库添加表情识别相关字段"""
    
    db_path = "/home/HwHiAiUser/dsh_抑郁症2/my_flask_app/depression.db"
    
    if not os.path.exists(db_path):
        print(f"数据库文件不存在: {db_path}")
        return False
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        print("开始数据库迁移...")
        
        # 检查是否已经存在emotion_data字段
        cursor.execute("PRAGMA table_info(test)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'emotion_data' not in columns:
            # 添加emotion_data字段来存储表情数据
            cursor.execute("""
                ALTER TABLE test 
                ADD COLUMN emotion_data TEXT
            """)
            print("✓ 添加emotion_data字段成功")
        else:
            print("emotion_data字段已存在，跳过")
            
        # 检查并添加综合评分相关字段
        if 'comprehensive_score' not in columns:
            cursor.execute("""
                ALTER TABLE test 
                ADD COLUMN comprehensive_score REAL
            """)
            print("✓ 添加comprehensive_score字段成功")
        else:
            print("comprehensive_score字段已存在，跳过")
            
        if 'comprehensive_result' not in columns:
            cursor.execute("""
                ALTER TABLE test 
                ADD COLUMN comprehensive_result TEXT
            """)
            print("✓ 添加comprehensive_result字段成功")
        else:
            print("comprehensive_result字段已存在，跳过")
        
        # 创建表情统计表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS emotion_statistics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                test_id INTEGER,
                emotion_type TEXT NOT NULL,
                emotion_chinese TEXT NOT NULL,
                confidence REAL,
                detection_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                question_number INTEGER,
                bbox_x INTEGER,
                bbox_y INTEGER,
                bbox_width INTEGER,
                bbox_height INTEGER,
                FOREIGN KEY (test_id) REFERENCES test (id)
            )
        """)
        print("✓ 创建emotion_statistics表成功")
        
        # 提交更改
        conn.commit()
        print("✓ 数据库迁移完成")
        
        return True
        
    except sqlite3.Error as e:
        print(f"数据库迁移失败: {e}")
        return False
        
    finally:
        if conn:
            conn.close()

def check_database_structure():
    """检查数据库结构"""
    
    db_path = "/home/HwHiAiUser/dsh_抑郁症2/my_flask_app/depression.db"
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        print("当前数据库结构:")
        print("-" * 50)
        
        # 检查test表结构
        cursor.execute("PRAGMA table_info(test)")
        test_columns = cursor.fetchall()
        print("test表字段:")
        for column in test_columns:
            print(f"  {column[1]} - {column[2]}")
        
        print()
        
        # 检查emotion_statistics表结构
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='emotion_statistics'
        """)
        if cursor.fetchone():
            cursor.execute("PRAGMA table_info(emotion_statistics)")
            emotion_columns = cursor.fetchall()
            print("emotion_statistics表字段:")
            for column in emotion_columns:
                print(f"  {column[1]} - {column[2]}")
        else:
            print("emotion_statistics表不存在")
        
    except sqlite3.Error as e:
        print(f"检查数据库结构失败: {e}")
        
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    print("=" * 60)
    print("表情识别数据库迁移工具")
    print("=" * 60)
    
    # 检查当前数据库结构
    check_database_structure()
    
    print("\n开始数据库迁移...")
    if migrate_database():
        print("\n迁移完成，检查新的数据库结构:")
        check_database_structure()
    else:
        print("\n迁移失败")
