import cv2
import numpy as np
import serial
import time

ser = serial.Serial('/dev/ttyUSB0', 115200, timeout=0)

pipeline = (
    "libcamerasrc ! "
    "video/x-raw,width=640,height=480,framerate=60/1 ! "
    "videoconvert ! "
    "appsink drop=true max-buffers=1 sync=false"
)

cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)

if not cap.isOpened():
    print("No se pudo abrir la cámara")
    exit()

PROC_WIDTH = 160
PROC_HEIGHT = 120

cx = PROC_WIDTH // 2
cy = PROC_HEIGHT // 2

kernel = np.ones((3, 3), np.uint8)

while True:
    ret, frame = cap.read()

    if not ret:
        continue

    frame = cv2.resize(
        frame,
        (PROC_WIDTH, PROC_HEIGHT),
        interpolation=cv2.INTER_LINEAR
    )

    b = frame[:,:,0]
    g = frame[:,:,1]
    r = frame[:,:,2]

    mask = ((r>50) & (g<30) & (b<60))
    mask = mask.astype(np.uint8) * 255
    ys, xs = np.where(mask>0)

    if len(xs) > 150:

        x = int(np.mean(xs))
        y = int(np.mean(ys))

        rel_x = x - cx
        rel_y = cy - y
        data = f"{rel_x},{rel_y}\n"
        ser.write(data.encode())
        print(data.strip())
        # cv2.circle(frame, (x, y), 4, (0, 255, 0), -1)
    cv2.imshow("Frame", frame)
    cv2.imshow("Mask", mask)
    if cv2.waitKey(1) == 27:
        break
cap.release()
cv2.destroyAllWindows()
ser.close()
