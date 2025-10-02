import os
import asyncio
import websockets
import psycopg2
from psycopg2.extras import execute_values

# --- PostgreSQL bağlantısı ---
DATABASE_URL = os.environ.get("DATABASE_URL")
conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

# Mesaj tablosu oluştur
cur.execute("""
CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    sender TEXT,
    receiver TEXT,
    message TEXT
);
""")
conn.commit()

clients = {}  # websocket -> username
message_queue = asyncio.Queue()  # mesajları batch işlemek için

# --- Mesajları batch ile kaydetme task ---
async def db_worker():
    while True:
        batch = []
        while not message_queue.empty():
            batch.append(await message_queue.get())
        if batch:
            execute_values(cur,
                "INSERT INTO messages (sender, receiver, message) VALUES %s",
                [(s, r, m) for s, r, m in batch]
            )
            conn.commit()
        await asyncio.sleep(1)  # 1 saniye aralıklarla commit

# --- WebSocket handler ---
async def handler(websocket):
    username = await websocket.recv()
    clients[websocket] = username
    print(f"🔗 {username} bağlandı.")

    # Önce mesaj geçmişini gönder
    cur.execute("SELECT sender, receiver, message FROM messages ORDER BY id ASC")
    rows = cur.fetchall()
    for row in rows:
        sender, receiver, message = row
        if receiver == "ALL" or receiver == username:
            msg = f"{sender}: {message}" if receiver == "ALL" else f"[Özel] {sender}: {message}"
            await websocket.send(msg)

    await notify_users()

    try:
        async for message in websocket:
            if message.startswith("/w "):
                try:
                    _, target, *msg_parts = message.split(" ")
                    msg_text = " ".join(msg_parts)
                    target_ws = next((ws for ws, name in clients.items() if name == target), None)
                    if target_ws:
                        full_msg = f"[Özel] {username}: {msg_text}"
                        await target_ws.send(full_msg)
                        await websocket.send(f"[→ {target}] {msg_text}")
                        await message_queue.put((username, target, msg_text))
                    else:
                        await websocket.send(f"⚠ Kullanıcı {target} çevrimdışı.")
                except:
                    await websocket.send("⚠ Özel mesaj formatı: /w KullanıcıAdı mesaj")
            else:
                full_msg = f"{username}: {message}"
                await message_queue.put((username, "ALL", message))
                await broadcast(full_msg)
    finally:
        del clients[websocket]
        await notify_users()
        print(f"❌ {username} ayrıldı.")

# --- Broadcast ---
async def broadcast(message):
    for ws in list(clients.keys()):
        try:
            await ws.send(message)
        except:
            pass

# --- Online kullanıcı bildirimi ---
async def notify_users():
    users = ", ".join(clients.values())
    for ws in list(clients.keys()):
        try:
            await ws.send(f"[Online Kullanıcılar] {users}")
        except:
            pass

# --- Main ---
async def main():
    PORT = int(os.environ.get("PORT", 8765))
    # DB worker task başlat
    asyncio.create_task(db_worker())
    async with websockets.serve(handler, "0.0.0.0", PORT):
        print(f"✅ Sunucu çalışıyor: ws://0.0.0.0:{PORT}")
        # Sonsuz bekleme
        stop_event = asyncio.Event()
        await stop_event.wait()

if __name__ == "__main__":
    asyncio.run(main())
