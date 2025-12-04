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
ARCHIVE_FILE = os.path.join(DOWNLOAD_FOLDER, 'archive.txt')

if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

# --- Helper to delete file after a delay ---
def delete_file_delayed(file_path, delay=60):
    time.sleep(delay)
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception as e:
        print(f"Error during cleanup: {e}")

# --- NEW: Smart Progress Hook ---
def progress_hook(d):
    if d['status'] == 'downloading':
        # 1. Get Current Song Progress
        try:
            p_str = d.get('_percent_str', '0%').replace('%','')
            current_song_percent = float(p_str)
        except:
            current_song_percent = 0

        # 2. Get Playlist Info (m of n)
        # If it's a single video, these might be None, so we default to 1
        current_index = d.get('playlist_index') or 1
        total_files = d.get('n_entries') or d.get('playlist_count') or 1

        # 3. Calculate Global Playlist Progress
        # Formula: ((Previous Songs) + (Current Song Progress)) / Total Songs
        global_percent = ((current_index - 1) + (current_song_percent / 100)) / total_files * 100

        # 4. Clean Filename for display
        filename = os.path.basename(d['filename'])

        # 5. Send everything to UI
        socketio.emit('progress', {
            'type': 'downloading',
            'current_song_percent': current_song_percent,
            'global_percent': global_percent,
            'index': current_index,
            'total': total_files,
            'filename': filename
        })

    elif d['status'] == 'finished':
        # Short pause between songs implies 100% for that specific song
        socketio.emit('progress', {'type': 'processing', 'status': "Converting audio..."})

def download_logic(url):
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': f'{DOWNLOAD_FOLDER}/%(playlist_title)s/%(title)s.%(ext)s',
        'download_archive': ARCHIVE_FILE,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'progress_hooks': [progress_hook],
        'ignoreerrors': True,
        'noplaylist': False, # Ensure we accept playlists
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # We fetch info first to get the title, but we don't download yet
            # Note: extract_info with download=True handles the whole process
            info = ydl.extract_info(url, download=True)
            
            if 'entries' in info:
                playlist_title = info.get('title', 'playlist')
            else:
                playlist_title = info.get('title', 'single_video')
            
            if playlist_title:
                socketio.emit('log', {'data': 'Downloads finished. Zipping files... (This allows 100% completion)'})
                
                # Update UI to show 100% global
                socketio.emit('progress', {
                    'type': 'zipping',
                    'global_percent': 100
                })

                playlist_folder = os.path.join(DOWNLOAD_FOLDER, playlist_title)
                
                timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                safe_title = "".join([c for c in playlist_title if c.isalpha() or c.isdigit() or c==' ']).rstrip()
                zip_filename = f"{safe_title}_{timestamp}.zip"
                zip_path = os.path.join(DOWNLOAD_FOLDER, zip_filename)

                if os.path.exists(playlist_folder):
                    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                        for root, dirs, files in os.walk(playlist_folder):
                            for file in files:
                                zipf.write(os.path.join(root, file), 
                                           os.path.relpath(os.path.join(root, file), 
                                           os.path.join(playlist_folder, '..')))
                    
                    shutil.rmtree(playlist_folder)
                    socketio.emit('done', {'url': f"/download-zip/{zip_filename}"})
                else:
                    socketio.emit('log', {'data': 'No new files were downloaded.'})
            else:
                socketio.emit('log', {'data': 'Could not determine playlist name.'})

    except Exception as e:
        socketio.emit('log', {'data': f"Error: {str(e)}"})

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/download-zip/<filename>')
def download_file(filename):
    file_path = os.path.join(DOWNLOAD_FOLDER, filename)
    threading.Thread(target=delete_file_delayed, args=(file_path, 60)).start()
    return send_file(file_path, as_attachment=True)

@socketio.on('start_download')
def handle_download(data):
    url = data['url']
    emit('log', {'data': 'Fetching playlist info...'})
    threading.Thread(target=download_logic, args=(url,)).start()

@socketio.on('clear_archive')
def handle_clear_archive():
    try:
        if os.path.exists(ARCHIVE_FILE):
            os.remove(ARCHIVE_FILE)
            emit('log', {'data': '✅ History cleared!'})
        else:
            emit('log', {'data': 'History is already empty.'})
    except Exception as e:
        emit('log', {'data': f'Error: {str(e)}'})

if __name__ == '__main__':
    socketio.run(app, debug=True)