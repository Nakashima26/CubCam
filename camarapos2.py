import cv2
import numpy as np
import serial
import threading
import queue
import time

# =========================
# CONFIGURACION
# =========================

SERIAL_PORT = '/dev/ttyUSB0'
BAUD_RATE = 115200

# Resolucion REAL de captura
# (mantiene FOV completo, solo reduce detalle)
CAPTURE_WIDTH = 320
CAPTURE_HEIGHT = 240

# Resolucion interna de procesamiento
PROC_WIDTH = 160
PROC_HEIGHT = 120

FRAME_RATE = 60
MIN_RED_PIXELS = 150

# Mostrar ventanas cada N frames
DISPLAY_EVERY = 2

# =========================
# PIPELINE GSTREAMER
# =========================
# IMPORTANTE:
# Esto reduce MUCHO la latencia.
# appsink con drop=true evita acumulacion de frames viejos.
#
# NO hace crop.
# Solo reduce resolucion manteniendo el FOV.

pipeline = (
    "libcamerasrc ! "
    f"video/x-raw,width={CAPTURE_WIDTH},height={CAPTURE_HEIGHT},framerate={FRAME_RATE}/1 ! "
    "videoconvert ! "
    "video/x-raw,format=BGR ! "
    "appsink drop=true max-buffers=1 sync=false"
)

# =========================
# ABRIR CAMARA
# =========================

def open_camera():
    cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)

    if not cap.isOpened():
        raise RuntimeError("No se pudo abrir la cámara")

    # Evita buffer interno
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    return cap

# =========================
# THREAD 1 - CAPTURA
# =========================

def camera_reader(cap, frame_queue, stop_event):

    while not stop_event.is_set():

        ret, frame = cap.read()

        if not ret:
            time.sleep(0.001)
            continue

        # Mantener SOLO el frame mas reciente
        if frame_queue.full():
            try:
                frame_queue.get_nowait()
            except queue.Empty:
                pass

        try:
            frame_queue.put_nowait(frame)
        except queue.Full:
            pass

    cap.release()

# =========================
# PROCESAMIENTO
# =========================

def process_frame(frame):

    # Reduccion RAPIDA
    small = cv2.resize(
        frame,
        (PROC_WIDTH, PROC_HEIGHT),
        interpolation=cv2.INTER_AREA
    )

    # Deteccion rojo
    mask = cv2.inRange(
        small,
        (0, 0, 50),
        (60, 30, 255)
    )

    moments = cv2.moments(mask, binaryImage=True)

    found = False
    x = 0
    y = 0

    if moments['m00'] >= MIN_RED_PIXELS:

        px = int(moments['m10'] / moments['m00'])
        py = int(moments['m01'] / moments['m00'])

        # Escalar coordenadas
        x = int(px * CAPTURE_WIDTH / PROC_WIDTH)
        y = int(py * CAPTURE_HEIGHT / PROC_HEIGHT)

        found = True

    return frame, mask, x, y, found

# =========================
# THREAD 2 - SERIAL
# =========================

def serial_writer(ser, serial_queue, stop_event):

    while not stop_event.is_set():

        try:
            data = serial_queue.get(timeout=0.01)
        except queue.Empty:
            continue

        try:
            ser.write(data.encode())
        except:
            pass

# =========================
# MAIN
# =========================

def main():

    stop_event = threading.Event()

    # Solo conservar frame mas nuevo
    frame_queue = queue.Queue(maxsize=1)

    # Cola serial
    serial_queue = queue.Queue(maxsize=5)

    # Serial NO bloqueante
    ser = serial.Serial(
        SERIAL_PORT,
        BAUD_RATE,
        timeout=0,
        write_timeout=0
    )

    cap = open_camera()

    # =========================
    # THREAD CAPTURA
    # =========================

    capture_thread = threading.Thread(
        target=camera_reader,
        args=(cap, frame_queue, stop_event),
        daemon=True
    )

    capture_thread.start()

    # =========================
    # THREAD SERIAL
    # =========================

    serial_thread = threading.Thread(
        target=serial_writer,
        args=(ser, serial_queue, stop_event),
        daemon=True
    )

    serial_thread.start()

    frame_counter = 0

    try:

        while True:

            try:
                frame = frame_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            frame, mask, x, y, found = process_frame(frame)

            # =========================
            # OBJETO ENCONTRADO
            # =========================

            if found:

                rel_x = x - (CAPTURE_WIDTH // 2)
                rel_y = (CAPTURE_HEIGHT // 2) - y

                data = f"{rel_x},{rel_y}\n"

                # Evita acumulacion serial
                if not serial_queue.full():
                    serial_queue.put_nowait(data)

                # Dibujar SOLO cuando existe objeto
                cv2.circle(
                    frame,
                    (x, y),
                    4,
                    (0, 255, 0),
                    -1
                )

            # =========================
            # DISPLAY OPTIMIZADO
            # =========================

            frame_counter += 1

            if frame_counter % DISPLAY_EVERY == 0:

                # Escalar SOLO para mostrar
                display_frame = cv2.resize(
                    frame,
                    (640, 480),
                    interpolation=cv2.INTER_NEAREST
                )

                display_mask = cv2.resize(
                    mask,
                    (640, 480),
                    interpolation=cv2.INTER_NEAREST
                )

                cv2.imshow("Frame", display_frame)
                cv2.imshow("Mask", display_mask)

            # waitKey PEQUEÑO
            if cv2.waitKey(1) == 27:
                break

    except KeyboardInterrupt:
        pass

    finally:

        stop_event.set()

        capture_thread.join(timeout=1.0)
        serial_thread.join(timeout=1.0)

        cap.release()
        ser.close()

        cv2.destroyAllWindows()

# =========================
# START
# =========================

if __name__ == '__main__':
    main()