from flask import Flask, request, session, redirect

def auth():
    # 静态文件直接放行
    if request.path.startswith('/static'):
        return

    # 登录和注册页面直接放行
    if request.path in ['/login', '/register']:
        return

    # 检查用户会话
    userinfo = session.get("userinfo")

    # 如果没有用户信息，重定向到登录页
    if not userinfo:
        return redirect('/login')

def create_app():
    app = Flask(__name__)
    app.secret_key = 'aaaaaaaaaa'

    app.before_request(auth)

    from .views import account
    app.register_blueprint(account.ac)

    from .views import test
    app.register_blueprint(test.ts)

    from .views import main
    app.register_blueprint(main.mi)

    return app