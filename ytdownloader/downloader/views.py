from django.shortcuts import render, redirect
from django.http import StreamingHttpResponse, HttpResponse
import yt_dlp
from urllib.parse import urlparse, parse_qs
import tempfile
import zipfile
import os
import requests
import re

def sanitize_filename(filename):
    return re.sub(r'[<>:"/\\|?*]', '-', filename)

def home(request):
    if request.method == 'POST':
        url = request.POST.get('url')
        if not url:
            return render(request, 'downloader/home.html', {'error': 'Please enter a URL'})

        # Parse URL to detect type
        parsed_url = urlparse(url)
        query_params = parse_qs(parsed_url.query)
        video_id = query_params.get('v', [None])[0]
        playlist_id = query_params.get('list', [None])[0]
        index = query_params.get('index', [1])[0]  # Default to 1 if not provided

        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
        }

        if playlist_id:
            # Playlist mode
            playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}"
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    playlist_info = ydl.extract_info(playlist_url, download=False)
                    videos = []
                    entries = playlist_info.get('entries', [])
                    for idx, entry in enumerate(entries, start=1):
                        if entry:  # Skip None entries
                            videos.append({
                                'index': idx,
                                'title': entry.get('title', 'Unknown'),
                                'thumbnail_url': entry.get('thumbnail'),
                                'video_id': entry.get('id'),
                                'highlighted': idx == int(index)  # Highlight based on URL index
                            })
                return render(request, 'downloader/home.html', {
                    'is_playlist': True,
                    'playlist_title': playlist_info.get('title', 'Unknown Playlist'),
                    'videos': videos,
                    'url': url
                })
            except Exception as e:
                return render(request, 'downloader/home.html', {'error': f'Error fetching playlist: {str(e)}'})
        elif video_id:
            # Single video mode
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    video_info = ydl.extract_info(url, download=False)
                    formats = video_info.get('formats', [])
                    # Filter for progressive MP4 streams (video+audio merged)
                    progressive_mp4s = [
                        f for f in formats
                        if f.get('vcodec') != 'none' and f.get('acodec') != 'none'
                        and f.get('ext') == 'mp4' and f.get('height') is not None
                    ]
                    # Sort by height descending
                    progressive_mp4s.sort(key=lambda f: f.get('height', 0), reverse=True)
                    resolutions = [f"{f.get('height')}p" for f in progressive_mp4s]
                return render(request, 'downloader/home.html', {
                    'is_video': True,
                    'title': video_info.get('title', 'Unknown'),
                    'thumbnail_url': video_info.get('thumbnail'),
                    'video_id': video_id,
                    'resolutions': resolutions,
                    'url': url
                })
            except Exception as e:
                return render(request, 'downloader/home.html', {'error': f'Error fetching video: {str(e)}'})
        else:
            return render(request, 'downloader/home.html', {'error': 'Invalid YouTube URL'})

    return render(request, 'downloader/home.html')

def download_video(request, video_id):
    resolution = request.GET.get('resolution', 'highest')  # Default to highest
    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'outtmpl': '%(title)s.%(ext)s',
        }
        if resolution != 'highest':
            height = int(resolution.replace('p', ''))
            ydl_opts['format'] = f'best[height<={height}][ext=mp4]/best[ext=mp4]'

        downloaded_path = None
        def progress_hook(d):
            if d['status'] == 'finished':
                nonlocal downloaded_path
                downloaded_path = d['filename']

        ydl_opts['progress_hooks'] = [progress_hook]

        with tempfile.TemporaryDirectory() as tmpdir:
            ydl_opts['outtmpl'] = os.path.join(tmpdir, '%(title)s.%(ext)s')
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            if not downloaded_path or not os.path.exists(downloaded_path):
                return HttpResponse('Download failed: No file found', status=404)

            with open(downloaded_path, 'rb') as f:
                response = StreamingHttpResponse(f.read(), content_type='video/mp4')
                response['Content-Disposition'] = f'attachment; filename="{os.path.basename(downloaded_path)}"'
                return response
    except Exception as e:
        return HttpResponse(f'Error downloading video: {str(e)}', status=500)

def download_thumbnail(request, video_id):
    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            video_info = ydl.extract_info(url, download=False)
            thumbnail_url = video_info.get('thumbnail')
            title = video_info.get('title', 'Unknown')
        if not thumbnail_url:
            return HttpResponse('No thumbnail available', status=404)
        thumbnail_data = requests.get(thumbnail_url).content
        response = HttpResponse(thumbnail_data, content_type='image/jpeg')
        response['Content-Disposition'] = f'attachment; filename="{sanitize_filename(title)}_thumbnail.jpg"'
        return response
    except Exception as e:
        return HttpResponse(f'Error downloading thumbnail: {str(e)}', status=500)

def download_playlist(request):
    if request.method == 'POST':
        selected_videos = request.POST.getlist('selected_videos')  # List of video_ids
        action = request.POST.get('action')  # 'videos' or 'thumbnails' or 'all_videos_zip'

        if not selected_videos:
            return redirect('home')

        if action == 'thumbnails':
            # For thumbnails, we'd need to handle multiple, but for simplicity, assume one-by-one via individual buttons
            pass  # Handled via download_thumbnail view

        # For videos or all (zip)
        try:
            urls = [f"https://www.youtube.com/watch?v={vid}" for vid in selected_videos]
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'format': 'best[ext=mp4]',
                'outtmpl': '%(title)s.%(ext)s',
            }

            with tempfile.TemporaryDirectory() as tmpdir:
                ydl_opts['outtmpl'] = os.path.join(tmpdir, '%(title)s.%(ext)s')
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download(urls)

                # Find all downloaded MP4 files in tmpdir
                video_files = [f for f in os.listdir(tmpdir) if f.endswith('.mp4')]
                if not video_files:
                    return HttpResponse('No videos downloaded', status=404)

                zip_path = os.path.join(tmpdir, 'playlist.zip')
                with zipfile.ZipFile(zip_path, 'w') as zipf:
                    for video_file in video_files:
                        video_path = os.path.join(tmpdir, video_file)
                        zipf.write(video_path, video_file)

                with open(zip_path, 'rb') as f:
                    response = StreamingHttpResponse(f.read(), content_type='application/zip')
                    response['Content-Disposition'] = 'attachment; filename="playlist_videos.zip"'
                    return response
        except Exception as e:
            return HttpResponse(f'Error downloading playlist: {str(e)}', status=500)

    return redirect('home')