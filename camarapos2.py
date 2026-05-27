import cv2
import numpy as np
import serial
import threading
import time

SERIAL_PORT = '/dev/ttyUSB0'
BAUD_RATE = 115200

CAPTURE_WIDTH = 320
CAPTURE_HEIGHT = 240

PROC_WIDTH = 160
PROC_HEIGHT = 120

FRAME_RATE = 60

MIN_RED_PIXELS = 150

DISPLAY_SCALE = 2

latest_frame = None
frame_lock = threading.Lock()

# PIPELINE GSTREAMER
pipeline = (
    "libcamerasrc ! "
    f"video/x-raw,width={CAPTURE_WIDTH},height={CAPTURE_HEIGHT},framerate={FRAME_RATE}/1 ! "
    "queue max-size-buffers=1 leaky=downstream ! "
    "videoconvert ! "
    "video/x-raw,format=BGR ! "
    "appsink max-buffers=1 drop=true sync=false"
)

# ABRIR CAMARA
def open_camera():

    cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)

    if not cap.isOpened():
        raise RuntimeError("No se pudo abrir la cámara")

    # Evita buffers internos OpenCV
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    return cap

# THREAD DE CAPTURA
def camera_reader(cap, stop_event):

    global latest_frame

    while not stop_event.is_set():

        ret, frame = cap.read()

        if not ret:
            continue

        # Guardar SOLO frame mas reciente
        with frame_lock:
            latest_frame = frame

    cap.release()

# PROCESAMIENTO
def process_frame(frame):

    small = cv2.resize(
        frame,
        (PROC_WIDTH, PROC_HEIGHT),
        interpolation=cv2.INTER_AREA
    )

    mask = cv2.inRange(
        small,
        (0, 0, 50),
        (60, 30, 255)
    )

    # FILTRO
    kernel = np.ones((3,3), np.uint8)

    # Eliminar ruido pequeño
    mask = cv2.erode(mask, kernel, iterations=1)

    # Recuperar tamaño objeto
    mask = cv2.dilate(mask, kernel, iterations=2)

    # BUSCAR CONTORNOS
    contours, _ = cv2.findContours(
        mask,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE
    )

    found = False
    x = 0
    y = 0

    if contours:

        # Contorno mas grande
        largest = max(contours, key=cv2.contourArea)

        area = cv2.contourArea(largest)

        # Ignorar objetos pequeños
        if area > 50:

            M = cv2.moments(largest)

            if M["m00"] != 0:

                px = int(M["m10"] / M["m00"])
                py = int(M["m01"] / M["m00"])

                x = int(px * CAPTURE_WIDTH / PROC_WIDTH)
                y = int(py * CAPTURE_HEIGHT / PROC_HEIGHT)

                found = True

    return mask, x, y, found

# MAIN
def main():

    global latest_frame

    stop_event = threading.Event()

    # Activar serial
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0, write_timeout=0)

    # CAMARA
    cap = open_camera()

    # THREAD CAMARA
    capture_thread = threading.Thread(target=camera_reader, args=(cap, stop_event), daemon=True)

    capture_thread.start()

    # VENTANAS
    cv2.namedWindow("Frame", cv2.WINDOW_NORMAL)
    cv2.namedWindow("Mask", cv2.WINDOW_NORMAL)

    cv2.resizeWindow("Frame", CAPTURE_WIDTH * DISPLAY_SCALE, CAPTURE_HEIGHT * DISPLAY_SCALE)

    cv2.resizeWindow("Mask", CAPTURE_WIDTH * DISPLAY_SCALE, CAPTURE_HEIGHT * DISPLAY_SCALE)

    # LOOP PRINCIPAL
    try:

        while True:

            # Obtener frame MAS RECIENTE
            with frame_lock:

                if latest_frame is None:
                    continue

                frame = latest_frame

            # Procesamiento
            mask, x, y, found = process_frame(frame)

            # OBJETO ENCONTRADO
            if found:

                rel_x = x - (CAPTURE_WIDTH // 2)
                rel_y = (CAPTURE_HEIGHT // 2) - y

                data = f"{rel_x},{rel_y}\n"

                try:
                    ser.write(data.encode())
                except:
                    pass

                # Dibujar punto
                cv2.circle(frame, (x, y), 4, (0, 255, 0), 1)

            # DISPLAY
            display_mask = cv2.resize(mask,(CAPTURE_WIDTH,CAPTURE_HEIGHT),interpolation=cv2.INTER_NEAREST)

            cv2.imshow("Frame", frame)
            cv2.imshow("Mask", display_mask)

            if cv2.waitKey(1) == 27:
                break

    except KeyboardInterrupt:
        pass

    finally:

        stop_event.set()
        capture_thread.join(timeout=1.0)
        cap.release()
        ser.close()

        cv2.destroyAllWindows()

if __name__ == '__main__':
    main()