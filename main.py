import RPi.GPIO as GPIO
import cv2
from pyzbar.pyzbar import decode
from time import sleep
import requests
import json

# === ตั้งค่า GPIO ===
GPIO.setmode(GPIO.BOARD)

servo_pin1 = 11  # ตัวที่ 1
servo_pin2 = 13  # ตัวที่ 2

GPIO.setup(servo_pin1, GPIO.OUT)
GPIO.setup(servo_pin2, GPIO.OUT)

pwm1 = GPIO.PWM(servo_pin1, 50)  # 50Hz
pwm2 = GPIO.PWM(servo_pin2, 50)  # 50Hz

pwm1.start(0)
pwm2.start(0)

# === ตั้งค่าคะแนนสำหรับแต่ละประเภทขยะ ===
TRASH_POINTS = {
    'cardboard': 10,
    'glass': 15,
    'metal': 20,
    'paper': 8,
    'plastic': 12,
    'trash': 2,
    'Food Organics': 5,
    'Miscellaneous': 3,
    'Textile Trash': 7,
    'Vegetation': 6
}

# === API URLs ===
USERS_API = "https://twg.ongor.fun/users"
PREDICT_API = "https://api.ongor.fun/throw2go/predict"
ADD_POINTS_API = "https://twg.ongor.fun/users/{}/add_points"

def set_angle(pwm, angle):
    """ตั้งมุมของ servo motor"""
    duty = 2 + (angle / 18)
    pwm.ChangeDutyCycle(duty)
    sleep(0.5)  # ให้เวลามอเตอร์ขยับ

def check_user_exists(qr_data):
    """ตรวจสอบว่า UID ของผู้ใช้มีอยู่ใน database หรือไม่"""
    try:
        response = requests.get(USERS_API, timeout=10)
        if response.status_code == 200:
            users_data = response.json()
            return qr_data in users_data
        else:
            print(f"Error checking user: HTTP {response.status_code}")
            return False
    except Exception as e:
        print(f"Error checking user: {e}")
        return False

def capture_and_predict_trash(camera):
    """ใช้กล้องตัวที่ 2 ถ่ายภาพและส่งไป predict"""
    try:
        # ล้างบัฟเฟอร์กล้องก่อนถ่าย (อ่านภาพทิ้งไป 5 เฟรม)
        print("ล้างบัฟเฟอร์กล้อง...")
        for i in range(5):
            camera.read()
            sleep(0.1)
        
        # ถ่ายภาพจริง
        ret, frame = camera.read()
        if not ret:
            print("ไม่สามารถถ่ายภาพได้")
            return None, None
            
        print("ถ่ายภาพสำเร็จ")
            
        # แปลงภาพเป็น JPEG format ในหน่วยความจำ
        success, img_encoded = cv2.imencode('.jpg', frame)
        if not success:
            print("ไม่สามารถ encode ภาพได้")
            return None, None
        
        # เตรียมไฟล์สำหรับส่ง
        img_bytes = img_encoded.tobytes()
        files = {
            'image': ('image.jpg', img_bytes, 'image/jpeg')
        }
        
        # ส่งไป API แบบ multipart/form-data
        response = requests.post(PREDICT_API, files=files, timeout=15)
        
        if response.status_code == 200:
            result = response.json()
            predicted_class = result.get("predicted_class")
            confidence = result.get("confidence", 0)
            print(f"Predicted: {predicted_class}, Confidence: {confidence:.2f}")
            return predicted_class, confidence
        else:
            print(f"Error predicting: HTTP {response.status_code}")
            return None, None
            
    except Exception as e:
        print(f"Error in prediction: {e}")
        return None, None

def add_points_to_user(user_id, predicted_class):
    """เพิ่มคะแนนให้กับผู้ใช้"""
    try:
        points = TRASH_POINTS.get(predicted_class, 0)
        if points == 0:
            print(f"ไม่มีคะแนนสำหรับประเภท: {predicted_class}")
            return False
            
        url = ADD_POINTS_API.format(user_id)
        payload = {"points": points}
        
        response = requests.post(url, json=payload, timeout=10)
        
        if response.status_code == 200:
            print(f"เพิ่มคะแนน {points} ให้ผู้ใช้ {user_id} สำเร็จ")
            return True
        else:
            print(f"Error adding points: HTTP {response.status_code}")
            return False
            
    except Exception as e:
        print(f"Error adding points: {e}")
        return False

def reset_servos():
    """รีเซ็ต servo กลับตำแหน่งเริ่มต้น"""
    print("รีเซ็ต servo กลับตำแหน่งเริ่มต้น")
    set_angle(pwm1, 85)
    set_angle(pwm2, 65)
    # รอให้ servo เคลื่อนที่เสร็จ
    sleep(2)
    print("รีเซ็ตเสร็จสิ้น - พร้อมใช้งานใหม่")

def main():
    """ฟังก์ชันหลัก"""
    # เริ่มต้นที่ 85 องศา
    print("เซอร์โวอยู่ที่ตำแหน่งเริ่มต้น รอ QR Code...")
    reset_servos()

    # === เปิดกล้อง ===
    # กล้องตัวที่ 1 สำหรับสแกน QR
    cap1 = cv2.VideoCapture(0)
    cap1.set(3, 640)
    cap1.set(4, 480)
    
    # กล้องตัวที่ 2 สำหรับถ่ายภาพขยะ
    cap2 = cv2.VideoCapture(1)  # หรือเปลี่ยนเป็น index ที่เหมาะสม
    cap2.set(3, 640)
    cap2.set(4, 480)
    
    # ตั้งค่า buffer size ให้เล็กลงเพื่อลดความล่าช้าของภาพ
    cap2.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    try:
        while True:
            success, frame = cap1.read()
            if not success:
                continue

            # แสดงภาพจากกล้องตัวที่ 1
            cv2.imshow("QR Scanner", frame)
            
            # สแกนหา QR code
            for code in decode(frame):
                qr_data = code.data.decode("utf-8")
                print(f"เจอ QR: {qr_data}")

                # ตรวจสอบผู้ใช้
                if check_user_exists(qr_data):
                    print(f"ผู้ใช้ {qr_data} มีอยู่ในระบบ")
                    
                    # เปิด servo ตัวแรก (ฝาถัง) ไปที่ 0°
                    print("เปิดฝาถังขยะ...")
                    set_angle(pwm1, 0)

                    print("รอให้ผู้ใช้ใส่ขยะ 10 วินาที...")
                    sleep(10)

                    # ปิดฝาถังขยะ
                    print("ปิดฝาถังขยะ...")
                    set_angle(pwm1, 51)

                    # ถ่ายภาพก่อน (ขณะขยะยังอยู่บนถาด)
                    print("กำลังถ่ายภาพและวิเคราะห์ขยะ...")
                    predicted_class, confidence = capture_and_predict_trash(cap2)
                    
                    if predicted_class and confidence:
                        print(f"ตรวจพบ: {predicted_class} (ความมั่นใจ: {confidence:.2f})")
                        
                        # เพิ่มคะแนนให้ผู้ใช้
                        if add_points_to_user(qr_data, predicted_class):
                            print("เพิ่มคะแนนสำเร็จ!")
                        else:
                            print("ไม่สามารถเพิ่มคะแนนได้")
                        
                        # ตอนนี้ค่อยเปิดถาดให้ขยะตกลงไปในถัง
                        print("เปิดถาดให้ขยะตกลงไปในถัง...")
                        set_angle(pwm2, 180)  # เปิดถาดล่าง
                        
                        print("รอให้ขยะตกลง 3 วินาที...")
                        sleep(3)
                        
                        # ปิดถาดกลับ
                        print("ปิดถาดกลับ...")
                        set_angle(pwm2, 65)
                    
                        print("รออีก 2 วินาที...")
                        sleep(2)
                        print("Success - กระบวนการเสร็จสิ้น")
                    else:
                        print("ไม่สามารถวิเคราะห์ขยะได้ - ปิดฝาถังทันที")
                        # ปิดฝาถังทันที (กลับไปตำแหน่งเริ่มต้น)
                        print("กลับไปตำแหน่งเริ่มต้น...")
                        set_angle(pwm1, 85)
                        print("กระบวนการหยุดเนื่องจากไม่สามารถวิเคราะห์ขยะได้")

                    # กลับตำแหน่งเริ่มต้น
                    reset_servos()
                    
                else:
                    print(f"ผู้ใช้ {qr_data} ไม่มีในระบบ")

            if cv2.waitKey(1) == ord("q"):
                break

    except KeyboardInterrupt:
        print("หยุดด้วย Ctrl+C")

    finally:
        cap1.release()
        cap2.release()
        cv2.destroyAllWindows()
        pwm1.stop()
        pwm2.stop()
        GPIO.cleanup()

if __name__ == "__main__":
    main()