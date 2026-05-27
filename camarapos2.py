import cv2
import numpy as np
import serial
import threading
import queue
import time

SERIAL_PORT = '/dev/ttyUSB0'
BAUD_RATE = 115200
CAPTURE_WIDTH = 640
CAPTURE_HEIGHT = 480
PROC_WIDTH = 160
PROC_HEIGHT = 120
FRAME_RATE = 60
MIN_RED_PIXELS = 150

pipeline = (
    "libcamerasrc ! "
    f"video/x-raw,width={CAPTURE_WIDTH},height={CAPTURE_HEIGHT},framerate={FRAME_RATE}/1 ! "
    "videoconvert ! "
    "video/x-raw,format=BGR ! "
    "appsink drop=true max-buffers=1 sync=false"
)


def open_camera():
    cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
    if not cap.isOpened():
        raise RuntimeError("No se pudo abrir la cámara")
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


def camera_reader(cap, frame_queue, stop_event):
    while not stop_event.is_set():
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.005)
            continue

        try:
            frame_queue.put(frame, timeout=0.01)
        except queue.Full:
            try:
                frame_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                frame_queue.put(frame, timeout=0.01)
            except queue.Full:
                pass

    cap.release()


def process_frame(frame):
    small = cv2.resize(frame, (PROC_WIDTH, PROC_HEIGHT), interpolation=cv2.INTER_LINEAR)
    mask = cv2.inRange(small, (0, 0, 50), (60, 30, 255))
    moments = cv2.moments(mask, binaryImage=True)

    if moments['m00'] >= MIN_RED_PIXELS:
        px = int(moments['m10'] / moments['m00'])
        py = int(moments['m01'] / moments['m00'])
        x = int(px * CAPTURE_WIDTH / PROC_WIDTH)
        y = int(py * CAPTURE_HEIGHT / PROC_HEIGHT)
        return frame, mask, x, y, True

    return frame, mask, 0, 0, False


def main():
    stop_event = threading.Event()
    frame_queue = queue.Queue(maxsize=1)

    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0)
    cap = open_camera()

    reader = threading.Thread(
        target=camera_reader,
        args=(cap, frame_queue, stop_event),
        daemon=True,
    )
    reader.start()

    try:
        while True:
            try:
                frame = frame_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            frame, mask, x, y, found = process_frame(frame)

            if found:
                rel_x = x - (CAPTURE_WIDTH // 2)
                rel_y = (CAPTURE_HEIGHT // 2) - y
                data = f"{rel_x},{rel_y}\n"
                ser.write(data.encode())
                print(data.strip())
                cv2.circle(frame, (x, y), 4, (0, 255, 0), -1)

            cv2.imshow("Frame", frame)
            cv2.imshow("Mask", cv2.resize(mask, (CAPTURE_WIDTH, CAPTURE_HEIGHT), interpolation=cv2.INTER_NEAREST))

            if cv2.waitKey(1) == 27:
                break
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        reader.join(timeout=1.0)
        cv2.destroyAllWindows()
        ser.close()


if __name__ == '__main__':
    main()
