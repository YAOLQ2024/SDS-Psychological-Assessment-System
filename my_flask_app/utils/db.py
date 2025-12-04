import sqlite3
import os

# SQLite数据库文件路径
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'depression.db')

# 初始化数据库连接
def get_connection():
    return sqlite3.connect(DB_PATH)

# 初始化数据库表
def init_database():
    conn = get_connection()
    cursor = conn.cursor()
    
    # 创建userinfo表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS userinfo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(255),
            mobile VARCHAR(255),
            password VARCHAR(255),
            email VARCHAR(255),
            real_name VARCHAR(255),
            sex VARCHAR(255),
            number VARCHAR(255),
            history VARCHAR(255),
            role INTEGER DEFAULT 1
        )
    ''')
    
    # 创建test表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS test (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role INTEGER DEFAULT 1,
            choose VARCHAR(24) DEFAULT '000000000000000000000000',
            score INTEGER DEFAULT 0,
            user_id INTEGER NOT NULL DEFAULT 1,
            start_time DATETIME,
            finish_time DATETIME,
            use_time INTEGER,
            status VARCHAR(25),
            result VARCHAR(10),
            emotion_data TEXT,
            comprehensive_score REAL,
            comprehensive_result TEXT,
            FOREIGN KEY (user_id) REFERENCES userinfo (id)
        )
    ''')
    
    # 插入默认用户数据
    cursor.execute('''
        INSERT OR IGNORE INTO userinfo (id, name, mobile, password, email, real_name, sex, number, history, role) 
        VALUES (1, 'DSH', '1', '1', '123', '1234', '男', '123', '轻度抑郁', 1)
    ''')
    
    conn.commit()
    conn.close()

def fetch_one(sql, params):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(sql, params)
    result = cursor.fetchone()
    
    # 将结果转换为字典格式
    if result:
        columns = [description[0] for description in cursor.description]
        result = dict(zip(columns, result))
    
    cursor.close()
    conn.close()
    return result

def fetch_all(sql, params):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(sql, params)
    results = cursor.fetchall()
    
    # 将结果转换为字典格式
    if results:
        columns = [description[0] for description in cursor.description]
        results = [dict(zip(columns, row)) for row in results]
    
    cursor.close()
    conn.close()
    return results

def insert(sql, params):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(sql, params)
    lastrowid = cursor.lastrowid  # 获取自增ID
    conn.commit()

    cursor.close()
    conn.close()

    return lastrowid

def update(sql, params):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(sql, params)
    affected_rows = cursor.rowcount  # 获取受影响的行数
    conn.commit()

    cursor.close()
    conn.close()
    
    return affected_rows  # 返回受影响的行数

def migrate_database():
    """数据库迁移：为test表添加新字段（如果不存在）"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # 检查并添加emotion_data列
    try:
        cursor.execute("SELECT emotion_data FROM test LIMIT 1")
    except sqlite3.OperationalError:
        print("添加emotion_data列到test表...")
        cursor.execute("ALTER TABLE test ADD COLUMN emotion_data TEXT")
        conn.commit()
    
    # 检查并添加comprehensive_score列
    try:
        cursor.execute("SELECT comprehensive_score FROM test LIMIT 1")
    except sqlite3.OperationalError:
        print("添加comprehensive_score列到test表...")
        cursor.execute("ALTER TABLE test ADD COLUMN comprehensive_score REAL")
        conn.commit()
    
    # 检查并添加comprehensive_result列
    try:
        cursor.execute("SELECT comprehensive_result FROM test LIMIT 1")
    except sqlite3.OperationalError:
        print("添加comprehensive_result列到test表...")
        cursor.execute("ALTER TABLE test ADD COLUMN comprehensive_result TEXT")
        conn.commit()
    
    cursor.close()
    conn.close()
    print("数据库迁移完成！")
