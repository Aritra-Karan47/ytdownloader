from django.shortcuts import render
from django.shortcuts import render, redirect
from django.http import StreamingHttpResponse, HttpResponse
from pytube import YouTube, Playlist
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

        if playlist_id:
            # Playlist mode
            playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}"
            try:
                playlist = Playlist(playlist_url)
                videos = []
                for idx, video in enumerate(playlist.videos, start=1):
                    videos.append({
                        'index': idx,
                        'title': video.title,
                        'thumbnail_url': video.thumbnail_url,
                        'video_id': video.video_id,
                        'highlighted': idx == int(index)  # Highlight based on URL index
                    })
                return render(request, 'downloader/home.html', {
                    'is_playlist': True,
                    'playlist_title': playlist.title,
                    'videos': videos,
                    'url': url
                })
            except Exception as e:
                return render(request, 'downloader/home.html', {'error': f'Error fetching playlist: {str(e)}'})
        elif video_id:
            # Single video mode
            try:
                video = YouTube(url)
                streams = video.streams.filter(progressive=True, file_extension='mp4').order_by('resolution').desc()
                resolutions = [stream.resolution for stream in streams]
                return render(request, 'downloader/home.html', {
                    'is_video': True,
                    'title': video.title,
                    'thumbnail_url': video.thumbnail_url,
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
        video = YouTube(f"https://www.youtube.com/watch?v={video_id}")
        if resolution == 'highest':
            stream = video.streams.get_highest_resolution()
        else:
            stream = video.streams.filter(res=resolution, progressive=True, file_extension='mp4').first()
        
        if not stream:
            return HttpResponse('No stream found for this resolution', status=404)

        # Download to temp file
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = stream.download(output_path=tmpdir, filename=sanitize_filename(f"{video.title}.mp4"))
            with open(filepath, 'rb') as f:
                response = StreamingHttpResponse(f.read(), content_type='video/mp4')
                response['Content-Disposition'] = f'attachment; filename="{os.path.basename(filepath)}"'
                return response
    except Exception as e:
        return HttpResponse(f'Error downloading video: {str(e)}', status=500)

def download_thumbnail(request, video_id):
    try:
        video = YouTube(f"https://www.youtube.com/watch?v={video_id}")
        thumbnail_url = video.thumbnail_url
        thumbnail_data = requests.get(thumbnail_url).content
        response = HttpResponse(thumbnail_data, content_type='image/jpeg')
        response['Content-Disposition'] = f'attachment; filename="{sanitize_filename(video.title)}_thumbnail.jpg"'
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
            with tempfile.TemporaryDirectory() as tmpdir:
                zip_path = os.path.join(tmpdir, 'playlist.zip')
                with zipfile.ZipFile(zip_path, 'w') as zipf:
                    for video_id in selected_videos:
                        video = YouTube(f"https://www.youtube.com/watch?v={video_id}")
                        stream = video.streams.get_highest_resolution()
                        video_path = stream.download(output_path=tmpdir, filename=sanitize_filename(f"{video.title}.mp4"))
                        zipf.write(video_path, os.path.basename(video_path))
                        os.remove(video_path)  # Clean up temp video

                with open(zip_path, 'rb') as f:
                    response = StreamingHttpResponse(f.read(), content_type='application/zip')
                    response['Content-Disposition'] = 'attachment; filename="playlist_videos.zip"'
                    return response
        except Exception as e:
            return HttpResponse(f'Error downloading playlist: {str(e)}', status=500)

    return redirect('home')

# Create your views here.
