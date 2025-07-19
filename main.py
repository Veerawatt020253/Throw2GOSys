import RPi.GPIO as GPIO
import cv2
from pyzbar.pyzbar import decode
from time import sleep
import requests
import json
import base64
from io import BytesIO
from PIL import Image

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

def open_camera(camera_index):
    """เปิดกล้องและตั้งค่า"""
    cap = cv2.VideoCapture(camera_index)
    cap.set(3, 640)
    cap.set(4, 480)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap

def close_camera(cap):
    """ปิดกล้องและปล่อยทรัพยากร"""
    if cap and cap.isOpened():
        cap.release()
        print(f"ปิดกล้องแล้ว")

def capture_and_predict_trash():
    """เปิดกล้องตัวที่ 2, ถ่ายภาพ, predict แล้วปิดกล้อง"""
    cap2 = None
    try:
        print("เปิดกล้องสำหรับถ่ายภาพขยะ...")
        cap2 = open_camera(1)  # กล้องตัวที่ 2
        
        if not cap2.isOpened():
            print("ไม่สามารถเปิดกล้องตัวที่ 2 ได้")
            return None, None
        
        # ล้างบัฟเฟอร์กล้องก่อนถ่าย
        print("ล้างบัฟเฟอร์กล้อง...")
        for i in range(5):
            cap2.read()
            sleep(0.1)
        
        # ถ่ายภาพจริง
        ret, frame = cap2.read()
        if not ret:
            print("ไม่สามารถถ่ายภาพได้")
            return None, None
            
        print("ถ่ายภาพสำเร็จ")
            
        # แปลงภาพเป็น base64
        pil_img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        buffered = BytesIO()
        pil_img.save(buffered, format="JPEG")
        img_base64 = base64.b64encode(buffered.getvalue()).decode()
        
        # ส่งไป API
        payload = {"image": img_base64}
        response = requests.post(PREDICT_API, json=payload, timeout=15)
        
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
    finally:
        # ปิดกล้องเสมอ
        close_camera(cap2)

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
    sleep(2)
    print("รีเซ็ตเสร็จสิ้น - พร้อมใช้งานใหม่")

def scan_qr_loop():
    """ลูปสแกน QR code โดยใช้กล้องตัวที่ 1"""
    cap1 = None
    try:
        print("เปิดกล้องสำหรับสแกน QR Code...")
        cap1 = open_camera(0)  # กล้องตัวที่ 1
        
        if not cap1.isOpened():
            print("ไม่สามารถเปิดกล้องตัวที่ 1 ได้")
            return None
            
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
                
                # ปิดกล้องตัวที่ 1 ทันทีที่เจอ QR
                print("ปิดกล้อง QR Scanner...")
                close_camera(cap1)
                cv2.destroyAllWindows()
                
                return qr_data  # ส่งข้อมูล QR กลับไป

            if cv2.waitKey(1) == ord("q"):
                break
                
        return None
        
    except Exception as e:
        print(f"Error in QR scanning: {e}")
        return None
    finally:
        close_camera(cap1)
        cv2.destroyAllWindows()

def main():
    """ฟังก์ชันหลัก"""
    print("เซอร์โวอยู่ที่ตำแหน่งเริ่มต้น รอ QR Code...")
    reset_servos()

    try:
        while True:
            # สแกน QR code (เปิดกล้องตัวที่ 1)
            qr_data = scan_qr_loop()
            
            if qr_data:  # เจอ QR code
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

                    # ถ่ายภาพและวิเคราะห์ (เปิดกล้องตัวที่ 2)
                    print("กำลังถ่ายภาพและวิเคราะห์ขยะ...")
                    predicted_class, confidence = capture_and_predict_trash()
                    
                    if predicted_class and confidence:
                        print(f"ตรวจพบ: {predicted_class} (ความมั่นใจ: {confidence:.2f})")
                        
                        # เพิ่มคะแนนให้ผู้ใช้
                        if add_points_to_user(qr_data, predicted_class):
                            print("เพิ่มคะแนนสำเร็จ!")
                        else:
                            print("ไม่สามารถเพิ่มคะแนนได้")
                    else:
                        print("ไม่สามารถวิเคราะห์ขยะได้")
                    
                    # เปิดถาดให้ขยะตกลงไปในถัง
                    print("เปิดถาดให้ขยะตกลงไปในถัง...")
                    set_angle(pwm2, 180)
                    
                    print("รอให้ขยะตกลง 3 วินาที...")
                    sleep(3)
                    
                    # ปิดถาดกลับ
                    print("ปิดถาดกลับ...")
                    set_angle(pwm2, 65)
                
                    print("รออีก 2 วินาที...")
                    sleep(2)
                    print("Success - กระบวนการเสร็จสิ้น")

                    # กลับตำแหน่งเริ่มต้น
                    reset_servos()
                    
                else:
                    print(f"ผู้ใช้ {qr_data} ไม่มีในระบบ")
                    
            else:  # กด q หรือเกิดข้อผิดพลาด
                break

    except KeyboardInterrupt:
        print("หยุดด้วย Ctrl+C")

    finally:
        pwm1.stop()
        pwm2.stop()
        GPIO.cleanup()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()