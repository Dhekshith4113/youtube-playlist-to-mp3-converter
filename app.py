import os
import shutil
import zipfile
import threading 
import time
from datetime import datetime
from flask import Flask, render_template, request, send_file
from flask_socketio import SocketIO, emit
import yt_dlp

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, async_mode='threading')

DOWNLOAD_FOLDER = 'downloads'

# Ensure folder exists
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

# --- Helper to delete file after a delay ---
def delete_file_delayed(file_path, delay=60):
    time.sleep(delay)
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception as e:
        print(f"Cleanup error: {e}")

# --- Simplified Progress Hook ---
def progress_hook(d):
    if d['status'] == 'downloading':
        # Get counts (m of n)
        current = d.get('playlist_index', 1)
        total = d.get('n_entries') or d.get('playlist_count') or '?'
        filename = os.path.basename(d['filename'])
        
        # Send simple text update
        msg = f"Downloading song {current} of {total}: {filename}..."
        socketio.emit('status_update', {'msg': msg})

    elif d['status'] == 'finished':
        socketio.emit('status_update', {'msg': "Processing audio (converting to MP3)..."})

def download_logic(url):
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': f'{DOWNLOAD_FOLDER}/%(playlist_title)s/%(title)s.%(ext)s',
        # 'download_archive': ARCHIVE_FILE,  <-- REMOVED
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'progress_hooks': [progress_hook],
        'ignoreerrors': True, # Skip video if it errors out
        'noplaylist': False,
    }

    try:
        socketio.emit('status_update', {'msg': "Fetching Playlist Info..."})
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            if 'entries' in info:
                playlist_title = info.get('title', 'playlist')
            else:
                playlist_title = info.get('title', 'single_video')
            
            if playlist_title:
                socketio.emit('status_update', {'msg': "Downloads complete. Zipping files..."})
                
                playlist_folder = os.path.join(DOWNLOAD_FOLDER, playlist_title)
                
                # Create unique filename
                timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                safe_title = "".join([c for c in playlist_title if c.isalpha() or c.isdigit() or c==' ']).rstrip()
                zip_filename = f"{safe_title}_{timestamp}.zip"
                zip_path = os.path.join(DOWNLOAD_FOLDER, zip_filename)

                if os.path.exists(playlist_folder):
                    # Zip it
                    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                        for root, dirs, files in os.walk(playlist_folder):
                            for file in files:
                                zipf.write(os.path.join(root, file), 
                                           os.path.relpath(os.path.join(root, file), 
                                           os.path.join(playlist_folder, '..')))
                    
                    # Cleanup folder immediately
                    shutil.rmtree(playlist_folder)
                    
                    # Notify Frontend
                    socketio.emit('status_update', {'msg': "Done! Starting download..."})
                    socketio.emit('done', {'url': f"/download-zip/{zip_filename}"})
                else:
                    socketio.emit('status_update', {'msg': "Error: No files were downloaded."})
            else:
                socketio.emit('status_update', {'msg': "Error: Could not determine playlist name."})

    except Exception as e:
        socketio.emit('status_update', {'msg': f"Critical Error: {str(e)}"})

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/download-zip/<filename>')
def download_file(filename):
    file_path = os.path.join(DOWNLOAD_FOLDER, filename)
    # Delete zip 60 seconds after download request
    threading.Thread(target=delete_file_delayed, args=(file_path, 60)).start()
    return send_file(file_path, as_attachment=True)

@socketio.on('start_download')
def handle_download(data):
    url = data['url']
    socketio.emit('status_update', {'msg': "Initializing..."})
    threading.Thread(target=download_logic, args=(url,)).start()

if __name__ == '__main__':
    socketio.run(app, debug=True)
