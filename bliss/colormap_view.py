import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg


class ColormapView:
    def __init__(self, parent, rows, cols):
        self.rows = rows
        self.cols = cols
        self.figure = Figure(figsize=(6, 3), dpi=100)
        self.ax = self.figure.add_subplot(111)
        self._image = self.ax.imshow(
            np.zeros((rows, cols), dtype=np.uint8),
            cmap="viridis",
            vmin=0,
            vmax=255,
            aspect="equal",
            interpolation="nearest",
        )
        self.ax.set_xlabel("col")
        self.ax.set_ylabel("row")
        self.figure.colorbar(self._image, ax=self.ax)
        self.canvas = FigureCanvasTkAgg(self.figure, master=parent)
        self.widget = self.canvas.get_tk_widget()

    def resize_grid(self, rows, cols):
        self.rows = rows
        self.cols = cols
        self._image.set_data(np.zeros((rows, cols), dtype=np.uint8))
        self._image.set_extent((-0.5, cols - 0.5, rows - 0.5, -0.5))
        self.canvas.draw_idle()

    def set_cmap(self, name):
        self._image.set_cmap(name)
        self.canvas.draw_idle()

    def update(self, frame):
        if frame.shape != (self.rows, self.cols):
            self.rows, self.cols = frame.shape
            self._image.set_data(frame)
            self._image.set_extent((-0.5, self.cols - 0.5, self.rows - 0.5, -0.5))
        else:
            self._image.set_data(frame)
        self.canvas.draw_idle()
