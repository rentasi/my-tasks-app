import json
import os
from datetime import datetime
from flask import Flask, request, redirect, render_template, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

app.secret_key = os.environ.get("SECRET_KEY", "yokohama-dev-key-default-12345") 

basedir = os.path.abspath(os.path.dirname(__file__))
instance_path = os.path.join(basedir, 'instance')

if not os.path.exists(instance_path):
    os.makedirs(instance_path)
# 2. データベースの設定（tasks.db というファイルに保存されます）
db_path = os.path.join(basedir, 'instance', 'tasks.db')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + db_path
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# 3. データの設計図（モデル）を作成
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False) # 名前（重複NG）
    password_hash = db.Column(db.String(200), nullable=False)        # 暗号化されたパスワード
    # そのユーザーが持っているタスクを紐付ける
    tasks = db.relationship('Task', backref='author', lazy=True)

class Follow(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    follower_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False) # フォローした人
    followed_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False) # フォローされた人

# 2. グループ（コミュニティ）を管理するテーブル
class Group(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False) # グループ名（例：起業部）
    description = db.Column(db.String(200)) # 説明文

# 3. 既存の Task モデルに「どのグループの投稿か」を記録する列を追加
class Task(db.Model):
    # ...（既存の列はそのまま）...
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=True) # どのグループ用か（空でもOK） 

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False) # コメント本文
    task_id = db.Column(db.Integer, db.ForeignKey('task.id'), nullable=False) # どのタスクへのコメントか
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False) # 誰が書いたか
    created_at = db.Column(db.String(10), default=lambda: datetime.now().strftime("%H:%M"))
    
    # コメントを書いた人の情報を簡単に取れるようにする（リレーション）
    user = db.relationship('User', backref='comments')

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)  # ID（自動で割り振られる番号）
    name = db.Column(db.String(100), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False) # ユーザーIDで紐付け
    done = db.Column(db.Boolean, default=False)
    date = db.Column(db.String(20))
    likes_json = db.Column(db.Text, default="[]") # 応援した人のリストを文字列として保存
    created_at = db.Column(db.String(10), default=lambda: datetime.now().strftime("%H:%M"))
    comments = db.relationship('Comment', backref='task', lazy=True, cascade="all, delete-orphan")

    # 応援リスト（JSON文字列）をリストとして扱うための便利な仕組み
    @property
    def likes(self):
        return json.loads(self.likes_json)
    
    @likes.setter
    def likes(self, value):
        self.likes_json = json.dumps(value)

# 初回実行時にデータベースファイルを作成する魔法
with app.app_context():
    db.create_all()

@app.route("/", methods=["GET", "POST"])
def index():
    if "user_name" not in session:
        return redirect("/login")

    if request.method == "POST":
        action = request.form.get("action")
        # 各ボタンに紐づくIDを取得
        task_id = request.form.get("task_id", type=int)
        task = Task.query.get(task_id) if task_id else None

        if action == "add":
            new_name = request.form.get("task_name")
            new_date = request.form.get("task_date") or None
            if new_name:
                new_task = Task(name=new_name, user_id=session["user_id"], date=new_date)
                db.session.add(new_task)
        
        elif action == "toggle" and task:
            task.done = not task.done
        
        elif action == "delete" and task:
            db.session.delete(task)

        elif action == "update" and task:
            task.name = request.form.get("task_name")
            task.date = request.form.get("task_date") or None
            task.user_id = session["user_id"]

        elif action == "like" and task:
            my_name = session["user_name"]
            current_likes = task.likes
            if my_name in current_likes:
                current_likes.remove(my_name)
            else:
                current_likes.append(my_name)
            task.likes = current_likes # Setterが動いてJSONに変換される

        elif action == "comment":
            content = request.form.get("content")
            if content and task: # contentが空でなく、taskが存在すれば保存
                new_comment = Comment(
                    content=content, 
                    task_id=task.id, 
                    user_id=session["user_id"]
                )
                db.session.add(new_comment)

        elif action == "clear_done":
            Task.query.filter_by(done=True).delete()

        db.session.commit() # 5. 最後にまとめて変更を確定（保存）！
        return redirect("/")
    
    my_id = session["user_id"]

    # URLから「どのタブを表示するか」を取得（デフォルトは 'timeline'）
    current_tab = request.args.get('tab', 'timeline')

    if current_tab == 'mine':
        # ① 自分だけ
        tasks = Task.query.filter_by(user_id=my_id).order_by(Task.id.desc()).all()

    elif current_tab == 'group':
        # ② グループ（自分が所属しているグループのタスク）
        # ※ 今は簡単のため「group_id が設定されているもの全部」にします
        tasks = Task.query.filter(Task.group_id != None).order_by(Task.id.desc()).all()

    else: # 'timeline'（自分 ＋ フォローしている人）
        # 1. 自分がフォローしている人のIDリストを取得
        following_list = Follow.query.filter_by(follower_id=my_id).all()
        following_ids = [f.followed_id for f in following_list]
        
        # 2. 「自分のID」と「フォロー中のID」を合体させる
        target_ids = following_ids + [my_id]
        
        # 3. そのリストに含まれる人のタスクだけを取得（これがBeReal風！）
        tasks = Task.query.filter(Task.user_id.in_(target_ids)).order_by(Task.id.desc()).all()

    return render_template("index.html", tasks=tasks, current_tab=current_tab)

    # 1. URLから「誰のタスクを表示するか」のIDを取得
    filter_user_id = request.args.get('user_id', type=int)
    filter_user = None

    # 2. データの取得開始
    if filter_user_id:
        # 3. 絞り込み中のユーザー名を取得（画面表示用）
        filter_user = User.query.get(filter_user_id)
        # 特定のユーザーで絞り込み ＋ IDの大きい順（新着順）
        tasks = Task.query.filter_by(user_id=filter_user_id).order_by(Task.id.desc()).all()
    else:
        # 全員のタスク ＋ IDの大きい順（新着順）
        tasks = Task.query.order_by(Task.id.desc()).all()

    today = datetime.now().strftime("%Y-%m-%d")
    
    # 編集中のタスクIDを取得
    edit_id = request.args.get("edit", type=int)
    edit_task = Task.query.get(edit_id) if edit_id else None

    return render_template("index.html", 
                           tasks=tasks, 
                           today=today, 
                           edit_task=edit_task,
                           filter_user=filter_user,
                           user_name=session["user_name"],
                           total_count=len(tasks),
                           todo_count=len([t for t in tasks if not t.done]))

# login, logout, app.run は変更なし

# 5. ログイン画面のルートを新設
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user_name = request.form.get("user_name")
        password = request.form.get("password") # パスワードを取得
        
        # データベースからユーザーを探す
        user = User.query.filter_by(username=user_name).first()
        
        # ユーザーが存在し、かつパスワードが正しいかチェック
        if user and check_password_hash(user.password_hash, password):
            session["user_name"] = user.username
            session["user_id"] = user.id  # これを保存しないと投稿でエラーになります！
            return redirect("/")
        else:
            return render_template("login.html", error="ユーザー名またはパスワードが違います")
            
    return render_template("login.html")

# 6. ログアウト（名前を忘れる）機能もおまけ
@app.route("/logout")
def logout():
    session.pop("user_name", None)
    return redirect("/login")

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form.get("user_name")
        password = request.form.get("password")
        
        # すでに同じ名前の人がいないかチェック
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            return "その名前はすでに使われています" # 本来はもっと丁寧にエラーを出します

        # パスワードを暗号化して保存！
        hashed_pw = generate_password_hash(password)
        new_user = User(username=username, password_hash=hashed_pw)
        db.session.add(new_user)
        db.session.commit()
        
        return redirect("/login") # 登録できたらログイン画面へ
    return render_template("signup.html")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)