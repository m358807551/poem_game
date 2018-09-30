# coding=utf-8
import logging
import random
import json

from pypinyin import lazy_pinyin
from pypinyin.style._utils import get_finals
from flask import Flask, render_template, request, redirect
from flask_socketio import SocketIO, emit
from flask_login import LoginManager, UserMixin, login_required, login_user, current_user

logging.basicConfig(level=logging.DEBUG,
                    format="%(asctime)s %(name)-12s %(levelname)-8s %(message)s")

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'

socketio = SocketIO(app)
login_manager = LoginManager()
login_manager.init_app(app)
# -------------------------------------------------------------


@socketio.on('c_back_to_room')
def c_back_to_room(msg):
    emit('server_response', {'user_list': user_list.json()}, broadcast=True)


@socketio.on('client_submit')
def client_submit(msg):
    if user_list.is_submit():
        return

    if question_list.is_answer_right(msg["answer"]):
        user_list.submit_success()
    else:
        user_list.submit_fail()
    emit('s_update_game_user_list', {'user_list': user_list.json()}, broadcast=True)

    if user_list.is_all_user_submit():
        if not question_list.is_last_question():
            question_list.next_question()
            user_list.reset_submit()
            emit('s_update_game_user_list', {'user_list': user_list.json()}, broadcast=True)
            emit('s_update_game_question', {'question_list': question_list.json()}, broadcast=True)
        else:
            question_list.reset()
            emit('s_match_is_over', {"winner_name": user_list.winner_name()}, broadcast=True)


class QuestionList(object):
    def reset(self):
        self.question_list = []
        self.question_id = 0

        # 选出要考的诗
        random.shuffle(self.poem_list)
        poem_list = self.poem_list[: 10]

        for poem in poem_list:
            # 把一首诗打散成很多联
            pair_list = []
            pair_list_ = poem["content"].replace("\n", u"。").split(u"。")
            for pair in pair_list_:
                pair = pair.strip()
                if not pair:
                    continue
                if set(list(u"()（）？！：?；")) & set(list(pair)):
                    continue
                if u"，" not in pair:
                    continue

                pair_list.append(pair)

            if not pair_list:
                continue
            # 选一联出题
            pair = random.choice(pair_list)
            sentence_list = pair.split(u"，")
            # 选出要考的句子
            id_ = random.randint(0, len(sentence_list)-1)
            target_sentence = sentence_list[id_]
            sentence_list[id_] = "_" * 14
            # 找到跟要考的句子相似的句子组成四个选项
            similar_sentence_list = []
            random.shuffle(self.sentence_list)
            for s in self.sentence_list:
                if s.strip() == target_sentence.strip():
                    continue
                if len(s) != len(target_sentence):
                    continue
                # 要求最后一个字的韵母相同
                if get_finals(lazy_pinyin(s[-1])[0], True) != get_finals(lazy_pinyin(target_sentence[-1])[0], True):
                    continue
                similar_sentence_list.append(s)
                if len(similar_sentence_list) == 3:
                    break
            if len(similar_sentence_list) < 3:
                similar_sentence_list += ["达拉崩吧公主米亚幸福的像个童话"] * (3 - len(similar_sentence_list))
            insert_index = random.randint(0, 3)
            similar_sentence_list.insert(insert_index, target_sentence)

            # 加入试卷
            self.question_list.append({
                "question": u"，".join(sentence_list),
                "choice_list": similar_sentence_list,
                "answer": "ABCD"[insert_index]
            })

    def json(self):
        return {
            "question_id": self.question_id,
            "question_list": self.question_list
        }

    def __init__(self):
        self.question_id = 0
        self.question_list = []
        with open("poem_list.json", "r") as f:
            self.poem_list = json.loads(f.read())
        self.sentence_list = []
        for poem in self.poem_list:
            pair_list_ = poem["content"].replace("\n", u"。").split(u"。")
            for pair in pair_list_:
                pair = pair.strip()
                if not pair:
                    continue
                if set(list(u"()（）？！：?；")) & set(list(pair)):
                    continue
                if u"，" not in pair:
                    continue
                self.sentence_list.extend(pair.split(u"，"))
        self.sentence_list = list(set(self.sentence_list))
        # self.poem_list = self.poem_list[: 200]
        self.reset()

    def is_answer_right(self, answer):
        return answer.strip() == self.question_list[self.question_id]["answer"]

    def next_question(self):
        self.question_id += 1

    def is_last_question(self):
        return self.question_id == len(self.question_list) - 1


@socketio.on('client_status_changed')
def client_status_changed(data):
    user_list.set_is_ready(data["is_ready"])
    emit('server_response', {'user_list': user_list.json()}, broadcast=True)

    if user_list.is_all_user_ready() and len(user_list) >= 1:
        user_list.reset_all()
        question_list.reset()

        data = {"question_list": question_list.json(), "now_question_id": 0, "user_list": user_list.json()}
        emit('server_all_user_ready', data, broadcast=True)
        emit('s_update_game_user_list', {'user_list': user_list.json()}, broadcast=True)
        emit('s_update_game_question', {'question_list': question_list.json()}, broadcast=True)


class UserList(object):
    def winner_name(self):
        username = sorted(self.userlist, key=lambda x: x["score"], reverse=True)[0]["username"]
        return {
            "wangyi": u"王一",
            "wanger": u"王二",
            "wangsan": u"王三",
            "wangsi": u"王四",
        }.get(username, username)

    def is_submit(self):
        for user in self.userlist:
            if user["username"] == current_user.username:
                return user["is_submit_success"] != -1

    def reset_all(self):
        for user in self.userlist:
            user["is_ready"] = 0
            user["is_submit_success"] = -1
            user["score"] = 0
            user["is_submit"] = 0

    def is_all_user_submit(self):
        for user in self.userlist:
            if user["is_submit_success"] == -1:
                return False
        return True

    def json(self):
        return self.userlist

    def submit_success(self):
        for user in self.userlist:
            if user["username"] == current_user.username:
                submit_num = len([x for x in self.userlist if x["is_submit_success"] == 1])
                user["score"] += max(4 - submit_num, 1)
                user["is_submit_success"] = 1

    def submit_fail(self):
        for user in self.userlist:
            if user["username"] == current_user.username:
                user["is_submit_success"] = 0

    def set_submit(self):
        for user in self.userlist:
            if user["username"] == current_user.username:
                user["is_submit"] = 1

    def __len__(self):
        return len(self.userlist)

    def set_is_ready(self, is_ready):
        for user in self.userlist:
            if user["username"] == current_user.username:
                user["is_ready"] = is_ready

    def __init__(self):
        self.userlist = []

    def __contains__(self, item):
        for user in self.userlist:
            if user["username"] == item.username:
                return True
        return False

    def append(self, item):
        self.userlist.append(item.dict())

    def remove(self, item):
        for i, user in enumerate(self.userlist):
            if user["username"] == item.username:
                self.userlist.pop(i)

    def is_all_user_ready(self):
        for user in self.userlist:
            if not user["is_ready"]:
                return False
        return True

    def reset_submit(self):
        for user in self.userlist:
            user["is_submit"] = 0
            user["is_submit_success"] = -1




user_list = UserList()


question_list = QuestionList()


@app.route('/room')
@login_required
def room():
    return render_template('room.html')


@login_manager.user_loader
def load_user(userid):
    return User.get(userid)


class User(UserMixin):
    def dict(self):
        return {
            "score": self.score,
            "is_submit_success": self.is_submit_success,
            "username": self.username,
            "is_ready": self.is_ready,
        }

    def __eq__(self, other):
        return self.username == other.username

    def __init__(self, username, password):
        self.score = 0
        self.is_submit_success = -1
        self.username = username
        self.password = password
        self.is_ready = 0

    def is_authenticated(self):
        return self.username in ["wangyi", "wanger", "wangsan", "wangsi"]\
               and self.password == "123"

    def get_id(self):
        return self.username

    @classmethod
    def get(cls, userid):
        return User(userid, "123")


@app.route('/login', methods=["GET", "POST"])
def login():
    logging.debug("someone coming: " + request.remote_addr)
    if request.method == "GET":
        return render_template('login.html')
    else:
        user = User(request.form.get("username"), request.form.get("password"))
        if user.is_authenticated():
            login_user(user, False)

            return redirect("/room", code=302)
        else:
            return redirect("/login", code=302)


@app.route('/')
@login_required
def index():
    return render_template('index.html')


@socketio.on('client_event')
def client_msg(msg):
    emit('server_response', {'data': msg['data']}, broadcast=True)


@socketio.on('connect_event')
def connected_msg(msg):
    emit('server_response', {'data': msg['data']})


@socketio.on('connect')
def someone_connect():
    if current_user not in user_list:
        user_list.append(current_user)
    emit('server_response', {'user_list': user_list.json()}, broadcast=True)


@socketio.on('disconnect')
def disconnect():
    if current_user in user_list:
        user_list.remove(current_user)
    emit('server_response', {'user_list': user_list.json()}, broadcast=True)


if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0')
