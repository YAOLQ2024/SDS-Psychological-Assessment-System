from flask import Blueprint, render_template, request, redirect, url_for, session
from utils import db

#蓝图对象
ac = Blueprint("account", __name__)


@ac.route('/login', methods=["GET", "POST", "HEAD"])
def login():
    if request.method == "GET" or request.method == "HEAD":
        return render_template("login.html")

    account = request.form.get("account")
    password = request.form.get("password")

    # 检查account和password是否存在
    if not account or not password:
        return render_template("login.html", error="账户或密码不能为空")

    # 若只包含数字，且长度在11位，则判定为电话号码
    if account and account.isdigit() and len(account) == 11:
        userinfo = db.fetch_one("select * from userinfo where mobile=? and password=?", [account, password])
    else:
    # 若包含字母或其他特殊字符，判定为用户名
        userinfo = db.fetch_one("select * from userinfo where name=? and password=?", [account, password])

    if userinfo:
        session["userinfo"] = userinfo
        # 登录成功 + 跳转
        return redirect('/main')

    return render_template("login.html", error="账户或密码错误")


@ac.route('/register', methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")

    name = request.form.get("name")
    mobile = request.form.get("mobile")
    password = request.form.get("password")
    password2 = request.form.get("password2")

    if password2 != password:
        return render_template("register.html", error="两次密码不相同")

    if db.fetch_one("select * from userinfo where name=?", [name]):
        return render_template("register.html", error="该用户名已被使用")

    if db.fetch_one("select * from userinfo where mobile=?", [mobile]):
        return render_template("register.html", error="该手机号已注册，请点击登录")

    db.insert("INSERT INTO userinfo (name, mobile, password) VALUES (?, ?, ?)", [name, mobile, password])

    return redirect('/login')
