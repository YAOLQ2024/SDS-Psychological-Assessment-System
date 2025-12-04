from flask import Blueprint, request, render_template, session, redirect, make_response
from utils import db
import datetime
import json
from datetime import timezone, timedelta

def get_beijing_time():
    """获取北京时间 - 直接使用系统时间（系统已配置为UTC+8）"""
    # 系统本地时间已经是北京时间，直接返回
    return datetime.datetime.now()

def parse_datetime(dt_str):
    """解析datetime字符串为datetime对象"""
    if isinstance(dt_str, str):
        return datetime.datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
    return dt_str

#蓝图对象
mi = Blueprint("main", __name__)

sds_questions = [
    "我觉得闷闷不乐，情绪低沉",
    "我觉得一天之中早晨最好",
    "我一阵阵哭出来或觉得想哭",
    "我晚上睡眠不好",
    "我吃得跟平常一样多",
    "我与异性密切接触时和以往一样感到愉快",
    "我发觉我的体重在下降",
    "我有便秘的苦恼",
    "我心跳比平常快",
    "我无缘无故地感到疲乏",
    "我的头脑跟平常一样清楚",
    "我觉得经常做的事情并没有困难",
    "我觉得不安而平静不下来",
    "我对将来抱有希望",
    "我比平常容易生气激动",
    "我觉得作出决定是容易的",
    "我觉得自己是个有用的人，有人需要我",
    "我的生活过得很有意思",
    "我认为如果我死了别人会生活得好些",
    "平常感兴趣的事我仍然照样感兴趣"
]


def calculate_total_time(records):
    total_seconds = sum(record['use_time'] for record in records)

    if total_seconds < 60:
        return f"{total_seconds} 秒"
    elif total_seconds < 3600:
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        return f"{minutes} 分钟"
    elif total_seconds < 86400:
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        return f"{hours} 小时"
    else:
        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        return f"{days} 天"

@mi.route('/main', methods=["GET"])
def main():
    # 读取cookies
    userinfo = session.get("userinfo")

    role = userinfo['role']
    if role == 2:
        test_list = db.fetch_all("select * from test", [])
    else:
        test_list = db.fetch_all("select * from test where user_id=?", [userinfo['id']])

    # 过滤掉result为None的数据
    filtered_list  = [item for item in test_list if item.get('result') is not None]
    sorted_list = sorted(filtered_list , key=lambda x: x['finish_time'], reverse=True)

    if len(sorted_list) == 0:
        status = "未测评"
        count_inmonth = 0
        delta = 0
    else:
        current_time = get_beijing_time()
        last_month = current_time - datetime.timedelta(days=30)

        # 转换finish_time为datetime对象进行比较
        count_inmonth = sum(1 for item in sorted_list if parse_datetime(item['finish_time']) >= last_month)

        latest_time = parse_datetime(sorted_list[0]['finish_time'])

        delta = (current_time - latest_time).days if (current_time - latest_time).days >= 0 else 0

        status = sorted_list[0]["result"]

    return render_template("main.html", status = status, count_inmonth = count_inmonth, delta = delta, userinfo = userinfo)


@mi.route('/history/debug', methods=["GET"])
def history_debug():
    """调试页面：显示原始数据库记录"""
    userinfo = session.get("userinfo")
    if not userinfo:
        return redirect('/login')
    
    role = userinfo['role']
    if role == 2:
        test_list = db.fetch_all("select * from test ORDER BY id DESC LIMIT 50", [])
    else:
        test_list = db.fetch_all("select * from test where user_id=? ORDER BY id DESC LIMIT 50", [userinfo['id']])
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>历史记录调试</title>
        <style>
            body {{ font-family: monospace; padding: 20px; background: #0a0a0a; color: #0f0; }}
            table {{ border-collapse: collapse; width: 100%; background: #1a1a1a; }}
            th, td {{ border: 1px solid #0f0; padding: 8px; text-align: left; }}
            th {{ background: #2a2a2a; }}
            .completed {{ color: #0f0; }}
            .incomplete {{ color: #666; }}
            h1 {{ color: #0ff; }}
            a {{ color: #0ff; text-decoration: none; }}
            a:hover {{ text-decoration: underline; }}
        </style>
    </head>
    <body>
        <h1>📊 数据库记录调试页面</h1>
        <p>用户: {userinfo['name']} (ID: {userinfo['id']})</p>
        <p>总记录数: {len(test_list)}</p>
        <p><a href="/history">← 返回正常历史页面</a></p>
        <hr>
        <table>
            <tr>
                <th>ID</th>
                <th>状态</th>
                <th>结果</th>
                <th>分数</th>
                <th>综合分数</th>
                <th>开始时间</th>
                <th>完成时间</th>
                <th>用时(秒)</th>
                <th>有综合结果</th>
            </tr>
    """
    
    for item in test_list:
        status_class = 'completed' if item.get('status') == '已完成' else 'incomplete'
        has_comp = '✓' if item.get('comprehensive_result') else '✗'
        html += f"""
            <tr class="{status_class}">
                <td>{item.get('id')}</td>
                <td>{item.get('status') or 'NULL'}</td>
                <td>{item.get('result') or 'NULL'}</td>
                <td>{item.get('score') or 0}</td>
                <td>{item.get('comprehensive_score') or 0}</td>
                <td>{str(item.get('start_time') or '')[:19]}</td>
                <td>{str(item.get('finish_time') or 'NULL')[:19]}</td>
                <td>{item.get('use_time') or 0}</td>
                <td>{has_comp}</td>
            </tr>
        """
    
    html += """
        </table>
    </body>
    </html>
    """
    
    return html

@mi.route('/history', methods=["GET", "POST"])
def history():
    userinfo = session.get("userinfo")

    role = userinfo['role']
    if role == 2:
        test_list = db.fetch_all("select * from test", [])
    else:
        test_list = db.fetch_all("select * from test where user_id=?", [userinfo['id']])

    print(f"查询历史记录 - 用户: {userinfo.get('name')}, user_id: {userinfo.get('id')}")
    print(f"  总记录数: {len(test_list) if test_list else 0}")
    
    if test_list:
        for idx, item in enumerate(test_list):
            print(f"  记录 {idx+1}: id={item.get('id')}, status={item.get('status')}, result={item.get('result')}, score={item.get('score')}, finish_time={item.get('finish_time')}")

    # 过滤掉result为None的数据
    filtered_list = [item for item in test_list if item.get('status') == '已完成']
    print(f"  已完成记录数: {len(filtered_list)}")
    
    # 按 id 降序排序（id 越大越新，最可靠）
    sorted_list = sorted(filtered_list, key=lambda x: x['id'], reverse=True)
    
    if sorted_list:
        print(f"  排序后前5条记录:")
        for i, item in enumerate(sorted_list[:5]):
            print(f"    {i+1}. id={item.get('id')}, finish_time={item.get('finish_time')}, result={item.get('result')}")

    if len(sorted_list) == 0:
        status = "未测评"
        all_times = 0
        delta = 0
        total_time_str = "0 分钟"
    else:
        all_times = len(sorted_list)
        status = sorted_list[0]["result"]
        latest_time = parse_datetime(sorted_list[0]['finish_time'])
        current_time = get_beijing_time()
        delta = (current_time - latest_time).days if (current_time - latest_time).days >= 0 else 0
        # 计算并打印总时间
        total_time_str = calculate_total_time(sorted_list)

        for item in sorted_list:
            item['finish_time'] = parse_datetime(item['finish_time']).strftime('%Y-%m-%d %H:%M')

    print(f"\n✓ 准备渲染 history.html:")
    print(f"  - sorted_list 长度: {len(sorted_list)}")
    print(f"  - all_times: {all_times}")
    print(f"  - status: {status}")
    if sorted_list:
        print(f"  - 最新记录（前3条）:")
        for i, item in enumerate(sorted_list[:3]):
            print(f"    {i+1}. id={item.get('id')}, result={item.get('result')}, score={item.get('score')}, time={item.get('finish_time')}")

    response = make_response(render_template("history.html", sorted_list = sorted_list, user_name = userinfo['name'],
                           all_times=all_times, status=status, delta=delta, total_time_str=total_time_str))
    
    # 防止浏览器缓存
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    
    return response

@mi.route('/detail', methods=["GET", "POST", "HEAD"])
def detail():
    # HEAD请求直接返回，不处理
    if request.method == "HEAD":
        return '', 200
    
    user_name = session.get("userinfo")['name']
    test_id = request.form.get("test_id") or request.args.get("test_id")
    
    # 检查test_id是否存在
    if not test_id:
        print(f"错误: detail路由未获取到test_id, method={request.method}, form={request.form}, args={request.args}")
        return redirect('/history')

    print(f"查询test记录: test_id={test_id}, type={type(test_id)}")
    test = db.fetch_one("select * from test where id=?", [test_id])
    
    # 检查test是否存在
    if not test:
        print(f"错误: 未找到test记录, test_id={test_id}")
        return redirect('/history')
    
    print(f"找到test记录: id={test.get('id')}, status={test.get('status')}, finish_time={test.get('finish_time')}")
    
    # 检查finish_time是否存在
    if test.get('finish_time'):
        test['finish_time'] = parse_datetime(test['finish_time']).strftime('%Y-%m-%d %H:%M')
    else:
        test['finish_time'] = '未完成'

    result = []
    # 检查test['choose']是否存在
    if test.get('choose'):
        for question, choice in zip(sds_questions, test['choose']):
            item = {
                'question': question,
                'choose': choice
            }
            result.append(item)
    print(result)

    return render_template("detail.html", test=test, result=result, user_name=user_name)

@mi.route('/comprehensive-detail', methods=["GET", "POST", "HEAD"])
def comprehensive_detail():
    """综合评分详情页面"""
    # HEAD请求直接返回，不处理
    if request.method == "HEAD":
        return '', 200
    
    user_name = session.get("userinfo")['name']
    
    # 支持GET和POST两种方式获取test_id
    if request.method == "GET":
        test_id = request.args.get("test_id")
    else:
        test_id = request.form.get("test_id")
    
    # 检查test_id是否存在
    if not test_id:
        print(f"错误: comprehensive-detail路由未获取到test_id, method={request.method}")
        return redirect('/history')

    test = db.fetch_one("select * from test where id=?", [test_id])
    if not test:
        print(f"错误: 未找到test记录, test_id={test_id}")
        return redirect('/history')
    
    # 检查finish_time是否存在
    if test.get('finish_time'):
        test['finish_time'] = parse_datetime(test['finish_time']).strftime('%Y-%m-%d %H:%M')
    else:
        test['finish_time'] = '未完成'

    # 解析综合评分结果
    comprehensive_result = None
    emotion_data = None
    
    if test.get('comprehensive_result'):
        try:
            comprehensive_result = json.loads(test['comprehensive_result'])
        except:
            comprehensive_result = None
    
    if test.get('emotion_data'):
        try:
            emotion_data = json.loads(test['emotion_data'])
        except:
            emotion_data = None

    # 构建详细答题记录
    result = []
    for question, choice in zip(sds_questions, test['choose']):
        item = {
            'question': question,
            'choose': choice
        }
        result.append(item)

    return render_template("comprehensive_detail.html", 
                         test=test, 
                         result=result, 
                         user_name=user_name,
                         comprehensive_result=comprehensive_result,
                         emotion_data=emotion_data)


@mi.route('/submit_success.html', methods=["GET"])
def submit_success():
    """提交成功页面"""
    return render_template('submit_success.html')

@mi.route('/logout', methods=["GET", "POST"])
def logout():
    session.clear()

    return '1'