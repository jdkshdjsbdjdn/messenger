import os
import asyncio
import websockets
import psycopg2

# --- PostgreSQL bağlantısı ---
DATABASE_URL = os.environ.get("DATABASE_URL")  # Burayı değiştir
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

async def handler(websocket):
    # Kullanıcı adı al
    username = await websocket.recv()
    clients[websocket] = username
    print(f"🔗 {username} bağlandı.")

    # Önce mesaj geçmişini gönder
    cur.execute("SELECT sender, receiver, message FROM messages ORDER BY id ASC")
    rows = cur.fetchall()
    for row in rows:
        sender, receiver, message = row
        if receiver == "ALL" or receiver == username:
            if receiver == "ALL":
                msg = f"{sender}: {message}"
            else:
                msg = f"[Özel] {sender}: {message}"
            await websocket.send(msg)

    # Online kullanıcıları bildir
    await notify_users()

    try:
        async for message in websocket:
            if message.startswith("/w "):
                try:
                    _, target, *msg_parts = message.split(" ")
                    msg_text = " ".join(msg_parts)
                    target_ws = None
                    for ws, name in clients.items():
                        if name == target:
                            target_ws = ws
                            break
                    if target_ws:
                        full_msg = f"[Özel] {username}: {msg_text}"
                        await target_ws.send(full_msg)
                        await websocket.send(f"[→ {target}] {msg_text}")
                        save_message(username, target, msg_text)
                    else:
                        await websocket.send(f"⚠ Kullanıcı {target} çevrimdışı.")
                except:
                    await websocket.send("⚠ Özel mesaj formatı: /w KullanıcıAdı mesaj")
            else:
                full_msg = f"{username}: {message}"
                save_message(username, "ALL", message)
                await broadcast(full_msg)
    finally:
        del clients[websocket]
        await notify_users()
        print(f"❌ {username} ayrıldı.")

async def broadcast(message):
    for ws in list(clients.keys()):
        try:
            await ws.send(message)
        except:
            pass

async def notify_users():
    users = ", ".join(clients.values())
    for ws in list(clients.keys()):
        try:
            await ws.send(f"[Online Kullanıcılar] {users}")
        except:
            pass

def save_message(sender, receiver, message):
    cur.execute("INSERT INTO messages (sender, receiver, message) VALUES (%s, %s, %s)",
                (sender, receiver, message))
    conn.commit()

async def main():
    PORT = int(os.environ.get("PORT", 8765))  # Railway port
    async with websockets.serve(handler, "0.0.0.0", PORT):
        print(f"✅ Sunucu çalışıyor: ws://0.0.0.0:{PORT}")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
