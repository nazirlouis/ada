Advanced Digital Assistant (A.D.A.)
===================================

A.D.A. is an advanced, real-time digital assistant built with Google's **Gemini-live-2.5-flash-preview** model. It features a responsive graphical user interface (GUI) using **PySide6**, real-time audio communication, and the ability to process live video from either a webcam or a screen share. A.D.A. is equipped with powerful tools for searching, code execution, and managing your local file system.

  
FOR FULL VIDEO TUTORIAL: https://www.youtube.com/watch?v=aooylKf-PeA
  

Features
--------

*   🗣️ **Real-time Conversation**: Seamless, low-latency voice-to-voice interaction powered by Google Gemini and ElevenLabs TTS.
    
*   👀 **Live Visual Input**: A.D.A. can see what you see, with the ability to switch between a live **webcam** feed and a **screen share**. This allows it to answer questions about on-screen content, debug code visually, or provide guidance as you work.
    
*   🛠️ **Integrated Tooling**: The assistant can perform a variety of actions by invoking powerful tools, including:
    
    *   **Google Search**: For real-time information retrieval.
        
    *   **Code Execution**: To run and debug Python code.
        
    *   **File System Management**: Create, edit, read, and list files and folders on your computer.
        
    *   **System Actions**: Open applications and websites.
        
*   🎨 **Dynamic UI**: A responsive and visually appealing GUI built with PySide6, featuring a **3D animated avatar** that pulses when the assistant is speaking.
    
*   💻 **Cross-Platform**: Designed to work on Windows, macOS, and Linux.
    

Setup
-----

Follow these steps to get A.D.A. up and running on your local machine.

### 1\. Prerequisites

Before you begin, ensure you have the following installed:

*   **Python 3.9+**
*   **Git**: [Download Git](https://git-scm.com/downloads)
*   **Gemini API Key**: Get your key from [Google AI Studio](https://aistudio.google.com/app/apikey).
*   **ElevenLabs API Key**: Get your key from the [ElevenLabs website(Affiliate Link Helps Me Out)](https://try.elevenlabs.io/6alaeznm5itg).

### 2\. Clone the Repository

Clone this project's repository from GitHub:

```bash
git clone https://github.com/your-username/your-repo-name.git
cd your-repo-name
```

### 3\. Create a Virtual Environment

It's highly recommended to use a virtual environment to manage dependencies cleanly.

**On Windows:**
```bash
python -m venv venv
venv\Scripts\activate
```

**On macOS/Linux:**
```bash
python -m venv venv
source venv/bin/activate
```

### 4\. Install Dependencies

With your virtual environment active, install all the required Python packages with a single command:

```bash
pip install google-genai python-dotenv elevenlabs PySide6 opencv-python Pillow numpy websockets pyaudio
```

> **Note**: On some systems, `PyAudio` can be tricky to install. If you encounter issues, you may need to install system-level development libraries first (e.g., `portaudio`). Please refer to the PyAudio documentation for platform-specific instructions.

### 5\. Configure API Keys

Create a file named `.env` in the project's root directory to store your API keys securely.

Add your API keys to the .env file:

```
GEMINI_API_KEY="YOUR_GEMINI_API_KEY_HERE"
ELEVENLABS_API_KEY="YOUR_ELEVENLABS_API_KEY_HERE"
```

By default, A.D.A.'s file tools can only access the `ada_workspace` folder. To
use a different workspace, set `ADA_WORKSPACE` in `.env`:

```
ADA_WORKSPACE="path/to/your/workspace"
```

> **Important**: Do not share or commit your .env file to GitHub. The project's .gitignore file is configured to ignore it.

Usage
-----

### Running the Application

Ensure your virtual environment is active, then run the main Python script:

```bash
python ada.py
```

### Command-line Arguments

You can specify the initial video mode when launching the application:

*   \--mode camera: Starts with the webcam feed active.
    
*   \--mode screen: Starts with screen sharing active.
    
*   \--mode none: Starts without a video feed (default).
    

**Example**:

```bash
python ada.py --mode camera
```

### Interacting with A.D.A.

*   **Voice**: The application listens in real-time. Simply speak to the assistant to begin a conversation.
    
*   **Text**: Use the input box to type commands or questions.
    
*   **Video Mode Buttons**: Use the "WEBCAM", "SCREEN", and "OFFLINE" buttons on the right panel to change the visual input source.
    

A.D.A. can answer questions, run code, manage files, open applications, and analyze content on your screen.

Troubleshooting
---------------

If you encounter any issues, here are some common problems and their solutions:

### 1. API Key Errors

*   **Symptom**: The application closes immediately after starting, with an error message like `Error: GEMINI_API_KEY not found`.
*   **Solution**:
    1.  **Check `.env` file location**: Ensure your `.env` file is in the root directory of the project, alongside `ada.py`.
    2.  **Verify Key Names**: Make sure the variable names in your `.env` file are exactly `GEMINI_API_KEY` and `ELEVENLABS_API_KEY`.
    3.  **Check Key Values**: Confirm that you have correctly pasted your API keys without any extra spaces or characters.

### 2. Microphone Not Working

*   **Symptom**: A.D.A. does not respond to your voice commands.
*   **Solution**:
    1.  **Grant Permissions**: Your operating system may be blocking microphone access.
        *   **Windows**: Go to `Settings > Privacy & security > Microphone` and ensure "Let desktop apps access your microphone" is enabled.
        *   **macOS**: Go to `System Settings > Privacy & Security > Microphone` and make sure your terminal or code editor has permission.
    2.  **Set Default Device**: The application uses your system's default input device. Check your OS sound settings to ensure the correct microphone is selected as the default.
    3.  **PyAudio Installation**: If you see errors related to `PyAudio` or `PortAudio` on startup, you may need to reinstall it or install its system dependencies as mentioned in the setup guide.

### 3. Video Feed Not Displaying

*   **Symptom**: The video panel on the right is black when "WEBCAM" mode is active.
*   **Solution**:
    1.  **Grant Permissions**: Just like the microphone, your OS may be blocking camera access. Check your system's privacy settings for the camera.
    2.  **Camera In Use**: Make sure no other application (like Zoom, Teams, OBS, etc.) is currently using your webcam.
    3.  **Correct Device**: The script defaults to the first available camera (index 0). If you have multiple cameras, you may need to adjust the `cv2.VideoCapture(0)` line in `ada.py` to use a different index (e.g., `cv2.VideoCapture(1)`).
