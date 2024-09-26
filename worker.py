from celery import Celery
import asyncpg
import asyncio
from datetime import datetime

# Create a Celery instance
celery = Celery(__name__, broker='redis://localhost:6379/0')


# Store chat message
@celery.task
def store_message(room, sender, content, timestamp):
    # Run the async function in the event loop
    if isinstance(timestamp, str):
        timestamp = datetime.fromisoformat(timestamp)
    asyncio.run(async_persist_message(room, sender, content, timestamp))

async def async_persist_message(room, sender, content, timestamp):
    # TODO: open connection at the start of the script
    conn = await asyncpg.connect(user='admin', password='password', database='connect', host='localhost')
    await conn.execute(
        "INSERT INTO messages (room, sender, content, timestamp) VALUES ($1, $2, $3, $4)",
        room, sender, content, timestamp
    )
    await conn.close()


# Store room member
@celery.task
def enter_room(username, room):
    asyncio.run(async_persist_enter_room(username, room))

async def async_persist_enter_room(username, room):
    conn = await asyncpg.connect(user='admin', password='password', database='connect', host='localhost')
    # Step 1: Check if the room exists
    room_id = await conn.fetchval("SELECT id FROM rooms WHERE name = $1", room)
    # Step 2: If the room doesn't exist, create it and get the room ID
    if room_id is None:
        room_id = await conn.fetchval(
            "INSERT INTO rooms (name) VALUES ($1) RETURNING id",
            room
        )
    # Step 3: Check if the user is already in the room
    existing_member = await conn.fetchval(
        "SELECT 1 FROM room_members WHERE room_id = $1 AND user_id = (SELECT id FROM users WHERE username = $2)",
        room_id, username
    )
    if existing_member:
        await conn.close()
        return
    # Step 4: Add the new member to the room
    await conn.execute(
        "INSERT INTO room_members (room_id, user_id) VALUES ($1, (SELECT id FROM users WHERE username = $2))",
        room_id, username
    )
    # Step 5: Check the room member count
    member_count = await conn.fetchval(
        "SELECT COUNT(*) FROM room_members WHERE room_id = $1",
        room_id
    )
    # Step 6: If there are more than 2 members, set the room as a group chat
    if member_count > 2:
        await conn.execute(
            "UPDATE rooms SET is_group = TRUE WHERE id = $1",
            room_id
        )
    await conn.close()


# Delete room member
@celery.task
def leave_chat(username, room):
    asyncio.run(async_persist_leave_room(username, room))

async def async_persist_leave_room(username, room):
    conn = await asyncpg.connect(user='admin', password='password', database='connect', host='localhost')
    await conn.execute(
        "DELETE FROM room_members WHERE room_id = (SELECT id FROM rooms WHERE name = $1) AND user_id = (SELECT id FROM users WHERE username = $2)",
        room, username
    )
    await conn.close()


# Update message
def update_message(message_id, new_content, edited_at):
    asyncio.run(async_persist_update_message(message_id, new_content, edited_at))

async def async_persist_update_message(message_id, new_content, edited_at):
    conn = await asyncpg.connect(user='admin', password='password', database='connect', host='localhost')
    await conn.execute(
        "UPDATE messages SET content = $1, edited_at = $2 WHERE id = $3",
        new_content, edited_at, message_id
    )
    await conn.close()


# Delete message
def delete_message(message_id):
    asyncio.run(async_persist_delete_message(message_id))

async def async_persist_delete_message(message_id):
    conn = await asyncpg.connect(user='admin', password='password', database='connect', host='localhost')
    await conn.execute(
        "UPDATE messages SET deleted = TRUE WHERE id = $1",
        message_id
    )
    await conn.close()


# Update active status
@celery.task
def update_active_status(user_id, status):
    asyncio.run(async_update_active_status(user_id, status))

async def async_update_active_status(user_id, status):
    conn = await asyncpg.connect(user='admin', password='password', database='connect', host='localhost')
    if status == 'online' or status == 'offline':
        await conn.execute(
            "UPDATE users SET status = $1 WHERE id = $2",
            status, user_id
        )
    elif status == 'last_seen':
        last_seen = datetime.now()
        await conn.execute(
            "UPDATE users SET status = $1 WHERE id = $2",
            last_seen.isoformat(), user_id
        )
    await conn.close()