from celery import Celery
import asyncpg
import asyncio
from datetime import datetime

# Create a Celery instance
celery = Celery(__name__, broker='redis://localhost:6379/0')


@celery.task
def persist_message(room, sender, content, timestamp):
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
