from flask import Flask, request, jsonify
from flask_socketio import SocketIO, join_room, leave_room
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity

from datetime import datetime, timedelta
from config import Config

from worker import store_message, enter_room, leave_chat, update_message, delete_message, update_active_status

import json
import redis
import psycopg2
import bcrypt


SOCKET_EVENTS = {
    'JOIN_ROOM': 'join_room',
    'LEAVE_ROOM': 'leave_room',
    'SEND_MESSAGE': 'send_message',
    'EDIT_MESSAGE': 'edit_message',
    'DELETE_MESSAGE': 'delete_message',
    'TYPING': 'typing',
    'STOP_TYPING': 'stop_typing',
    'RECEIVE_MESSAGE': 'receive_message',
    'MESSAGE_EDITED': 'message_edited',
    'MESSAGE_DELETED': 'message_deleted',
    'active_TYPING': 'user_typing',
    'USER_JOINED': 'user_joined',
    'USER_LEFT': 'user_left',
    'ACTIVE_STATUS': 'active_status',
}

REDIS_CHANNELS = {
    'CHAT_MESSAGES': 'channel:chat_messages',
    'EDIT_MESSAGES': 'channel:edit_messages',
    'DELETE_MESSAGES': 'channel:delete_messages',
    'ACTIVE_USERS': 'channel:active_users'
}

DATABASE_CONFIG = {
    'dbname': 'connect',
    'user': 'admin',
    'password': 'password',
    'host': 'localhost',
    'port': '5432'
}

USER_AUTH_RATE_LIMIT_PREFIX = "rate_limit:auth:"
USER_CHAT_RATE_LIMIT_PREFIX = "rate_limit:chat:"
AUTH_LIMIT = 10
CHAT_LIMIT = 5
RATE_LIMIT_WINDOW = 60

app = Flask(__name__)
app.config.from_object(Config)
app.config['JWT_SECRET_KEY'] = 'your-secret-key'  # Change this to your secret key
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(days=1)
CORS(app)


socketio = SocketIO(app, message_queue="redis://localhost:6379/0", cors_allowed_origins="*")
redis_client = redis.StrictRedis(host='localhost', port=6379, db=0)

conn = psycopg2.connect(**DATABASE_CONFIG)
cursor = conn.cursor()

jwt = JWTManager(app)


# --- Rate Limiter --- #
from functools import wraps
from flask import jsonify

def rate_limit(limit: int, window: int):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            email = request.json.get("email", None)
            if not email:
                return jsonify({"msg": "Email is required for rate limiting"}), 400
            rate_limit_key = USER_AUTH_RATE_LIMIT_PREFIX + email
            current_count = redis_client.incr(rate_limit_key)
            if current_count == 1:
                redis_client.expire(rate_limit_key, window)
            elif current_count > limit:
                time_remaining = redis_client.ttl(rate_limit_key)
                return jsonify({"msg": f"Rate limit exceeded. Try again in {time_remaining} seconds."}), 429
            return f(*args, **kwargs)
        return decorated_function
    return decorator


# --- HTTP Routes --- #
@app.route('/register', methods=['POST'])
@rate_limit(AUTH_LIMIT, RATE_LIMIT_WINDOW)
def register():
    username = request.json.get("username", None)
    email = request.json.get("email", None)
    status = 'online'
    password = request.json.get("password", None)
    if not username or not email or not password:
        return jsonify({"msg": "Missing required fields"}), 400
    hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
    try:
        insert_query = f"""
            INSERT INTO users (username, email, password, status)
            VALUES (%s, %s, %s, %s)
        """
        cursor.execute(insert_query, (username, email, hashed_password.decode('utf-8'), status))
        conn.commit()
        return jsonify({"msg": "User registered successfully"}), 201
    except psycopg2.Error as e:
        conn.rollback()
        return jsonify({"msg": "Database error", "error": str(e)}), 500


@app.route('/login', methods=['POST'])
@rate_limit(AUTH_LIMIT, RATE_LIMIT_WINDOW)
def login():
    email = request.json.get("email", None)
    password = request.json.get("password", None)
    if email and password:
        try:
            cursor.execute("SELECT id, username, email, password, status FROM users WHERE email = %s", (email,))
            result = cursor.fetchone()
            if result and bcrypt.checkpw(password.encode('utf-8'), result[3].encode('utf-8')):
                user_data = {
                    "id": result[0],         # User ID
                    "username": result[1],    # Username
                    "email": result[2],       # Email
                    "status": result[4]       # User status
                }
                print(user_data)
                access_token = create_access_token(identity=user_data)
                return jsonify(access_token=access_token), 200
            else:
                return jsonify({"msg": "Bad username or password"}), 401
        except psycopg2.Error as e:
            return jsonify({"msg": "Database error", "error": str(e)}), 500
    return jsonify({"msg": "Missing username or password"}), 400


@app.route('/users', methods=['GET'])
@jwt_required()
def get_users():
    cursor.execute("SELECT * FROM users")
    users = cursor.fetchall()
    users_list = [
        {
            'id': user[0],
            'username': user[1],
            'email': user[2],
            'status': user[4]
        }
        for user in users
    ]
    return jsonify(users=users_list), 200


@app.route('/conversations', methods=['GET'])
@jwt_required()
def get_conversations():
    cursor.execute("SELECT * FROM conversations")
    convos = cursor.fetchall()
    convos_list = [
        {
            'id': convo[0],
            'room_name': convo[1],
            'created_by': convo[2],
            'participant': convo[3],
            'created_at': convo[4]
        }
        for convo in convos
    ]
    return jsonify(conversations=convos_list), 200


@app.route('/conversations/<room_name>', methods=['POST'])
@jwt_required()
def check_room_exists(room_name):
    sub = get_jwt_identity()
    created_by = sub['id']
    participant = request.json.get('participant')

    try:
        check_query = f'''
            SELECT id, room_name, created_by, participant, created_at FROM conversations WHERE room_name = %s;
        '''
        with conn.cursor() as cursor:
            cursor.execute(check_query, (room_name,))
            existing_conversation = cursor.fetchone()
        if existing_conversation:
            return jsonify({
                    "id": existing_conversation[0],
                    "room_name": existing_conversation[1],
                    "created_by": existing_conversation[2],
                    "participant": existing_conversation[3],
                    "created_at": existing_conversation[4],
                }), 200
        else:
            insert_query = f'''
                INSERT INTO conversations (room_name, created_by, participant) 
                VALUES (%s, %s, %s) RETURNING id, room_name, created_by, participant, created_at;
            '''
            with conn.cursor() as cursor:
                cursor.execute(insert_query, (room_name, created_by, participant))
                conn.commit()
                conversation_id, room_name, created_by, participant, created_at = cursor.fetchone()
                print(f"Created new conversation: {room_name} by user ID {created_by}")
                return jsonify({
                    "id": conversation_id,
                    "room_name": room_name,
                    "created_by": created_by,
                    "participant": participant,
                    "created_at": created_at,
                }), 201

    except Exception as e:
        print(f"An error occurred: {e}")
        conn.rollback()
        return jsonify({"message": f"An error occurred: {e}"}), 500


@jwt.expired_token_loader
def expired_token_callback(jwt_header, jwt_payload):
    return jsonify({"msg": "The token has expired", "error": "token_expired"}), 401


# Join a room (start a chat)
@socketio.on(SOCKET_EVENTS['JOIN_ROOM'])
def handle_join_room(data):
    room_name = data['room']
    created_by = data['created_by']
    username = data['username']  # For broadcast to another user
    join_room(room_name)
    socketio.emit(SOCKET_EVENTS['USER_JOINED'], {'username': username, 'room': room_name}, room=room_name)

# Leave a room (del a chat or manually leave)
@socketio.on(SOCKET_EVENTS['LEAVE_ROOM'])
def handle_leave_room(data):
    room = data['room']
    username = data['username']
    leave_room(room)
    socketio.emit(SOCKET_EVENTS['USER_LEFT'], {'username': username}, room=room, include_self=False)
    # leave_chat.delay(username, room)


# Sending messages
@socketio.on(SOCKET_EVENTS['SEND_MESSAGE'])
def handle_send_message(data):
    message = {
        'sid': data['sid'],
        'room': data['room'],
        'sender': data['sender'],
        'content': data['content'],
        'timestamp': str(datetime.now())
    }
    redis_client.publish(REDIS_CHANNELS['CHAT_MESSAGES'], json.dumps(message))
    # store_message.delay(message['room'], message['sender'], message['content'], message['timestamp'])


# Editing messages
@socketio.on(SOCKET_EVENTS['EDIT_MESSAGE'])
def handle_edit_message(data):
    message = {
        'sid': data['sid'],
        'message_id': data['message_id'],
        'room': data['room'],
        'sender': data['sender'],
        'new_content': data['new_content'],
        'edited_at': str(datetime.now())
    }
    redis_client.publish(REDIS_CHANNELS['EDIT_MESSAGES'], json.dumps(message))
    # update_message.delay(message['message_id'], message['new_content'], message['edited_at'])


# Deleting messages
@socketio.on(SOCKET_EVENTS['DELETE_MESSAGE'])
def handle_delete_message(data):
    message = {
        'room': data['room'],
        'message_id': data['message_id']
    }
    redis_client.publish(REDIS_CHANNELS['DELETE_MESSAGES'], json.dumps(message))
    # delete_message.delay(message['message_id'])


# Typing animation
@socketio.on(SOCKET_EVENTS['TYPING'])
def handle_typing(data):
    room = data['room']
    user = data['user']
    socketio.emit(SOCKET_EVENTS['USER_TYPING'], {'user': user, 'typing': True}, room=room)

# Stop typing animation
@socketio.on(SOCKET_EVENTS['STOP_TYPING'])
def handle_stop_typing(data):
    room = data['room']
    user = data['user']
    socketio.emit(SOCKET_EVENTS['USER_TYPING'], {'user': user, 'typing': False}, room=room)


# Active Status
@socketio.on(SOCKET_EVENTS['ACTIVE_STATUS'])
def handle_active_status(data):
    user_id = data['user_id']
    status = data['status']  # 'online', 'offline', or 'last_seen'
    redis_client.hset(REDIS_CHANNELS['ACTIVE_USERS'], user_id, status)
    update_active_status.delay(user_id, status)
    socketio.emit(SOCKET_EVENTS['ACTIVE_STATUS'], {'user_id': user_id, 'status': status})


# --- LISTENERS --- #
def listen_for_messages():
    pubsub = redis_client.pubsub()
    pubsub.subscribe(REDIS_CHANNELS['CHAT_MESSAGES'])

    for message in pubsub.listen():
        if message['type'] == 'message':
            data = json.loads(message['data'])
            socketio.server.emit(SOCKET_EVENTS['RECEIVE_MESSAGE'], data, room=data['room'], skip_sid=data['sid'])


def listen_for_edit_messages():
    pubsub = redis_client.pubsub()
    pubsub.subscribe(REDIS_CHANNELS['EDIT_MESSAGES'])

    for message in pubsub.listen():
        if message['type'] == 'message':
            data = json.loads(message['data'])
            socketio.server.emit(SOCKET_EVENTS['MESSAGE_EDITED'], data, room=data['room'], skip_sid=data['sid'])


def listen_for_delete_messages():
    pubsub = redis_client.pubsub()
    pubsub.subscribe(REDIS_CHANNELS['DELETE_MESSAGES'])

    for message in pubsub.listen():
        if message['type'] == 'message':
            data = json.loads(message['data'])
            socketio.server.emit(SOCKET_EVENTS['MESSAGE_DELETED'], data, room=data['room'])


def listen_for_active_status():
    pubsub = redis_client.pubsub()
    pubsub.subscribe(REDIS_CHANNELS['ACTIVE_USERS'])

    for message in pubsub.listen():
        if message['type'] == 'message':
            socketio.emit(SOCKET_EVENTS['ACTIVE_STATUS'], message['data'].decode('utf-8'))


socketio.start_background_task(listen_for_messages)
socketio.start_background_task(listen_for_edit_messages)
socketio.start_background_task(listen_for_delete_messages)
socketio.start_background_task(listen_for_active_status)


if __name__ == '__main__':
    socketio.run(app, host='localhost', port=5000, debug=True)


