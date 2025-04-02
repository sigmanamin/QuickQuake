import asyncio
import requests
from datetime import datetime
import pytz
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    Configuration, 
    ApiClient, 
    MessagingApi,
    TextMessage, 
    BroadcastRequest,
    PushMessageRequest
)
from linebot.v3.exceptions import InvalidSignatureError
import logging

# ตั้งค่า log
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# ตั้งค่า LINE
LINE_CHANNEL_ACCESS_TOKEN = ''
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)

# ขอบเขตพิกัดไทย
LAT_MIN, LAT_MAX = 5, 22
LON_MIN, LON_MAX = 92, 108
MIN_MAGNITUDE = 2.5
CHECK_INTERVAL = 60  # เช็คทุก 60 วินาที
MESSAGE_DELAY = 5    # หน่วงส่งข้อความ 5 วินาที

# เก็บเวลาแผ่นดินไหวล่าสุด
latest_quake_time = 0

# ดึงข้อมูลแผ่นดินไหว
def fetch_earthquake_data():
    url = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logging.error(f"ดึงข้อมูลไม่ได้: {e}")
        return None

# เช็คว่าอยู่ใกล้ไทยมั้ย
def is_near_thailand(lat, lon):
    return LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX

# ส่งข้อความ LINE
async def send_line_notification(message_text, user_id=None):
    if not message_text:
        return False

    max_retries = 5
    retry_delay = 5  # รอ 5 วินาทีแรก

    for attempt in range(max_retries):
        try:
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
                text_message = TextMessage(text=message_text)
                
                if user_id is None:  # ส่งแบบ broadcast
                    broadcast_request = BroadcastRequest(messages=[text_message])
                    response = line_bot_api.broadcast(broadcast_request)
                    logging.info(f"ส่ง broadcast: {message_text[:50]}...")
                # ถ้าจะส่งแบบ push ให้เปิดตรงนี้
                # else:
                #     push_request = PushMessageRequest(to=user_id, messages=[text_message])
                #     response = line_bot_api.push_message(push_request)
                #     logging.info(f"ส่ง push ไป {user_id}: {message_text[:50]}...")
                
                return True
        except Exception as e:
            if hasattr(e, 'status_code') and e.status_code == 429:
                if attempt < max_retries - 1:
                    wait_time = retry_delay * (2 ** attempt)  # รอนานขึ้นเรื่อยๆ
                    logging.warning(f"เกินลิมิต (429) รอ {wait_time} วินาที...")
                    await asyncio.sleep(wait_time)
                else:
                    logging.error(f"ลองครบ {max_retries} ครั้งแล้วยังส่งไม่ได้: {e}")
                    return False
            else:
                logging.error(f"ส่งข้อความมีปัญหา: {e}")
                return False

# เช็คแผ่นดินไหวและส่งข้อมูลล่าสุดทันที
async def check_earthquakes():
    global latest_quake_time
    
    data = fetch_earthquake_data()
    if not data or "features" not in data:
        return

    # เรียงจากใหม่ไปเก่า
    sorted_quakes = sorted(
        data["features"],
        key=lambda x: x["properties"]["time"],
        reverse=True
    )

    # หาแผ่นดินไหวล่าสุดในไทย
    for quake in sorted_quakes:
        props = quake["properties"]
        coords = quake["geometry"]["coordinates"]
        lon, lat, depth = coords
        magnitude = props.get("mag")
        
        if not magnitude or magnitude < MIN_MAGNITUDE:
            continue
            
        if not is_near_thailand(lat, lon):
            continue

        # ไม่เช็ค latest_quake_time เพื่อส่งข้อมูลล่าสุดทันทีสำหรับทดสอบ
        place = props.get("place", "ไม่ระบุสถานที่")
        thai_time = datetime.fromtimestamp(props["time"] / 1000, tz=pytz.UTC).astimezone(pytz.timezone('Asia/Bangkok'))

        severity = (
            "⛔️ รุนแรงมาก" if magnitude >= 6.0 
            else "⚠️ รุนแรงปานกลาง" if magnitude >= 4.0 
            else "ℹ️ เบา"
        )

        alert = (
            f"🌋 แผ่นดินไหวล่าสุด (ทดสอบ API)!\n"
            f"{severity}\n"
            f"ขนาด: {magnitude:.1f} ริกเตอร์\n"
            f"สถานที่: {place}\n"
            f"พิกัด: ({lat:.2f}, {lon:.2f})\n"
            f"ความลึก: {depth:.1f} กม.\n"
            f"เวลา: {thai_time.strftime('%Y-%m-%d %H:%M:%S')} (ไทย)\n"
            f"ดูแผนที่: https://www.google.com/maps?q={lat},{lon}"
        )

        if await send_line_notification(alert):
            latest_quake_time = props["time"]  # อัพเดทหลังส่ง
            logging.info(f"ส่งแจ้งเตือน: M{magnitude} ที่ {place}")
            await asyncio.sleep(MESSAGE_DELAY)  # รอหน่อย
        break

# เริ่มระบบ
async def main():
    global latest_quake_time
    
    logging.info("เริ่มระบบเช็คแผ่นดินไหว...")
    
    # ดึงข้อมูลครั้งแรก
    data = fetch_earthquake_data()
    if data and "features" in data:
        sorted_quakes = sorted(
            data["features"],
            key=lambda x: x["properties"]["time"],
            reverse=True
        )
        for quake in sorted_quakes:
            coords = quake["geometry"]["coordinates"]
            lon, lat, _ = coords
            if is_near_thailand(lat, lon):
                latest_quake_time = quake["properties"]["time"]
                break

    startup_message = (
        "🚀 ระบบเริ่มแล้ว!\n"
        f"เช็คแผ่นดินไหวตั้งแต่ {MIN_MAGNITUDE} ริกเตอร์\n"
        "ในไทยและใกล้เคียง\n"
        f"อัพเดททุก {CHECK_INTERVAL} วินาที"
    )
    
    if not await send_line_notification(startup_message):
        logging.error("ส่งข้อความเริ่มต้นไม่ได้ จบการทำงาน")
        return

    # ลูปเช็คตลอด
    try:
        while True:
            await check_earthquakes()
            await asyncio.sleep(CHECK_INTERVAL)
    except Exception as e:
        logging.error(f"ลูปมีปัญหา: {e}")
        await send_line_notification("⚠️ ระบบหยุดเพราะมีข้อผิดพลาด")

# รันโปรแกรม
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("ผู้ใช้หยุดระบบ")
        asyncio.run(send_line_notification("🔴 ระบบหยุดแล้ว"))
    except Exception as e:
        logging.error(f"เจอปัญหาไม่คาดคิด: {e}")
        asyncio.run(send_line_notification("⚠️ ระบบหยุดจากข้อผิดพลาด"))
