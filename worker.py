from celery import Celery
import asyncpg
import asyncio
from datetime import datetime

# Create a Celery instance
celery = Celery(__name__, broker='redis://localhost:6379/0')

# TODO: open connection at the start of the script

@celery.task
def store_message(conversation_id, sender_id, content, timestamp):
    if isinstance(timestamp, str):
        timestamp = datetime.fromisoformat(timestamp)
    asyncio.run(async_persist_message(conversation_id, sender_id, content, timestamp))

async def async_persist_message(conversation_id, sender_id, content, timestamp):
    conn = await asyncpg.connect(user='admin', password='password', database='connect', host='localhost')
    await conn.execute(
        "INSERT INTO messages (conversation_id, sender_id, content, timestamp) VALUES ($1, $2, $3, $4)",
        conversation_id, sender_id, content, timestamp
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