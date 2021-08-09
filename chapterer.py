import os
import re
import sys
import tkinter as tk
import tkinterDnD
from abc import ABC
from contextlib import suppress
from functools import wraps
from os.path import isfile
from threading import Timer
from tkinter import ttk, DoubleVar, StringVar
from time import time
from typing import Any, Callable, Tuple

import cv2
from PIL import Image, ImageTk

VID_FILE_EXTENSTIONS = ['mp4', 'mkv', 'avi', 'flv']
CHAPTERS_EXT = '.chapters.txt'

def debouce(delay: float) -> Callable:
    print(f"creating deboucer {delay}s")
    def decorator(func: Callable) -> Callable:
        timer = None
        latent = None

        @wraps(func)
        def _callfunc():
            nonlocal timer, latent
            if latent:
                wrapper.result = func(*latent[0], **latent[1])
                timer = Timer(delay, _callfunc)
                timer.start()
            else:
                timer = None
            latent = None

        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            nonlocal timer, latent
            if timer:
                latent = (args, kwargs)
            else:
                wrapper.result = func(*args, **kwargs)
                timer = Timer(delay, _callfunc)
                timer.start()

        return wrapper
    return decorator

class Video:
    class CouldNotOpenError(BaseException):
        ''' cv2 could not open '''
    class FrameNotReadError(BaseException):
        ''' cv2 could not open '''

    def __init__(self, filename):
        self.filename = filename
        self.frame_count = 0
        self.fps = 0

    def open(self) -> None:
        self.cap = cv2.VideoCapture(self.filename)
        if not self.cap.isOpened():
            raise self.CouldNotOpenError()
        print(f"{self.filename} opened")
        self.frame_count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.fps = self.cap.get(cv2.CAP_PROP_FPS)
        print(f"{self.frame_count} frames")
        print(f"{self.fps} fps")

    def close(self) -> None:
        self.filename = None
        self.frame_count = 0
        self.fps = 0x200
        self.cap.release()

    def seek(self, pos: int) -> None:
        pos = min(max(0, int(pos)), self.frame_count -1)
        print(f"seeking to frame {pos}")
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, pos)

    def seek_float(self, pos: float) -> None:
        self.seek(pos * self.frame_count)

    def get_current_frame(self) -> Image:
        rval, image = self.cap.read()
        if not rval:
            raise self.FrameNotReadError()
        image = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        return image

    def frameno_to_timestamp(self, frameno: int) -> str:
        frameno = int(frameno)
        frac = int(frameno % self.fps / self.fps * 1000)
        s = int(frameno / self.fps) % 60
        m = int(frameno / self.fps / 60) % 60
        h = int(frameno / self.fps / 3600)
        return f"{h:02}:{m:02}:{s:02}.{frac:03}"



class TkEvent:
    VIDEO_FILE = '<<VideoFile>>'
    SEEK = '<<Seek>>'
    SAVE_CHAPTERS = '<<SaveChapters>>'
    CLOSE_VIDEO = '<<CloseVideo>>'


class TkRooted(ABC):
    @property
    def root(self):
        return self._nametowidget(self.winfo_toplevel())


class DropFrame(ttk.Frame, TkRooted):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.label = ttk.Label(self, style='Big.TLabel', text="Drag and Drop Video File Here")
        self.label.grid(row=0, column=0)
        self.register_drop_target('*')
        self.bind('<<Drop>>', self._on_drop)
        self._file_name = None

    def _on_drop(self, ev: tk.Event) -> None:
        files = re.findall(r"(?:\{)(.*?)(?:\})", ev.data)
        if files and files[0][-3:] in VID_FILE_EXTENSTIONS:
            self._file_name = files[0]
            self.event_generate(TkEvent.VIDEO_FILE)

    @property
    def file_name(self) -> str:
        return self._file_name


class VideoFrame(ttk.Frame, TkRooted):
    WHEEL_FRAME_INCREMENT = 10

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.last_seek = 0
        self.info = {
            'width': 0,
            'height': 0,
            'frame_count': 0
        }
        self.chapters = ()
        self.info_var = StringVar()
        self.ui = {}
        self.ui['info'] = tk.Label(self, textvariable=self.info_var)
        self.ui['info'].grid(column=0, row=0)
        self.ui['vidcanvas'] = tk.Canvas(self, bg='black')
        self.ui['vidcanvas'].grid(column=0, row=1, sticky=tk.NSEW)
        self.ui['vidcanvas'].bind('<MouseWheel>', self._on_wheel)
        #self.ui['vidcanvas'].bind('<Configure>', self._canvas_configure)
        self.ui['chapter_name'] = ttk.Entry(self)
        self.ui['chapter_name'].grid(column=1, row=0, padx=4, sticky=tk.EW)
        self.ui['chapter_name'].bind('<Return>', self._on_add_chapter)
        self.ui['chapters'] = tk.Listbox(self, selectmode=tk.EXTENDED, width=32)
        self.ui['chapters'].grid(column=1, row=1, padx=4, pady=4, sticky=tk.NS)
        self.ui['chapters'].bind('<Delete>', self._on_delete_chapter)
        self.ui['chapters'].bind('<<ListboxSelect>>', self._on_select_chapter)
        self.ui['seeker'] = ttk.Scale(self, orient=tk.HORIZONTAL, command=self.seek_pos)
        self.ui['seeker'].grid(column=0, row=2, columnspan=2, padx=4, pady=4, sticky=tk.EW)
        self.bind_all('<Control-s>', self._on_save_chapters)
        self.bind_all('<Control-w>', self._on_close_video)

    def _get_frameno_from_chapter_list(self, idx: int) -> int:
        with suppress(BaseException):
            return int(re.match('\[(\d+)\]', self.ui['chapters'].get(idx))[1])

    def _get_name_from_chapter_list(self, idx: int) -> str:
        with suppress(BaseException):
            return re.match('\[\d+\](.*)', self.ui['chapters'].get(idx))[1].strip()

    def _get_image_dims_for_canvas(self, img: Image) -> Image:
        imgw, imgh = img.width, img.height
        canw, canh = self.ui['vidcanvas'].winfo_width(), self.ui['vidcanvas'].winfo_height()
        if imgw / imgh > canw / canh: # img wider than canvas
            scale = canw / imgw
            coords = (0, (canh - imgh * scale) / 2)
        else:
            scale = canh / imgh
            coords = ((canw - imgw * scale) / 2, 0)
        dimensions = int(imgw * scale), int(imgh * scale)

        return (*coords, *dimensions)

    def _on_wheel(self, ev: tk.Event) -> None:
        pos = self.current_seek_pos + int(min(max(ev.delta * -1, -1), 1) * self.WHEEL_FRAME_INCREMENT)
        pos = min(pos, self.info['frame_count'] - 1)
        self.ui['seeker'].set(pos)

    def _on_add_chapter(self, ev: tk.Event) -> None:
        count = self.ui['chapters'].size()
        ipos = 0
        for i in range(self.ui['chapters'].size()):
            if (self._get_frameno_from_chapter_list(i) or 0) > self.current_seek_pos:
                break
            ipos += 1
        self.ui['chapters'].insert(ipos, f"[{self.current_seek_pos}] {self.ui['chapter_name'].get()}")
        self.ui['chapter_name'].delete(0, 1000)

    def _on_select_chapter(self, ev: tk.Event) -> None:
        print(self.ui['chapters'].curselection())
        frameno = self._get_frameno_from_chapter_list(self.ui['chapters'].curselection()[0])
        self.ui['seeker'].set(frameno)
        self.event_generate(TkEvent.SEEK)

    def _on_delete_chapter(self, ev: tk.Event) -> None:
        for i in reversed(self.ui['chapters'].curselection()):
            self.ui['chapters'].delete(i)

    def _on_save_chapters(self, ev: tk.Event) -> None:
        if not self.winfo_ismapped():
            return

        self.chapters = tuple(
            (
                self._get_frameno_from_chapter_list(i),
                self._get_name_from_chapter_list(i),
            )
            for i in range(self.ui['chapters'].size())
        )
        #self.chapters = tuple(
        #    (
        #        re.match('\[(\d+)\]', entry)[1],
        #        re.match('\[\d+\](.*)', entry)[1].strip(),
        #    )
        #    for entry in self.ui['chapters'].get(0, self.ui['chapters'].size())
        #)
        self.event_generate(TkEvent.SAVE_CHAPTERS)

    def _on_close_video(self, ev: tk.Event) -> None:
        if not self.winfo_ismapped():
            return

        self.ui['chapters'].delete(0, 1000)
        self.ui['seeker'].set(0)
        self.ui['vidcanvas'].delete(tk.ALL)
        self.event_generate(TkEvent.CLOSE_VIDEO)

    def seek_pos(self, ev: tk.Event, *args, **kwargs):
        pos = self.current_seek_pos
        if self.last_seek != pos:
            self.event_generate(TkEvent.SEEK)
            self.last_seek = pos

    def update_image(self, img: Image) -> None:
        self.info['width'], self.info['height'] = img.width, img.height
        self.update_info()
        x, y, w, h = self._get_image_dims_for_canvas(img)
        img = img.resize((w, h), resample=Image.BICUBIC)
        img = ImageTk.PhotoImage(img)
        self.current_image = img # to prevent garbage collection
        self.ui['vidcanvas'].create_image((x, y), anchor=tk.NW, image=img)

    def update_info(self) -> None:
        self.info_var.set(f"{self.info['width']}x{self.info['height']} frame {self.last_seek} / {self.info['frame_count']}")

    #def get_file_list(self) -> Tuple[str]:
    #    return self.chapter.get(0)

    @property
    def current_seek_pos(self) -> int:
        return int(self.ui['seeker'].get())

    def set_frame_count(self, frames: int) -> None:
        self.info['frame_count'] = frames
        self.ui['seeker']['to'] = frames

class MyTk(tkinterDnD.Tk, TkRooted):
    FILE_FUNC = 'file_func'
    SEEK_FUNC = 'video_seek_func'
    SAVE_FUNC = 'save_chapters_func'
    CLOSE_FUNC = 'close_video_func'
    SCRIPT_FUNC = 'script_func'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.callbacks = {}
        self.geometry('1280x800')
        self.title("Video Chapter Creator")

    def build_ui(self):
        self.dropframe = DropFrame(self)
        self.vidframe = VideoFrame(self)
        self.show_frame(self.dropframe)

        self.style = ttk.Style(self)
        self.style.configure('Big.TLabel', font=('TkDefaultFont', 20))

        self.bind('<Control-r>', lambda ev: self._callback(self.SCRIPT_FUNC))
        self.bind(TkEvent.VIDEO_FILE, self._on_file)
        self.bind(TkEvent.SEEK, self._on_seek)
        self.bind(TkEvent.SAVE_CHAPTERS, self._on_save_chapters)
        self.bind(TkEvent.CLOSE_VIDEO, self._on_close_video)

    def _callback(self, name: str, *args, **kwargs) -> Any:
        return self.callbacks[name](*args, **kwargs) if name in self.callbacks else None

    def _on_close_video(self, ev: tk.Event) -> None:
        self.show_frame(self.dropframe)
        self._callback(self.CLOSE_FUNC)

    def _on_file(self, ev: tk.Event) -> None:
        filename = self.dropframe.file_name
        self._callback(self.FILE_FUNC, filename)
        self.show_frame(self.vidframe)

    @debouce(0.2)
    def _on_seek(self, ev: tk.Event) -> None:
        self._callback(self.SEEK_FUNC, self.vidframe.current_seek_pos)

    def _on_save_chapters(self, ev: tk.Event) -> None:
        self._callback(self.SAVE_FUNC, self.vidframe.chapters)

    def register_callback(self, name: str, func: Callable) -> None:
        self.callbacks[name] = func

    def show_frame(self, frame: ttk.Frame) -> None:
        self.dropframe.pack_forget()
        self.vidframe.pack_forget()
        frame.pack(expand=True, fill=tk.BOTH)

    def set_frame_count(self, count: int) -> None:
        self.vidframe.set_frame_count(count)

    def set_video_image(self, image) -> None:
        self.vidframe.update_image(image)


class App:
    def __init__(self, script: str = None):
        self.script = script
        self.video = None
        self.tk = MyTk()
        self.tk.register_callback(MyTk.FILE_FUNC, self.on_video_file)
        self.tk.register_callback(MyTk.SEEK_FUNC, self.on_seek)
        self.tk.register_callback(MyTk.SAVE_FUNC, self.on_save_chapters)
        self.tk.register_callback(MyTk.CLOSE_FUNC, self.on_close_video)
        self.tk.register_callback(MyTk.SCRIPT_FUNC, self.on_run_script)
        self.tk.build_ui()

    def start(self) -> None:
        self.tk.mainloop()

    def on_video_file(self, filename: str) -> None:
        self.video = Video(filename)
        self.video.open()
        self.tk.set_frame_count(self.video.frame_count)
        self.video.seek(0)

    def on_seek(self, pos: float) -> None:
        self.video.seek(pos)
        image = self.video.get_current_frame()
        self.tk.set_video_image(image)

    def on_save_chapters(self, chapters: Tuple[Tuple[str]]) -> None:
        with open(self.video.filename + CHAPTERS_EXT, 'w') as f:
            for i, (frameno, name) in enumerate(chapters, start=1):
                timestamp = self.video.frameno_to_timestamp(frameno)
                print(f"CHAPTER{i:02}={timestamp}", file=f)
                print(f"CHAPTER{i:02}NAME={name}", file=f)

    def on_close_video(self) -> None:
        if self.video:
            self.video.close()
            self.video = None

    def on_run_script(self) -> None:
        if not self.video:
            return

        cmd = f"{self.script} '{self.video.filename}' '{self.video.filename}{CHAPTERS_EXT}'"
        print(f"running: \"{cmd}\"")
        os.system(cmd)

if __name__ == '__main__':
    script = sys.argv[1] if len(sys.argv) >= 2 else None
    app = App(script)
    app.start()
