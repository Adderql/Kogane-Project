import tkinter as tk

class ScreenSelector:
    def __init__(self):
        self.start_x = None
        self.start_y = None
        self.bbox = None

        self.root = tk.Tk()
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-alpha", 0.3)

        self.canvas = tk.Canvas(self.root, cursor="cross")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.rect = None

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)

    def on_press(self, event):
        self.start_x = event.x
        self.start_y = event.y
        self.rect = self.canvas.create_rectangle(
            self.start_x, self.start_y, self.start_x, self.start_y,
            outline="red", width=2
        )

    def on_drag(self, event):
        self.canvas.coords(self.rect, self.start_x, self.start_y, event.x, event.y)

    def on_release(self, event):
        self.bbox = {
            "left": min(self.start_x, event.x),
            "top": min(self.start_y, event.y),
            "width": abs(event.x - self.start_x),
            "height": abs(event.y - self.start_y),
        }
        self.root.destroy()

    def get_bbox(self):
        self.root.mainloop()
        return self.bbox