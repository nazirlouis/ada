# --- Core Imports ---
import asyncio
import base64
import io
import os
import sys
import traceback
import json
import websockets
import argparse
import threading
from html import escape
import subprocess
import webbrowser
import math
from pathlib import Path

from workspace_files import WorkspaceFiles

# --- PySide6 GUI Imports ---
from PySide6.QtWidgets import (QApplication, QMainWindow, QTextEdit, QLabel,
                               QVBoxLayout, QWidget, QLineEdit, QHBoxLayout,
                               QSizePolicy, QPushButton)
from PySide6.QtCore import QObject, Signal, Slot, Qt, QTimer
from PySide6.QtGui import (QImage, QPixmap, QFont, QFontDatabase, QTextCursor, 
                           QPainter, QPen, QVector3D, QMatrix4x4, QColor, QBrush)
from PySide6.QtOpenGLWidgets import QOpenGLWidget


# --- Media and AI Imports ---
import cv2
import pyaudio
import PIL.Image
from google import genai
from dotenv import load_dotenv
from PIL import ImageGrab
import numpy as np


# --- Load Environment Variables ---
load_dotenv()
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    sys.exit("Error: GEMINI_API_KEY not found. Please set it in your .env file.")
if not ELEVENLABS_API_KEY:
    sys.exit("Error: ELEVENLABS_API_KEY not found. Please check your .env file.")

# --- Configuration ---
FORMAT = pyaudio.paInt16
CHANNELS = 1
SEND_SAMPLE_RATE = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE = 1024
MODEL = "gemini-live-2.5-flash-preview"
VOICE_ID = 'pFZP5JQG7iQjIQuC4Bku'
DEFAULT_MODE = "none"  # Options: "camera", "screen", "none"
MAX_OUTPUT_TOKENS = 100
PROJECT_ROOT = Path(__file__).resolve().parent
WORKSPACE_ROOT = Path(os.getenv("ADA_WORKSPACE", PROJECT_ROOT / "ada_workspace"))
if not WORKSPACE_ROOT.is_absolute():
    WORKSPACE_ROOT = PROJECT_ROOT / WORKSPACE_ROOT

# --- Initialize Clients ---
pya = pyaudio.PyAudio()

# ==============================================================================
# AI Animation Widget
# ==============================================================================
class AIAnimationWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.angle_y = 0
        self.angle_x = 0
        self.sphere_points = self.create_sphere_points()
        self.is_speaking = False
        self.pulse_angle = 0

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_animation)
        self.timer.start(30) # Update about 33 times per second

    def start_speaking_animation(self):
        """Activates the speaking animation state."""
        self.is_speaking = True

    def stop_speaking_animation(self):
        """Deactivates the speaking animation state."""
        self.is_speaking = False
        self.pulse_angle = 0 # Reset for a clean start next time
        self.update() # Schedule a final repaint in the non-speaking state

    def create_sphere_points(self, radius=60, num_points_lat=20, num_points_lon=40):
        """Creates a list of QVector3D points on the surface of a sphere."""
        points = []
        for i in range(num_points_lat + 1):
            lat = math.pi * (-0.5 + i / num_points_lat)
            y = radius * math.sin(lat)
            xy_radius = radius * math.cos(lat)

            for j in range(num_points_lon):
                lon = 2 * math.pi * (j / num_points_lon)
                x = xy_radius * math.cos(lon)
                z = xy_radius * math.sin(lon)
                points.append(QVector3D(x, y, z))
        return points

    def update_animation(self):
        self.angle_y += 0.8
        self.angle_x += 0.2
        if self.is_speaking:
            self.pulse_angle += 0.2
            if self.pulse_angle > math.pi * 2:
                self.pulse_angle -= math.pi * 2

        if self.angle_y >= 360: self.angle_y = 0
        if self.angle_x >= 360: self.angle_x = 0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), Qt.transparent)

        w, h = self.width(), self.height()
        painter.translate(w / 2, h / 2)

        pulse_factor = 1.0
        if self.is_speaking:
            pulse_amplitude = 0.08 # Pulse by 8%
            pulse = (1 + math.sin(self.pulse_angle)) / 2
            pulse_factor = 1.0 + (pulse * pulse_amplitude)

        rotation_y = QMatrix4x4(); rotation_y.rotate(self.angle_y, 0, 1, 0)
        rotation_x = QMatrix4x4(); rotation_x.rotate(self.angle_x, 1, 0, 0)
        rotation = rotation_y * rotation_x

        projected_points = []
        for point in self.sphere_points:
            rotated_point = rotation.map(point)
            
            z_factor = 200 / (200 + rotated_point.z())
            x = (rotated_point.x() * z_factor) * pulse_factor
            y = (rotated_point.y() * z_factor) * pulse_factor
            
            size = (rotated_point.z() + 60) / 120
            alpha = int(50 + 205 * size)
            point_size = 1 + size * 3
            projected_points.append((x, y, point_size, alpha))

        projected_points.sort(key=lambda p: p[2])
        
        for x, y, point_size, alpha in projected_points:
            color = QColor(170, 255, 255, alpha) if self.is_speaking else QColor(0, 255, 255, alpha)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(color))
            painter.drawEllipse(int(x), int(y), int(point_size), int(point_size))

# ==============================================================================
# AI BACKEND LOGIC
# ==============================================================================
class AI_Core(QObject):
    """
    Handles all backend operations. Inherits from QObject to emit signals
    for thread-safe communication with the GUI.
    """
    text_received = Signal(str)
    end_of_turn = Signal()
    frame_received = Signal(QImage)
    search_results_received = Signal(list)
    code_being_executed = Signal(str, str)
    file_list_received = Signal(str, list)
    video_mode_changed = Signal(str)
    speaking_started = Signal()
    speaking_stopped = Signal()

    def __init__(self, video_mode=DEFAULT_MODE):
        super().__init__()
        self.video_mode = video_mode
        self.is_running = True
        self.client = genai.Client(api_key=GEMINI_API_KEY)
        self.workspace_files = WorkspaceFiles(WORKSPACE_ROOT)

        create_folder = {
            "name": "create_folder",
            "description": "Creates a new folder at a relative path inside the ADA workspace.",
            "parameters": {
                "type": "OBJECT",
                "properties": { "folder_path": { "type": "STRING", "description": "The path for the new folder (e.g., 'new_project/assets')."}},
                "required": ["folder_path"]
            }
        }

        create_file = {
            "name": "create_file",
            "description": "Creates a new text file at a relative path inside the ADA workspace.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "file_path": { "type": "STRING", "description": "The path for the new file (e.g., 'new_project/notes.txt')."},
                    "content": { "type": "STRING", "description": "The content to write into the new file."}
                },
                "required": ["file_path", "content"]
            }
        }

        edit_file = {
            "name": "edit_file",
            "description": "Appends content to an existing text file inside the ADA workspace.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "file_path": { "type": "STRING", "description": "The path of the file to edit (e.g., 'project/notes.txt')."},
                    "content": { "type": "STRING", "description": "The content to append to the file."}
                },
                "required": ["file_path", "content"]
            }
        }

        list_files = {
            "name": "list_files",
            "description": "Lists files and folders inside the ADA workspace. Defaults to the workspace root.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "directory_path": { "type": "STRING", "description": "The path of the directory to inspect. Defaults to '.' (current directory) if omitted."}
                }
            }
        }

        read_file = {
            "name": "read_file",
            "description": "Reads a text file at a relative path inside the ADA workspace.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "file_path": { "type": "STRING", "description": "The path of the file to read (e.g., 'project/notes.txt')."}
                },
                "required": ["file_path"]
            }
        }

        open_application = {
            "name": "open_application",
            "description": "Opens or launches a desktop application on the user's computer.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "application_name": { "type": "STRING", "description": "The name of the application to open (e.g., 'Notepad', 'Calculator', 'Chrome')."}
                },
                "required": ["application_name"]
            }
        }

        open_website = {
            "name": "open_website",
            "description": "Opens a given URL in the default web browser.",
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "url": { "type": "STRING", "description": "The full URL of the website to open (e.g., 'https://www.google.com')."}
                },
                "required": ["url"]
            }
        }
        
        tools = [{'google_search': {}}, {'code_execution': {}}, {"function_declarations": [create_folder, create_file, edit_file, list_files, read_file, open_application, open_website]}]
        
        self.config = {
            "response_modalities": ["TEXT"],
            "system_instruction": """
            Your name is Ada and you are my Ai assistant.
            You have access to tools for searching, code execution, and system actions.
            The user is providing a live video stream that can be switched between their webcam and their screen, or turned off.
            Ignore both the webcam and screen content unless the user explicitly asks you to analyze or comment on what you see.
            Follow these guidelines when choosing tools:
            1.  For information or questions, use `Google Search`.
            2.  For math or running python code, use `code_execution`.
            3.  Use file system functions (`create_folder`, `create_file`, `edit_file`, `list_files`, `read_file`) for any file-related tasks.
            4.  If the user asks to open or launch a desktop application, you must use the `open_application` function.
            5.  If the user asks to open a website or a URL, you must use the `open_website` function.
            Prioritize the most appropriate tool for the user's specific request.""",
                                "tools": tools,
                                "max_output_tokens": MAX_OUTPUT_TOKENS
        }
        self.session = None
        self.audio_stream = None
        self.out_queue_gemini = asyncio.Queue(maxsize=20)
        self.response_queue_tts = asyncio.Queue()
        self.audio_in_queue_player = asyncio.Queue()
        self.text_input_queue = asyncio.Queue()
        self.latest_frame = None
        self.tasks = []
        self.loop = asyncio.new_event_loop()

    def _create_folder(self, folder_path):
        try:
            return self.workspace_files.create_folder(folder_path)
        except Exception as e: return {"status": "error", "message": f"An error occurred: {str(e)}"}

    def _create_file(self, file_path, content):
        try:
            return self.workspace_files.create_file(file_path, content)
        except Exception as e: return {"status": "error", "message": f"An error occurred while creating the file: {str(e)}"}

    def _edit_file(self, file_path, content):
        try:
            return self.workspace_files.edit_file(file_path, content)
        except Exception as e: return {"status": "error", "message": f"An error occurred while editing the file: {str(e)}"}

    def _list_files(self, directory_path):
        try:
            return self.workspace_files.list_files(directory_path)
        except Exception as e: return {"status": "error", "message": f"An error occurred: {str(e)}"}

    def _read_file(self, file_path):
        try:
            return self.workspace_files.read_file(file_path)
        except Exception as e: return {"status": "error", "message": f"An error occurred while reading the file: {str(e)}"}

    def _open_application(self, application_name):
        print(f">>> [DEBUG] Attempting to open application: '{application_name}'")
        try:
            if not application_name or not isinstance(application_name, str):
                return {"status": "error", "message": "Invalid application name provided."}
            command, shell_mode = [], False
            if sys.platform == "win32":
                app_map = {"calculator": "calc:", "notepad": "notepad", "chrome": "chrome", "google chrome": "chrome", "firefox": "firefox", "explorer": "explorer", "file explorer": "explorer"}
                app_command = app_map.get(application_name.lower(), application_name)
                command, shell_mode = f"start {app_command}", True
            elif sys.platform == "darwin":
                app_map = {"calculator": "Calculator", "chrome": "Google Chrome", "firefox": "Firefox", "finder": "Finder", "textedit": "TextEdit"}
                app_name = app_map.get(application_name.lower(), application_name)
                command = ["open", "-a", app_name]
            else:
                command = [application_name.lower()]
            subprocess.Popen(command, shell=shell_mode)
            return {"status": "success", "message": f"Successfully launched '{application_name}'."}
        except FileNotFoundError: return {"status": "error", "message": f"Application '{application_name}' not found."}
        except Exception as e: return {"status": "error", "message": f"An error occurred: {str(e)}"}

    def _open_website(self, url):
        print(f">>> [DEBUG] Attempting to open URL: '{url}'")
        try:
            if not url or not isinstance(url, str): return {"status": "error", "message": "Invalid URL provided."}
            if not url.startswith(('http://', 'https://')): url = 'https://' + url
            webbrowser.open(url)
            return {"status": "success", "message": f"Successfully opened '{url}'."}
        except Exception as e: return {"status": "error", "message": f"An error occurred: {str(e)}"}

    @Slot(str)
    def set_video_mode(self, mode):
        """Sets the video source and notifies the GUI."""
        if mode in ["camera", "screen", "none"]:
            self.video_mode = mode
            print(f">>> [INFO] Switched video mode to: {self.video_mode}")
            if mode == "none":
                self.latest_frame = None
            self.video_mode_changed.emit(mode)

    async def stream_video_to_gui(self):
        video_capture = None
        while self.is_running:
            frame = None
            try:
                if self.video_mode == "camera":
                    if video_capture is None: video_capture = await asyncio.to_thread(cv2.VideoCapture, 0)
                    if video_capture.isOpened():
                        ret, frame = await asyncio.to_thread(video_capture.read)
                        if not ret:
                            await asyncio.sleep(0.01)
                            continue
                elif self.video_mode == "screen":
                    if video_capture is not None:
                        await asyncio.to_thread(video_capture.release)
                        video_capture = None
                    screenshot = await asyncio.to_thread(ImageGrab.grab)
                    frame = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
                else:
                    if video_capture is not None:
                        await asyncio.to_thread(video_capture.release)
                        video_capture = None
                    await asyncio.sleep(0.1)
                    continue
                if frame is not None:
                    self.latest_frame = frame
                    h, w, ch = frame.shape
                    bytes_per_line = ch * w
                    qt_image = QImage(frame.data, w, h, bytes_per_line, QImage.Format_BGR888)
                    self.frame_received.emit(qt_image.copy())
                else: self.frame_received.emit(QImage())
                await asyncio.sleep(0.033)
            except Exception as e:
                print(f">>> [ERROR] Video streaming error: {e}")
                if video_capture is not None:
                    await asyncio.to_thread(video_capture.release)
                    video_capture = None
                await asyncio.sleep(1)
        if video_capture is not None: await asyncio.to_thread(video_capture.release)

    async def send_frames_to_gemini(self):
        while self.is_running:
            await asyncio.sleep(1.0)
            if self.video_mode != "none" and self.latest_frame is not None:
                frame_rgb = cv2.cvtColor(self.latest_frame, cv2.COLOR_BGR2RGB)
                pil_img = PIL.Image.fromarray(frame_rgb)
                pil_img.thumbnail([1024, 1024])
                image_io = io.BytesIO()
                pil_img.save(image_io, format="jpeg")
                gemini_data = {"mime_type": "image/jpeg", "data": base64.b64encode(image_io.getvalue()).decode()}
                await self.out_queue_gemini.put(gemini_data)

    async def receive_text(self):
        while self.is_running:
            try:
                turn_urls, turn_code_content, turn_code_result, file_list_data = set(), "", "", None
                turn = self.session.receive()
                async for chunk in turn:
                    if chunk.tool_call and chunk.tool_call.function_calls:
                        function_responses = []
                        for fc in chunk.tool_call.function_calls:
                            args, result = fc.args, {}
                            if fc.name == "create_folder": result = self._create_folder(folder_path=args.get("folder_path"))
                            elif fc.name == "create_file": result = self._create_file(file_path=args.get("file_path"), content=args.get("content"))
                            elif fc.name == "edit_file": result = self._edit_file(file_path=args.get("file_path"), content=args.get("content"))
                            elif fc.name == "list_files":
                                result = self._list_files(directory_path=args.get("directory_path"))
                                if result.get("status") == "success": file_list_data = (result.get("directory_path"), result.get("files"))
                            elif fc.name == "read_file": result = self._read_file(file_path=args.get("file_path"))
                            elif fc.name == "open_application": result = self._open_application(application_name=args.get("application_name"))
                            elif fc.name == "open_website": result = self._open_website(url=args.get("url"))
                            function_responses.append({"id": fc.id, "name": fc.name, "response": result})
                        await self.session.send_tool_response(function_responses=function_responses)
                        continue
                    if chunk.server_content:
                        if hasattr(chunk.server_content, 'grounding_metadata') and chunk.server_content.grounding_metadata:
                            for g_chunk in chunk.server_content.grounding_metadata.grounding_chunks:
                                if g_chunk.web and g_chunk.web.uri: turn_urls.add(g_chunk.web.uri)
                        if chunk.server_content.model_turn:
                            for part in chunk.server_content.model_turn.parts:
                                if part.executable_code: turn_code_content = part.executable_code.code
                                if part.code_execution_result: turn_code_result = part.code_execution_result.output
                    if chunk.text:
                        self.text_received.emit(chunk.text)
                        await self.response_queue_tts.put(chunk.text)
                if file_list_data: self.file_list_received.emit(file_list_data[0], file_list_data[1])
                elif turn_code_content: self.code_being_executed.emit(turn_code_content, turn_code_result)
                elif turn_urls: self.search_results_received.emit(list(turn_urls))
                else:
                    self.code_being_executed.emit("",""); self.search_results_received.emit([]); self.file_list_received.emit("",[])
                self.end_of_turn.emit()
                await self.response_queue_tts.put(None)
            except Exception:
                if not self.is_running: break
                traceback.print_exc()

    async def listen_audio(self):
        mic_info = pya.get_default_input_device_info()
        self.audio_stream = pya.open(format=FORMAT, channels=CHANNELS, rate=SEND_SAMPLE_RATE, input=True, input_device_index=mic_info["index"], frames_per_buffer=CHUNK_SIZE)
        while self.is_running:
            data = await asyncio.to_thread(self.audio_stream.read, CHUNK_SIZE, exception_on_overflow=False)
            if not self.is_running: break
            await self.out_queue_gemini.put({"data": data, "mime_type": "audio/pcm"})

    async def send_realtime(self):
        while self.is_running:
            msg = await self.out_queue_gemini.get()
            if not self.is_running: break
            await self.session.send(input=msg)
            self.out_queue_gemini.task_done()

    async def process_text_input_queue(self):
        while self.is_running:
            text = await self.text_input_queue.get()
            if text is None:
                self.text_input_queue.task_done(); break
            if self.session:
                for q in [self.response_queue_tts, self.audio_in_queue_player]:
                    while not q.empty(): q.get_nowait()
                await self.session.send_client_content(turns=[{"role": "user", "parts": [{"text": text or "."}]}])
            self.text_input_queue.task_done()

    async def tts(self):
        uri = f"wss://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}/stream-input?model_id=eleven_turbo_v2_5&output_format=pcm_24000"
        while self.is_running:
            text_chunk = await self.response_queue_tts.get()
            if text_chunk is None or not self.is_running:
                self.response_queue_tts.task_done(); continue
            
            self.speaking_started.emit()
            try:
                async with websockets.connect(uri) as websocket:
                    await websocket.send(json.dumps({"text": " ", "voice_settings": {"stability": 0.5, "similarity_boost": 0.8}, "xi_api_key": ELEVENLABS_API_KEY,}))
                    async def listen():
                        while self.is_running:
                            try:
                                message = await websocket.recv()
                                data = json.loads(message)
                                if data.get("audio"): await self.audio_in_queue_player.put(base64.b64decode(data["audio"]))
                                elif data.get("isFinal"): break
                            except websockets.exceptions.ConnectionClosed: break
                    listen_task = asyncio.create_task(listen())
                    await websocket.send(json.dumps({"text": text_chunk + " "}))
                    self.response_queue_tts.task_done()
                    while self.is_running:
                        text_chunk = await self.response_queue_tts.get()
                        if text_chunk is None:
                            await websocket.send(json.dumps({"text": ""}))
                            self.response_queue_tts.task_done(); break
                        await websocket.send(json.dumps({"text": text_chunk + " "}))
                        self.response_queue_tts.task_done()
                    await listen_task
            except Exception as e: 
                print(f">>> [ERROR] TTS Error: {e}")
            finally:
                self.speaking_stopped.emit()

    async def play_audio(self):
        stream = await asyncio.to_thread(pya.open, format=pyaudio.paInt16, channels=CHANNELS, rate=RECEIVE_SAMPLE_RATE, output=True)
        while self.is_running:
            bytestream = await self.audio_in_queue_player.get()
            if bytestream and self.is_running: await asyncio.to_thread(stream.write, bytestream)
            self.audio_in_queue_player.task_done()

    async def main_task_runner(self, session):
        self.session = session
        self.tasks.extend([
            asyncio.create_task(self.stream_video_to_gui()), asyncio.create_task(self.send_frames_to_gemini()),
            asyncio.create_task(self.listen_audio()), asyncio.create_task(self.send_realtime()),
            asyncio.create_task(self.receive_text()), asyncio.create_task(self.tts()),
            asyncio.create_task(self.play_audio()), asyncio.create_task(self.process_text_input_queue())
        ])
        await asyncio.gather(*self.tasks, return_exceptions=True)

    async def run(self):
        try:
            async with self.client.aio.live.connect(model=MODEL, config=self.config) as session:
                await self.main_task_runner(session)
        except asyncio.CancelledError: print(f"\n>>> [INFO] AI Core run loop gracefully cancelled.")
        except Exception as e: print(f"\n>>> [ERROR] AI Core run loop encountered an error: {type(e).__name__}: {e}")
        finally:
            if self.is_running: self.stop()

    def start_event_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.run())

    @Slot(str)
    def handle_user_text(self, text):
        if self.is_running and self.loop.is_running(): asyncio.run_coroutine_threadsafe(self.text_input_queue.put(text), self.loop)

    async def shutdown_async_tasks(self):
        if self.text_input_queue: await self.text_input_queue.put(None)
        for task in self.tasks: task.cancel()
        await asyncio.sleep(0.1)

    def stop(self):
        if self.is_running and self.loop.is_running():
            self.is_running = False
            future = asyncio.run_coroutine_threadsafe(self.shutdown_async_tasks(), self.loop)
            try: future.result(timeout=5)
            except Exception as e: print(f">>> [ERROR] Timeout or error during async shutdown: {e}")
        if self.audio_stream and self.audio_stream.is_active():
            self.audio_stream.stop_stream(); self.audio_stream.close()

# ==============================================================================
# STYLED GUI APPLICATION
# ==============================================================================
class MainWindow(QMainWindow):
    user_text_submitted = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("A.D.A. - Advanced Digital Assistant")
        self.setGeometry(100, 100, 1600, 900)
        self.setMinimumSize(1280, 720)
        
        self.setStyleSheet("""
            QMainWindow { 
                background-color: #0a0a1a; 
                font-family: 'Segoe UI', 'Helvetica Neue', sans-serif;
            }
            QWidget#left_panel, QWidget#middle_panel, QWidget#right_panel { 
                background-color: #10182a; 
                border: 1px solid #00a1c1;
                border-radius: 0;
            }
            QLabel#tool_activity_title { 
                color: #00d1ff; 
                font-weight: bold; 
                font-size: 11pt; 
                padding: 5px;
                background-color: #1a2035;
                text-transform: uppercase;
                letter-spacing: 1px;
            }
            QTextEdit#text_display { 
                background-color: transparent; 
                color: #e0e0ff; 
                font-size: 12pt; 
                border: none; 
                padding: 10px; 
            }
            QLineEdit#input_box { 
                background-color: #0a0a1a; 
                color: #e0e0ff; 
                font-size: 11pt; 
                border: 1px solid #00a1c1; 
                border-radius: 0px; 
                padding: 10px; 
            }
            QLineEdit#input_box:focus { border: 1px solid #00ffff; }
            QLabel#video_label { 
                background-color: #000000; 
                border: 1px solid #00a1c1;
                border-radius: 0px; 
            }
            QLabel#tool_activity_display { 
                background-color: #0a0a1a; 
                color: #a0a0ff; 
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 10pt; 
                border: none;
                border-top: 1px solid #00a1c1;
                padding: 8px; 
            }
            QScrollBar:vertical { 
                border: none; 
                background: #10182a; 
                width: 10px; margin: 0px; 
            }
            QScrollBar::handle:vertical { 
                background: #00a1c1; 
                min-height: 20px; 
                border-radius: 0px; 
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
            QPushButton { 
                background-color: transparent; 
                color: #00d1ff; 
                border: 1px solid #00d1ff; 
                padding: 10px; 
                border-radius: 0px; 
                font-size: 10pt; 
                font-weight: bold;
            }
            QPushButton:hover { background-color: #00d1ff; color: #0a0a1a; }
            QPushButton:pressed { background-color: #00ffff; color: #0a0a1a; border: 1px solid #00ffff;}
            QPushButton#video_button_active { 
                background-color: #00ffff; 
                color: #0a0a1a; 
                border: 1px solid #00ffff;
            }
        """)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(15, 15, 15, 15)
        self.main_layout.setSpacing(15)
        self.left_panel = QWidget(); self.left_panel.setObjectName("left_panel")
        self.left_layout = QVBoxLayout(self.left_panel)
        self.left_layout.setContentsMargins(0, 0, 0, 0)
        self.left_layout.setSpacing(0)
        self.tool_activity_title = QLabel("SYSTEM ACTIVITY"); self.tool_activity_title.setObjectName("tool_activity_title")
        self.left_layout.addWidget(self.tool_activity_title)
        self.tool_activity_display = QLabel(); self.tool_activity_display.setObjectName("tool_activity_display")
        self.tool_activity_display.setWordWrap(True); self.tool_activity_display.setAlignment(Qt.AlignTop)
        self.tool_activity_display.setOpenExternalLinks(True); self.tool_activity_display.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.left_layout.addWidget(self.tool_activity_display, 1)
        self.middle_panel = QWidget(); self.middle_panel.setObjectName("middle_panel")
        self.middle_layout = QVBoxLayout(self.middle_panel)
        self.middle_layout.setContentsMargins(0, 0, 0, 15); self.middle_layout.setSpacing(0)

        # --- ADDED: Animation Widget ---
        self.animation_widget = AIAnimationWidget()
        self.animation_widget.setMinimumHeight(150)
        self.animation_widget.setMaximumHeight(200)
        self.middle_layout.addWidget(self.animation_widget, 2) # Add with a stretch factor

        self.text_display = QTextEdit(); self.text_display.setObjectName("text_display"); self.text_display.setReadOnly(True)
        self.middle_layout.addWidget(self.text_display, 5) # Add with a stretch factor
        
        input_container = QWidget()
        input_layout = QHBoxLayout(input_container)
        input_layout.setContentsMargins(15, 10, 15, 0)
        self.input_box = QLineEdit(); self.input_box.setObjectName("input_box")
        self.input_box.setPlaceholderText("Enter command...")
        self.input_box.returnPressed.connect(self.send_user_text)
        input_layout.addWidget(self.input_box)
        self.middle_layout.addWidget(input_container)

        self.right_panel = QWidget(); self.right_panel.setObjectName("right_panel")
        self.right_layout = QVBoxLayout(self.right_panel)
        self.right_layout.setContentsMargins(15, 15, 15, 15); self.right_layout.setSpacing(15)
        
        self.video_container = QWidget()
        self.video_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        video_container_layout = QVBoxLayout(self.video_container)
        video_container_layout.setContentsMargins(0,0,0,0)
        
        self.video_label = QLabel(); self.video_label.setObjectName("video_label")
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

        video_container_layout.addWidget(self.video_label)
        self.right_layout.addWidget(self.video_container)
        
        self.button_container = QHBoxLayout(); self.button_container.setSpacing(10)
        self.webcam_button = QPushButton("WEBCAM")
        self.screenshare_button = QPushButton("SCREEN")
        self.off_button = QPushButton("OFFLINE")
        self.button_container.addWidget(self.webcam_button)
        self.button_container.addWidget(self.screenshare_button)
        self.button_container.addWidget(self.off_button)
        self.right_layout.addLayout(self.button_container)
        
        self.main_layout.addWidget(self.left_panel, 2)
        self.main_layout.addWidget(self.middle_panel, 5)
        self.main_layout.addWidget(self.right_panel, 3)
        self.is_first_ada_chunk = True
        self.current_video_mode = DEFAULT_MODE
        self.setup_backend_thread()

    def setup_backend_thread(self):
        parser = argparse.ArgumentParser()
        parser.add_argument("--mode", type=str, default=DEFAULT_MODE, help="pixels to stream from", choices=["camera", "screen", "none"])
        args, unknown = parser.parse_known_args()
        
        self.ai_core = AI_Core(video_mode=args.mode)
        
        self.user_text_submitted.connect(self.ai_core.handle_user_text)
        self.webcam_button.clicked.connect(lambda: self.ai_core.set_video_mode("camera"))
        self.screenshare_button.clicked.connect(lambda: self.ai_core.set_video_mode("screen"))
        self.off_button.clicked.connect(lambda: self.ai_core.set_video_mode("none"))
        
        self.ai_core.text_received.connect(self.update_text)
        self.ai_core.search_results_received.connect(self.update_search_results)
        self.ai_core.code_being_executed.connect(self.display_executed_code)
        self.ai_core.file_list_received.connect(self.update_file_list)
        self.ai_core.end_of_turn.connect(self.add_newline)
        self.ai_core.frame_received.connect(self.update_frame)
        self.ai_core.video_mode_changed.connect(self.update_video_mode_ui)
        self.ai_core.speaking_started.connect(self.animation_widget.start_speaking_animation)
        self.ai_core.speaking_stopped.connect(self.animation_widget.stop_speaking_animation)

        self.backend_thread = threading.Thread(target=self.ai_core.start_event_loop)
        self.backend_thread.daemon = True
        self.backend_thread.start()
        
        self.update_video_mode_ui(self.ai_core.video_mode)

    def send_user_text(self):
        text = self.input_box.text().strip()
        if text:
            self.text_display.append(f"<p style='color:#00ffff; font-weight:bold;'>&gt; USER:</p><p style='color:#e0e0ff; padding-left: 10px;'>{escape(text)}</p>")
            self.user_text_submitted.emit(text)
            self.input_box.clear()

    @Slot(str)
    def update_video_mode_ui(self, mode):
        self.current_video_mode = mode
        self.webcam_button.setObjectName("")
        self.screenshare_button.setObjectName("")
        self.off_button.setObjectName("")

        if mode == "camera":
            self.webcam_button.setObjectName("video_button_active")
        elif mode == "screen":
            self.screenshare_button.setObjectName("video_button_active")
        elif mode == "none":
            self.off_button.setObjectName("video_button_active")
            self.video_label.clear()

        for button in [self.webcam_button, self.screenshare_button, self.off_button]:
            button.style().unpolish(button)
            button.style().polish(button)

    @Slot(str)
    def update_text(self, text):
        if self.is_first_ada_chunk:
            self.is_first_ada_chunk = False
            self.text_display.append(f"<p style='color:#00d1ff; font-weight:bold;'>&gt; A.D.A.:</p>")
        cursor = self.text_display.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(text)
        self.text_display.verticalScrollBar().setValue(self.text_display.verticalScrollBar().maximum())

    @Slot(list)
    def update_search_results(self, urls):
        base_title = "SYSTEM ACTIVITY"
        if not urls:
            if "SEARCH" in self.tool_activity_title.text():
                self.tool_activity_display.clear(); self.tool_activity_title.setText(base_title)
            return
        self.tool_activity_display.clear()
        self.tool_activity_title.setText(f"{base_title} // SEARCH")
        html_content = ""
        for i, url in enumerate(urls):
            display_text = url.split('//')[1].split('/')[0] if '//' in url else url
            html_content += f'<p style="margin:0; padding: 4px;">{i+1}: <a href="{url}" style="color: #00ffff; text-decoration: none;">{display_text}</a></p>'
        self.tool_activity_display.setText(html_content)

    @Slot(str, str)
    def display_executed_code(self, code, result):
        base_title = "SYSTEM ACTIVITY"
        if not code:
            if "CODE EXEC" in self.tool_activity_title.text():
                 self.tool_activity_display.clear(); self.tool_activity_title.setText(base_title)
            return
        self.tool_activity_display.clear()
        self.tool_activity_title.setText(f"{base_title} // CODE EXEC")
        html = f'<pre style="white-space: pre-wrap; word-wrap: break-word; color: #e0e0ff; font-size: 9pt; line-height: 1.4;">{escape(code)}</pre>'
        if result:
            html += f'<p style="color:#00d1ff; font-weight:bold; margin-top:10px; margin-bottom: 5px;">&gt; OUTPUT:</p><pre style="white-space: pre-wrap; word-wrap: break-word; color: #90EE90; font-size: 9pt;">{escape(result.strip())}</pre>'
        self.tool_activity_display.setText(html)

    @Slot(str, list)
    def update_file_list(self, directory_path, files):
        base_title = "SYSTEM ACTIVITY"
        if not directory_path:
            if "FILESYS" in self.tool_activity_title.text():
                self.tool_activity_display.clear(); self.tool_activity_title.setText(base_title)
            return
        self.tool_activity_display.clear()
        self.tool_activity_title.setText(f"{base_title} // FILESYS")
        html = f'<p style="color:#00d1ff; margin-bottom: 5px;">DIR &gt; <strong>{escape(directory_path)}</strong></p>'
        if not files:
            html += '<p style="margin-top:5px; color:#a0a0ff;"><em>(Directory is empty)</em></p>'
        else:
            folders = sorted([i for i in files if os.path.isdir(os.path.join(directory_path, i))])
            file_items = sorted([i for i in files if not os.path.isdir(os.path.join(directory_path, i))])
            html += '<ul style="list-style-type:none; padding-left: 5px; margin-top: 5px;">'
            for folder in folders: html += f'<li style="margin: 2px 0; color: #87CEEB;">[+] {escape(folder)}</li>'
            for file_item in file_items: html += f'<li style="margin: 2px 0; color: #e0e0ff;">&#9679; {escape(file_item)}</li>'
            html += '</ul>'
        self.tool_activity_display.setText(html)

    @Slot()
    def add_newline(self):
        if not self.is_first_ada_chunk: self.text_display.append("")
        self.is_first_ada_chunk = True

    @Slot(QImage)
    def update_frame(self, image):
        if self.current_video_mode == "none":
            if self.video_label.pixmap():
                self.video_label.clear()
            return

        if not image.isNull():
            pixmap = QPixmap.fromImage(image)
            scaled_pixmap = pixmap.scaled(self.video_container.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.video_label.setPixmap(scaled_pixmap)
        else:
            self.video_label.clear()
            
    def closeEvent(self, event):
        self.ai_core.stop()
        event.accept()

# ==============================================================================
# MAIN EXECUTION
# ==============================================================================
if __name__ == "__main__":
    try:
        app = QApplication(sys.argv)
        window = MainWindow()
        window.show()
        sys.exit(app.exec())
    except KeyboardInterrupt:
        print(">>> [INFO] Application interrupted by user.")
    finally:
        pya.terminate()
        print(">>> [INFO] Application terminated.")
