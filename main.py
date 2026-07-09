import keyboard
from selector import ScreenSelector
from capture import capture_region
from ai import analyze_image

def run():
    selector = ScreenSelector()
    bbox = selector.get_bbox()

    if not bbox:
        return

    img = capture_region(bbox)
    suggestion = analyze_image(img)

    print("\nAI Suggestion:\n")
    print(suggestion)

keyboard.add_hotkey('ctrl+shift+a', run)

print("Screen Ai running... Press ctrl+shift+a")
keyboard.wait()
if __name__ == "__main__":
    run()