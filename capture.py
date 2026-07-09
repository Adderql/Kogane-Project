import mss
from PIL import Image

def capture_region(box):
    with mss.mss() as sct:
        screenshot = sct.grab(box)
        img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)
        return img



#with mss.mss() as sct:
   # screencap = sct.grab(sct.monitors[1])

  # img = Image.frombytes("RGB", screencap.size, screencap.bgra, "raw", "BGRX")